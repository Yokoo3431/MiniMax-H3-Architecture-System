"""Pinned MiniMax-H3 non-weight support-data contract.

This module deliberately separates the upstream Diffusers release metadata
tree from the already adopted flat-weight root.  It never downloads weights.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from runtime.yaml_compat import safe_load


EXPECTED_REPOSITORY = "MiniMaxAI/MiniMax-H3"
REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
SIDECAR_ROOT_RELATIVE = Path("diffusers") / "MiniMax-H3"
REJECTED_SUFFIXES = {".safetensors"}


def load_h3_sidecar_manifest(repo_root: str | Path) -> dict[str, Any]:
    path = Path(repo_root).resolve() / "configs" / "h3_sidecar_manifest.yaml"
    if not path.is_file():
        raise ValueError("H3 sidecar manifest is missing")
    data = safe_load(path.read_text(encoding="utf-8")) or {}
    validate_h3_sidecar_manifest(data)
    return data


def validate_h3_sidecar_manifest(data: dict[str, Any]) -> None:
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("unsupported H3 sidecar manifest schema")
    source = data.get("source") or {}
    if source.get("repository") != EXPECTED_REPOSITORY:
        raise ValueError("H3 sidecar source must be MiniMaxAI/MiniMax-H3")
    revision = str(source.get("revision") or "").lower()
    if not REVISION_RE.fullmatch(revision) or revision in {"0" * 40}:
        raise ValueError("H3 sidecar source requires an immutable revision SHA")
    base_url = str(source.get("base_url") or "")
    if not base_url.startswith("https://") or "/resolve/" not in base_url:
        raise ValueError("H3 sidecar source must use an HTTPS immutable resolve URL")
    if any(token in base_url.lower() for token in ("/main/", "/master/", "/latest/")):
        raise ValueError("moving H3 sidecar source is not allowed")
    files = data.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("H3 sidecar allow-list is empty")
    seen: set[str] = set()
    for item in files:
        if not isinstance(item, dict):
            raise ValueError("H3 sidecar file entry must be an object")
        relative = str(item.get("path") or "").replace("\\", "/")
        candidate = Path(relative)
        if not relative or candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError("H3 sidecar file path is unsafe")
        if candidate.suffix.lower() in REJECTED_SUFFIXES:
            raise ValueError("safetensors are forbidden in H3 support-data task")
        if relative in seen:
            raise ValueError(f"duplicate H3 sidecar file: {relative}")
        seen.add(relative)
        size = item.get("expected_size")
        digest = str(item.get("sha256") or "")
        if not isinstance(size, int) or size <= 0:
            raise ValueError(f"invalid H3 sidecar size: {relative}")
        if not re.fullmatch(r"[0-9A-Fa-f]{64}", digest):
            raise ValueError(f"invalid H3 sidecar SHA-256: {relative}")
        url = str(item.get("source_url") or "")
        if not url.startswith(base_url) or "/resolve/" not in url:
            raise ValueError(f"H3 sidecar URL is not pinned: {relative}")
    license_data = data.get("license") or {}
    if not license_data.get("identifier") or not license_data.get("path"):
        raise ValueError("H3 sidecar license metadata is incomplete")


def sidecar_target_root(models_root: str | Path) -> Path:
    return Path(models_root).expanduser().resolve() / SIDECAR_ROOT_RELATIVE


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def validate_h3_sidecar_tree(models_root: str | Path, manifest: dict[str, Any]) -> dict[str, Any]:
    """Validate the immutable upstream-layout tree without loading tensors."""
    target = sidecar_target_root(models_root)
    missing: list[str] = []
    mismatched: list[dict[str, Any]] = []
    for item in manifest["files"]:
        path = target / str(item["path"])
        if not path.is_file():
            missing.append(str(item["path"]))
            continue
        if path.stat().st_size != int(item["expected_size"]):
            mismatched.append({"path": str(item["path"]), "reason": "size"})
            continue
        if _sha256(path) != str(item["sha256"]).upper():
            mismatched.append({"path": str(item["path"]), "reason": "sha256"})
    return {
        "target": str(target),
        "missing": missing,
        "mismatched": mismatched,
        "ready": not missing and not mismatched,
        "logical_size": sum(int(item["expected_size"]) for item in manifest["files"]),
    }


__all__ = [
    "EXPECTED_REPOSITORY", "REJECTED_SUFFIXES", "SIDECAR_ROOT_RELATIVE",
    "load_h3_sidecar_manifest", "validate_h3_sidecar_manifest",
    "sidecar_target_root", "validate_h3_sidecar_tree",
]
