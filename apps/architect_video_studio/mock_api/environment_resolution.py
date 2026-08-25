"""Resolve the active user environment independently from installer targets.

The installer may use a validation or proposed install directory.  That path
must never replace an already adopted Native/Models pair in Environment
Center. Resolution first follows configured paths, the application directory,
and known adjacent ComfyUI installation families; only the installed
distribution's explicit auto-discovery mode enables a bounded, signature-only
scan of fixed drives for an existing Runtime or model root.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional


MODEL_SUBDIRS = {
    "dit": "diffusion_models",
    "text_encoder": "text_encoders",
    "video_vae": "vae",
    "audio_vae": "vae",
}

_DISCOVERY_CACHE: dict[str, tuple[float, Optional[Path]]] = {}
_MODEL_DISCOVERY_CACHE: dict[str, tuple[float, Optional[Path]]] = {}
_DISCOVERY_CACHE_SECONDS = 30.0
_DISCOVERY_NAME_HINTS = (
    "comfy", "portable", "runtime", "model", "minimax", "h3",
    "architect", "video", "ai",
)
_SCAN_SKIP_NAMES = {
    "$recycle.bin", "system volume information", "windows", "node_modules",
    ".git", "__pycache__", "appdata", "programdata",
}


@dataclass(frozen=True)
class ActiveEnvironment:
    native_root: Optional[Path]
    models_root: Optional[Path]
    source: str
    validation_native: Optional[Path] = None
    validation_models: Optional[Path] = None


def _resolved(value: Any) -> Optional[Path]:
    if not value or not str(value).strip():
        return None
    try:
        return Path(str(value).strip()).expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        return None


def is_validation_target(path: Optional[Path], repo_root: Path) -> bool:
    if path is None:
        return False
    try:
        path.resolve().relative_to((Path(repo_root) / "validation").resolve())
        return True
    except (ValueError, OSError):
        return False


def is_native_root(path: Optional[Path]) -> bool:
    return bool(path and (path / "python_embeded" / "python.exe").is_file()
                and (path / "ComfyUI" / "main.py").is_file())


def _baseline(repo_root: Path) -> dict:
    path = Path(repo_root) / "configs" / "native_production_baseline.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def model_files_present(models_root: Optional[Path], repo_root: Path,
                        verify_size: bool = True) -> bool:
    if models_root is None or not models_root.is_dir():
        return False
    models = _baseline(repo_root).get("models", {})
    for key, subdir in MODEL_SUBDIRS.items():
        meta = models.get(key, {})
        path = models_root / subdir / str(meta.get("filename") or "")
        if not path.is_file():
            return False
        expected = meta.get("size_bytes") or meta.get("expected_size")
        if verify_size and expected and path.stat().st_size != int(expected):
            return False
    return True


def _candidate_native_from_models(models_root: Optional[Path], repo_root: Path) -> Optional[Path]:
    if models_root is None:
        return None
    current = models_root
    for candidate in (current, *current.parents):
        if is_validation_target(candidate, repo_root):
            continue
        if is_native_root(candidate):
            return candidate
    return None


def _native_models_root(native_root: Optional[Path], repo_root: Path) -> Optional[Path]:
    if native_root is None or is_validation_target(native_root, repo_root):
        return None
    for candidate in (native_root.parent / "Models",
                      native_root / "ComfyUI" / "models"):
        if candidate.is_dir():
            return candidate
    return None


def _runtime_expected_version(repo_root: Path) -> str:
    value = str(_baseline(repo_root).get("runtime", {}).get("comfyui", "0.33.1"))
    return value.split()[0].lstrip("v")


def _runtime_score(candidate: Path, repo_root: Path, environ: dict) -> int:
    if not is_native_root(candidate):
        return -1
    score = 1
    marker = candidate / "runtime_version.json"
    if marker.is_file():
        try:
            data = json.loads(marker.read_text(encoding="utf-8"))
            if str(data.get("comfyui", "")).lstrip("v") == _runtime_expected_version(repo_root):
                score += 4
            if str(data.get("pread", "")).lower() == "pread":
                score += 2
        except (OSError, ValueError, TypeError):
            pass
    custom = candidate / "ComfyUI" / "custom_nodes"
    if (custom / "ComfyUI_RH_MinMaxH3").is_dir():
        score += 1
    if (custom / "ComfyUI-VideoHelperSuite").is_dir():
        score += 1
    if pread_compatible(candidate, environ):
        score += 1
    return score


def _known_runtime_candidates(repo_root: Path, environ: dict) -> list[Path]:
    root = Path(repo_root).resolve()
    candidates: list[Path] = []
    value = _resolved(environ.get("H3_NATIVE_ROOT"))
    if value:
        candidates.append(value)
    env_file = root / "native_env.path"
    if env_file.is_file():
        try:
            value = _resolved(env_file.read_text(encoding="utf-8").splitlines()[0])
            if value:
                candidates.append(value)
        except (OSError, IndexError):
            pass

    parents = [root.parent]
    if root.parent.parent not in parents:
        parents.append(root.parent.parent)
    for parent in parents:
        candidates.extend((
            parent / "runtime" / "native",
            parent / "ComfyUI",
        ))
        family = parent / "ComfyUI"
        if family.is_dir():
            candidates.append(family)
            try:
                candidates.extend(item for item in family.iterdir() if item.is_dir())
            except OSError:
                pass
    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate.resolve()).lower()
        if key not in seen:
            seen.add(key)
            unique.append(candidate.resolve())
    return unique


def _fixed_drive_roots() -> list[Path]:
    if os.name != "nt":
        return []
    roots: list[Path] = []
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        candidate = Path(f"{letter}:\\")
        try:
            if candidate.is_dir():
                roots.append(candidate)
        except OSError:
            pass
    return roots


def _bounded_directory_scan(roots: list[Path], max_depth: int = 5,
                            max_nodes: int = 8000) -> list[Path]:
    """Walk directory names only; never read model contents or whole files."""
    found: list[Path] = []
    queue: list[tuple[Path, int]] = [(root, 0) for root in roots]
    visited: set[str] = set()
    while queue and len(visited) < max_nodes:
        current, depth = queue.pop(0)
        try:
            key = str(current.resolve()).lower()
        except OSError:
            continue
        if key in visited:
            continue
        visited.add(key)
        try:
            children = list(os.scandir(current))
        except OSError:
            continue
        for entry in children:
            if not entry.is_dir(follow_symlinks=False):
                continue
            if entry.name.lower() in _SCAN_SKIP_NAMES:
                continue
            path = Path(entry.path)
            # Traverse the first two levels broadly, then follow only names
            # that are plausible installation/model containers. This keeps a
            # cross-drive scan useful without recursively walking a whole user
            # disk on every Environment Center refresh.
            name = entry.name.casefold()
            if depth >= 2 and not any(hint in name for hint in _DISCOVERY_NAME_HINTS):
                continue
            found.append(path)
            if depth < max_depth:
                queue.append((path, depth + 1))
    return found


def _discovery_key(kind: str, repo_root: Path, environ: dict) -> str:
    values = [
        str(Path(repo_root).resolve()).casefold(),
        str(environ.get("H3_NATIVE_ROOT", "")),
        str(environ.get("H3_MODELS_ROOT", "")),
        str(environ.get("MINIMAX_H3_MODEL_ROOTS", "")),
        str(environ.get("MINIMAX_H3_WEIGHTS_ROOTS", "")),
    ]
    return kind + ":" + "|".join(values).casefold()


def discover_existing_native(repo_root: Path, environ: Optional[dict] = None) -> Optional[Path]:
    environ = environ or os.environ
    cache_key = _discovery_key("native", repo_root, environ)
    cached = _DISCOVERY_CACHE.get(cache_key)
    if cached and time.monotonic() - cached[0] < _DISCOVERY_CACHE_SECONDS:
        return cached[1]
    scored = [(_runtime_score(candidate, repo_root, environ), candidate)
              for candidate in _known_runtime_candidates(repo_root, environ)]
    scored = [(score, candidate) for score, candidate in scored if score >= 0]
    if scored:
        result = max(scored, key=lambda item: item[0])[1]
        _DISCOVERY_CACHE[cache_key] = (time.monotonic(), result)
        return result
    scanned = [(_runtime_score(candidate, repo_root, environ), candidate)
              for candidate in _bounded_directory_scan(_fixed_drive_roots())]
    scanned = [(score, candidate) for score, candidate in scanned if score >= 0]
    result = max(scanned, key=lambda item: item[0])[1] if scanned else None
    _DISCOVERY_CACHE[cache_key] = (time.monotonic(), result)
    return result


def _model_file_count(models_root: Path, repo_root: Path) -> int:
    baseline = _baseline(repo_root).get("models", {})
    count = 0
    for key, subdir in MODEL_SUBDIRS.items():
        filename = str(baseline.get(key, {}).get("filename") or "")
        if filename and (models_root / subdir / filename).is_file():
            count += 1
    return count


def _known_model_candidates(repo_root: Path, native_root: Optional[Path],
                            environ: dict) -> list[Path]:
    root = Path(repo_root).resolve()
    candidates: list[Path] = []
    for key in ("H3_MODELS_ROOT", "MINIMAX_H3_MODEL_ROOTS", "MINIMAX_H3_WEIGHTS_ROOTS"):
        raw = environ.get(key)
        if raw:
            for value in str(raw).split(os.pathsep):
                candidate = _resolved(value)
                if candidate and candidate.name.casefold() == "minimax-h3":
                    candidate = candidate.parent
                if candidate:
                    candidates.append(candidate)
    env_file = root / "models_env.path"
    if env_file.is_file():
        try:
            value = _resolved(env_file.read_text(encoding="utf-8").splitlines()[0])
            if value:
                candidates.append(value)
        except (OSError, IndexError):
            pass
    if native_root:
        candidates.append(native_root / "ComfyUI" / "models")
    candidates.extend((root / "models", root / "runtime" / "native" / "ComfyUI" / "models"))
    for parent in (root.parent, root.parent.parent):
        candidates.append(parent / "models")
        family = parent / "ComfyUI"
        if family.is_dir():
            candidates.append(family / "models")
            try:
                candidates.extend(item / "ComfyUI" / "models"
                                  for item in family.iterdir() if item.is_dir())
            except OSError:
                pass
    return [candidate.resolve() for candidate in candidates if candidate]


def discover_existing_models(repo_root: Path, native_root: Optional[Path],
                             environ: Optional[dict] = None) -> Optional[Path]:
    environ = environ or os.environ
    cache_key = _discovery_key("models", repo_root, environ) + "|native=" + str(native_root or "").casefold()
    cached = _MODEL_DISCOVERY_CACHE.get(cache_key)
    if cached and time.monotonic() - cached[0] < _DISCOVERY_CACHE_SECONDS:
        return cached[1]
    scored: list[tuple[int, Path]] = []
    seen: set[str] = set()
    for candidate in _known_model_candidates(repo_root, native_root, environ):
        key = str(candidate).lower()
        if key in seen or not candidate.is_dir():
            continue
        seen.add(key)
        scored.append((_model_file_count(candidate, repo_root), candidate))
    populated = [(count, candidate) for count, candidate in scored if count > 0]
    if populated:
        result = max(populated, key=lambda item: item[0])[1]
        _MODEL_DISCOVERY_CACHE[cache_key] = (time.monotonic(), result)
        return result
    scanned: list[tuple[int, Path]] = []
    for candidate in _bounded_directory_scan(_fixed_drive_roots()):
        count = _model_file_count(candidate, repo_root)
        if count > 0:
            scanned.append((count, candidate))
    if scanned:
        result = max(scanned, key=lambda item: item[0])[1]
        _MODEL_DISCOVERY_CACHE[cache_key] = (time.monotonic(), result)
        return result
    result = _native_models_root(native_root, repo_root)
    _MODEL_DISCOVERY_CACHE[cache_key] = (time.monotonic(), result)
    return result


def _legacy_configured_native(repo_root: Path) -> Optional[Path]:
    """Read existing project environment metadata as a migration fallback."""
    candidates: list[Path] = []
    config = Path(repo_root) / "configs" / "system_config.json"
    try:
        data = json.loads(config.read_text(encoding="utf-8"))
        defaults = data.get("comfyui_defaults", {})
        for key in ("python_executable", "comfyui_root"):
            value = _resolved(defaults.get(key))
            if value:
                candidates.append(value.parent.parent if key == "python_executable" else value.parent)
    except (OSError, ValueError, TypeError):
        pass
    audit = Path(repo_root) / "configs" / "audit_environment_report.json"
    try:
        data = json.loads(audit.read_text(encoding="utf-8"))
        value = _resolved((data.get("comfyui") or {}).get("installation_path"))
        if value:
            candidates.append(value)
    except (OSError, ValueError, TypeError):
        pass
    for candidate in candidates:
        if is_native_root(candidate) and not is_validation_target(candidate, repo_root):
            return candidate
    return None


def resolve_active_environment(repo_root: Path, state: Optional[dict] = None,
                               environ: Optional[dict] = None,
                               use_legacy_config: bool = False,
                               auto_discover: bool = False) -> ActiveEnvironment:
    """Resolve an adopted pair, keeping validation targets out of active state."""
    root = Path(repo_root).resolve()
    state = state or {}
    environ = environ or os.environ
    raw_native = _resolved(state.get("native_root") or environ.get("H3_NATIVE_ROOT"))
    raw_models = _resolved(state.get("models_root") or environ.get("H3_MODELS_ROOT"))

    validation_native = raw_native if is_validation_target(raw_native, root) else None
    validation_models = raw_models if is_validation_target(raw_models, root) else None
    native = None if validation_native else raw_native
    models = None if validation_models else raw_models
    source = "configured"

    # If a validation runtime was left in setup state but the configured model
    # root is a real adopted Native tree, recover the matching Native root from
    # that model path.  This is path-local adoption, not a disk scan.
    if native is None:
        native = _candidate_native_from_models(models, root)
        if native is not None:
            source = "adopted_from_models_root"

    if native is None and use_legacy_config:
        native = _legacy_configured_native(root)
        if native is not None:
            source = "adopted_legacy_config"

    # A portable installer can leave a proposed path in state while a
    # compatible production Runtime already exists beside it. Adopt only from
    # known application/ComfyUI locations, never by scanning an entire drive.
    # A valid-looking skeleton is not enough for production adoption.  When
    # the configured Runtime is incomplete, compare it with known existing
    # candidates so a fresh install does not hide a healthy Runtime elsewhere.
    if auto_discover and (native is None or not is_native_root(native) or
                          _runtime_score(native, root, environ) < 4):
        discovered = discover_existing_native(root, environ)
        current_score = _runtime_score(native, root, environ) if native else -1
        discovered_score = _runtime_score(discovered, root, environ) if discovered else -1
        if discovered is not None and discovered_score >= 4 and discovered_score > current_score:
            native = discovered
            source = "auto_discovered_existing_runtime"

    # Prefer a populated shared Models Root over an empty installer target.
    # This deliberately compares presence only; size/hash verification remains
    # the later environment/installation-plan responsibility.
    current_model_count = _model_file_count(models, root) if models and models.is_dir() else 0
    models_needs_discovery = models is None or not models.is_dir() or current_model_count < 4
    if auto_discover and models_needs_discovery:
        discovered_models = discover_existing_models(root, native, environ)
        discovered_count = (_model_file_count(discovered_models, root)
                            if discovered_models and discovered_models.is_dir() else 0)
        if discovered_models is not None and discovered_count > current_model_count:
            models = discovered_models
            if source == "configured":
                source = "auto_discovered_existing_models"

    # Prefer the adopted Native tree's own model contract when a validation
    # model target was mixed into setup state.
    if native is not None and models is None:
        candidate_models = _native_models_root(native, root)
        if candidate_models is not None:
            models = candidate_models
            source = "adopted_native_models_pair" if source == "configured" else source

    # A configured non-validation model path remains useful even when it is
    # incomplete: it is an active user choice, not an installer default.
    return ActiveEnvironment(native, models, source, validation_native, validation_models)


def resolve_install_roots(repo_root: Path, state: Optional[dict] = None,
                          environ: Optional[dict] = None,
                          use_legacy_config: bool = False,
                          auto_discover: bool = False) -> tuple[Path, Path, ActiveEnvironment]:
    """Return active roots when available, otherwise safe proposed targets."""
    root = Path(repo_root).resolve()
    active = resolve_active_environment(root, state, environ,
                                        use_legacy_config=use_legacy_config,
                                        auto_discover=auto_discover)
    manifest = _baseline(root)
    install = manifest.get("installation", {})
    raw_native = _resolved((state or {}).get("native_root") or
                           (environ or os.environ).get("H3_NATIVE_ROOT"))
    raw_models = _resolved((state or {}).get("models_root") or
                           (environ or os.environ).get("H3_MODELS_ROOT"))
    native = active.native_root or (raw_native if raw_native and not is_validation_target(raw_native, root) else None)
    models = active.models_root or (raw_models if raw_models and not is_validation_target(raw_models, root) else None)
    native = native or root / install.get("default_runtime_root", "runtime/native")
    models = models or root / install.get("default_models_root", "Models")
    return native.resolve(), models.resolve(), active


def pread_compatible(native_root: Optional[Path], environ: Optional[dict] = None) -> bool:
    """Recognize either the project shim or the validated production H3 patch."""
    if native_root is None:
        return False
    environ = environ or os.environ
    if str(environ.get("H3_WINDOWS_SAFE_LOAD", "")).lower() != "pread":
        return False
    shim = native_root / "ComfyUI" / "custom_nodes" / "windows_safe_load"
    if shim.is_dir():
        return True
    for relative in (
        "custom_nodes/ComfyUI_RH_MinMaxH3/minimax_h3_nodes/runtime/model_loader/_impl.py",
        "custom_nodes/ComfyUI_RH_MinMaxH3/minimax_h3_nodes/runtime/qwen_encoder/loading.py",
    ):
        path = native_root / "ComfyUI" / relative
        try:
            if "_MmapSafetensorsReader" not in path.read_text(encoding="utf-8", errors="ignore"):
                return False
        except OSError:
            return False
    return True


__all__ = [
    "ActiveEnvironment", "MODEL_SUBDIRS", "is_native_root",
    "is_validation_target", "model_files_present", "pread_compatible",
    "discover_existing_native", "discover_existing_models",
    "resolve_active_environment", "resolve_install_roots",
]
