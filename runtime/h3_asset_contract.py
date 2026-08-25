"""CPU-only H3 asset contract shared by detection and installation.

The contract is declared in ``configs/h3_sidecar_manifest.yaml``.  This
module deliberately checks only metadata/configuration files; it never opens
model tensors and never downloads or modifies assets.
"""

from __future__ import annotations

from pathlib import Path
import hashlib
from typing import Any, Mapping

from runtime.h3_sidecar import load_h3_sidecar_manifest


CONTRACT_KEY = "runtime_asset_contract"
INCOMPATIBLE_RUNTIME = "INCOMPATIBLE_RUNTIME"


def load_h3_asset_contract(repo_root: str | Path) -> dict[str, Any]:
    manifest = load_h3_sidecar_manifest(repo_root)
    contract = manifest.get(CONTRACT_KEY)
    if not isinstance(contract, dict):
        raise ValueError("H3 runtime asset contract is missing")
    validate_h3_asset_contract(contract)
    return contract


def validate_h3_asset_contract(contract: Mapping[str, Any]) -> None:
    if contract.get("schema_version") != 1:
        raise ValueError("unsupported H3 runtime asset contract schema")
    required = contract.get("required")
    if not isinstance(required, list) or not required:
        raise ValueError("H3 runtime asset contract has no required assets")
    seen: set[str] = set()
    for item in [*required, *(contract.get("optional") or [])]:
        if not isinstance(item, dict):
            raise ValueError("H3 runtime asset entry must be an object")
        logical = str(item.get("logical_component") or "")
        if not logical or logical in seen:
            raise ValueError(f"duplicate/empty H3 runtime asset: {logical}")
        seen.add(logical)
        if item.get("required") not in (True, False):
            raise ValueError(f"H3 runtime asset required flag is invalid: {logical}")
        paths = item.get("accepted_paths")
        if not isinstance(paths, list) or not paths:
            raise ValueError(f"H3 runtime asset has no accepted paths: {logical}")
        for relative in paths:
            path = Path(str(relative).replace("\\", "/"))
            if path.is_absolute() or ".." in path.parts:
                raise ValueError(f"unsafe H3 runtime asset path: {relative}")
        if not item.get("source_status") or not item.get("checksum_status"):
            raise ValueError(f"H3 runtime asset provenance is incomplete: {logical}")


def _manifest_file_index(repo_root: str | Path) -> dict[str, dict[str, Any]]:
    manifest = load_h3_sidecar_manifest(repo_root)
    return {str(item["path"]): item for item in manifest["files"]}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def evaluate_h3_asset_contract(models_root: str | Path,
                               repo_root: str | Path) -> dict[str, Any]:
    """Evaluate all required logical assets without loading any tensor."""
    root = Path(models_root).expanduser().resolve()
    contract = load_h3_asset_contract(repo_root)
    manifest_files = _manifest_file_index(repo_root)
    assets: list[dict[str, Any]] = []
    missing: list[str] = []
    mismatched: list[str] = []
    groups: dict[str, dict[str, Any]] = {}

    for item in contract["required"]:
        logical = str(item["logical_component"])
        accepted = [str(value).replace("\\", "/") for value in item["accepted_paths"]]
        found_path: Path | None = None
        found_relative = ""
        for relative in accepted:
            candidate = root / relative
            if candidate.is_file():
                found_path = candidate
                found_relative = relative
                break

        checksum_status = "NOT_PRESENT"
        source_status = str(item.get("source_status"))
        if found_path is not None:
            # Canonical manifest paths are hash-checked. An adopted path is
            # only present-but-unverified when no matching immutable manifest
            # entry exists.
            manifest_item = manifest_files.get(found_relative)
            if manifest_item is None:
                # Runtime candidates are rooted at the selected Models Root,
                # while sidecar manifest paths are rooted at MiniMax-H3's
                # upstream release tree. Prefer logical-component identity;
                # duplicated upstream processor/tokenizer entries are accepted
                # only when their pinned size and digest agree.
                manifest_item = next(
                    (value for value in manifest_files.values()
                     if value.get("logical_component") == logical),
                    None,
                )
            if manifest_item is None:
                basename = Path(found_relative).name
                candidates = [value for value in manifest_files.values()
                              if Path(str(value.get("path"))).name == basename]
                if candidates and all(
                    int(value["expected_size"]) == int(candidates[0]["expected_size"])
                    and str(value["sha256"]).upper() == str(candidates[0]["sha256"]).upper()
                    for value in candidates
                ):
                    manifest_item = candidates[0]
            if manifest_item is not None:
                if found_path.stat().st_size != int(manifest_item["expected_size"]):
                    checksum_status = "SIZE_MISMATCH"
                elif _sha256(found_path) != str(manifest_item["sha256"]).upper():
                    checksum_status = "SHA256_MISMATCH"
                else:
                    checksum_status = "VERIFIED_BY_MANIFEST"
            else:
                checksum_status = "PRESENT_UNVERIFIED"
        else:
            missing.append(logical)

        strict_checksum = str(item.get("checksum_policy") or "") == "strict"
        if found_path is not None and checksum_status in ("SIZE_MISMATCH", "SHA256_MISMATCH") and not strict_checksum:
            checksum_status = "PRESENT_UNVERIFIED"
        status = "PASS" if found_path is not None and checksum_status in (
            "VERIFIED_BY_MANIFEST", "PRESENT_UNVERIFIED") else (
            "MISSING" if found_path is None else "MISMATCH")
        entry = {
            "logical_component": logical,
            "required": True,
            "status": status,
            "source_status": source_status,
            "checksum_status": checksum_status,
            "accepted_paths": accepted,
            "resolved_path": str(found_path) if found_path else "",
            "resolved_relative": found_relative,
        }
        assets.append(entry)
        group = str(item.get("group") or "sidecar")
        groups.setdefault(group, {"status": "PASS", "missing": [], "assets": []})
        groups[group]["assets"].append(entry)
        if status != "PASS":
            if status == "MISMATCH":
                mismatched.append(logical)
            groups[group]["status"] = "MISSING"
            groups[group]["missing"].append(logical)

    ready = not missing and not mismatched
    for group in groups.values():
        if group["status"] != "PASS":
            group["status"] = "MISSING"
    return {
        "status": "READY" if ready else INCOMPATIBLE_RUNTIME,
        "ready": ready,
        "code": "READY" if ready else INCOMPATIBLE_RUNTIME,
        "root": str(root),
        "assets": assets,
        "groups": groups,
        "missing": missing,
        "mismatched": mismatched,
        "required_count": len(assets),
        "ready_count": len(assets) - len(missing),
    }


__all__ = [
    "CONTRACT_KEY", "INCOMPATIBLE_RUNTIME", "load_h3_asset_contract",
    "validate_h3_asset_contract", "evaluate_h3_asset_contract",
]
