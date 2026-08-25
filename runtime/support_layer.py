"""Immutable support-layer provenance and installation primitives for R2A.

This module deliberately knows nothing about ComfyUI inference.  It validates
support sources, applies the audited production patch, and fingerprints source
trees so a moving branch cannot silently enter a frozen runtime.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlparse

from runtime.yaml_compat import safe_load


FROZEN_NODE_NAMES = (
    "RHMiniMaxH3DecodeAV",
    "RHMiniMaxH3DualSigmaSampler",
    "RHMiniMaxH3EmptyAVLatent",
    "RHMiniMaxH3FL2VAEncode",
    "RHMiniMaxH3FL2VAFirstFrameCondition",
    "RHMiniMaxH3FL2VATarget",
    "RHMiniMaxH3ModelLoader",
    "RHMiniMaxH3T2VATextEncode",
    "RHMiniMaxH3TextEncoderLoader",
    "RHMiniMaxH3VAELoader",
    "VHS_VideoCombine",
)
SUPPORT_LAYER_IDS = ("minimax_h3_nodes", "video_helper_suite")
FROZEN_CORE_PACKAGES = frozenset({
    "torch", "torchvision", "torchaudio", "cuda", "cuda-runtime",
    "comfy-kitchen",
})
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


def load_support_manifest(repo_root: Path) -> dict:
    path = Path(repo_root) / "configs" / "support_layer_manifest.yaml"
    data = safe_load(path.read_text(encoding="utf-8")) or {}
    if data.get("schema_version") != 1:
        raise ValueError("unsupported support-layer manifest schema")
    return data


def load_release_runtime_manifest(repo_root: Path) -> dict:
    """Load the current release contract, separate from upstream provenance."""
    path = Path(repo_root) / "configs" / "release_runtime_manifest.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def support_entries(manifest: dict) -> list[tuple[str, dict]]:
    layers = manifest.get("support_layers") or {}
    return [(key, layers[key]) for key in SUPPORT_LAYER_IDS if key in layers]


def validate_support_entry(layer_id: str, entry: dict) -> None:
    """Reject branch refs, repository substitution, and malformed pins."""
    commit = str(entry.get("commit") or "")
    if not _COMMIT_RE.fullmatch(commit):
        raise ValueError(f"{layer_id}: immutable 40-character commit is required")
    repository = str(entry.get("repository") or "")
    parsed = urlparse(repository)
    if parsed.scheme.lower() != "https" or parsed.netloc.lower() != "github.com":
        raise ValueError(f"{layer_id}: repository must be HTTPS github.com")
    repo_path = parsed.path.strip("/")
    if not repo_path.endswith(".git") or repo_path.count("/") != 1:
        raise ValueError(f"{layer_id}: repository owner/name is invalid")
    owner, repo = repo_path[:-4].split("/", 1)
    archive = str(entry.get("source_archive_url") or "")
    expected_archive = f"https://github.com/{owner}/{repo}/archive/{commit}.zip"
    if archive != expected_archive:
        raise ValueError(f"{layer_id}: source archive is not the exact commit archive")
    archive_size = entry.get("archive_size")
    archive_sha = str(entry.get("archive_sha256") or "")
    if not isinstance(archive_size, int) or archive_size <= 0:
        raise ValueError(f"{layer_id}: archive size must be pinned")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", archive_sha):
        raise ValueError(f"{layer_id}: archive SHA-256 must be pinned")
    lowered = " ".join(str(entry.get(k) or "") for k in ("branch", "ref", "revision", "source_archive_url")).lower()
    if any(token in lowered for token in ("/main", "/master", "/latest", " branch", " latest")):
        raise ValueError(f"{layer_id}: moving branch/latest source is forbidden")
    required = set(entry.get("required_nodes") or [])
    if layer_id == "minimax_h3_nodes" and not set(FROZEN_NODE_NAMES[:-1]).issubset(required):
        raise ValueError("H3 support manifest is missing a frozen node")
    if layer_id == "video_helper_suite" and "VHS_VideoCombine" not in required:
        raise ValueError("VideoHelperSuite manifest is missing VHS_VideoCombine")
    if not entry.get("license"):
        raise ValueError(f"{layer_id}: license must be recorded")


def validate_support_manifest(manifest: dict) -> None:
    entries = dict(support_entries(manifest))
    if set(entries) != set(SUPPORT_LAYER_IDS):
        raise ValueError("both pinned support layers are required")
    for layer_id, entry in entries.items():
        validate_support_entry(layer_id, entry)
    order = list(manifest.get("installation_order") or [])
    required_order = ["comfyui_runtime", "minimax_h3_nodes", "video_helper_suite",
                      "support_layer_dependencies", "pread_shim", "prompt_skill", "models"]
    if order != required_order:
        raise ValueError("support installation order drifted from the frozen contract")
    for name in (manifest.get("dependency_policy", {}).get("frozen_core") or []):
        if str(name).lower() in FROZEN_CORE_PACKAGES:
            continue
    for spec in manifest.get("dependency_policy", {}).get("install_required", []) or []:
        package = str(spec).split("==", 1)[0].strip().lower()
        if package in FROZEN_CORE_PACKAGES:
            raise ValueError("frozen Torch/CUDA packages cannot be installed by support layer")


def _source_files(root: Path) -> list[Path]:
    return sorted(
        p for p in Path(root).rglob("*")
        if p.is_file()
        and "__pycache__" not in p.parts
        and p.suffix.lower() != ".pyc"
        and not p.name.endswith(".bak_crashfix")
        # The lock is generated metadata containing the fingerprint; including
        # it would make the fingerprint self-referential and non-reproducible.
        and p.name != "support_layer.lock.json"
    )


def source_tree_fingerprint(root: Path) -> str:
    """Fingerprint path + Git blob identity without requiring Git installed."""
    digest = hashlib.sha256()
    root = Path(root).resolve()
    for path in _source_files(root):
        data = path.read_bytes()
        blob = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8") + b"\0" + blob.encode("ascii") + b"\0")
    return digest.hexdigest()


def _safe_patch_path(root: Path, name: str) -> Path:
    relative = Path(name)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("support patch escaped its target root")
    target = (Path(root) / relative).resolve()
    if not str(target).startswith(str(Path(root).resolve())):
        raise ValueError("support patch escaped its target root")
    return target


def apply_unified_patch(patch_path: Path, target_root: Path) -> None:
    """Apply the small audited unified patch without depending on Git/patch.exe."""
    lines = Path(patch_path).read_text(encoding="utf-8").splitlines(keepends=True)
    index = 0
    hunk_re = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
    while index < len(lines):
        if not lines[index].startswith("--- "):
            index += 1
            continue
        index += 1
        if index >= len(lines) or not lines[index].startswith("+++ "):
            raise ValueError("malformed support patch file header")
        new_name = lines[index][4:].strip().split("\t", 1)[0]
        target = _safe_patch_path(target_root, new_name[2:] if new_name.startswith("b/") else new_name)
        index += 1
        original = target.read_text(encoding="utf-8").splitlines(keepends=True)
        offset = 0
        while index < len(lines) and lines[index].startswith("@@ "):
            match = hunk_re.match(lines[index])
            if not match:
                raise ValueError("malformed support patch hunk")
            old_start = int(match.group(1))
            old_count = int(match.group(2)) if match.group(2) is not None else 1
            new_count = int(match.group(4)) if match.group(4) is not None else 1
            index += 1
            hunk: list[str] = []
            while index < len(lines) and not lines[index].startswith(("@@ ", "--- ")):
                line = lines[index]
                if line.startswith((" ", "+", "-")):
                    hunk.append(line)
                elif line == "\n":
                    # Readable separators between the manually audited hunks
                    # are not part of the unified-diff body.
                    pass
                elif not line.startswith("\\"):
                    raise ValueError("malformed support patch body")
                index += 1
            position = old_start - 1 + offset
            consumed: list[str] = []
            replacement: list[str] = []
            for line in hunk:
                marker, value = line[0], line[1:]
                if marker in " -":
                    consumed.append(value)
                if marker in " +":
                    replacement.append(value)
            if original[position:position + len(consumed)] != consumed:
                raise ValueError(f"support patch context mismatch in {target.name}")
            original[position:position + len(consumed)] = replacement
            offset += new_count - old_count
        target.write_text("".join(original), encoding="utf-8")


def dependency_delta(production: dict, isolated: dict, manifest: dict) -> list[dict]:
    """Return an explicit, non-mutating dependency decision table."""
    expected = manifest.get("dependency_policy", {}).get("production_versions", {})
    result = []
    for package, required in expected.items():
        current = isolated.get(package)
        if package in {"torch", "torchvision", "torchaudio", "comfy-kitchen"}:
            action = "FROZEN_CORE_PROTECTED"
        elif current == required:
            action = "ALREADY_SATISFIED"
        elif current is None or current == "MISSING":
            action = "INSTALL_REQUIRED"
        elif package == "transformers" and str(current) != str(required):
            action = "VERSION_CONFLICT"
        else:
            action = "EXPECTED_DIFFERENCE"
        result.append({"package": package, "production": required,
                       "isolated": current or "MISSING", "action": action})
    return result


__all__ = [
    "FROZEN_CORE_PACKAGES", "FROZEN_NODE_NAMES", "SUPPORT_LAYER_IDS",
    "apply_unified_patch", "dependency_delta", "load_support_manifest",
    "load_release_runtime_manifest",
    "source_tree_fingerprint", "support_entries", "validate_support_entry",
    "validate_support_manifest",
]
