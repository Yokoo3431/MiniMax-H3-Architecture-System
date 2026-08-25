"""Path resolution shared by the public Windows entry points.

This module is deliberately independent of ComfyUI. Setup Mode must be able
to start when the Native runtime, models, or native_env.path do not exist.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Iterable, Optional


def project_root(anchor: Optional[Path] = None) -> Path:
    """Return the repository/distribution root from this module's location."""
    return (Path(anchor) if anchor else Path(__file__)).resolve().parent.parent


def configured_native_root(root: Optional[Path] = None) -> Optional[Path]:
    """Resolve a configured Native root without requiring it to exist."""
    root = Path(root or project_root()).resolve()
    value = os.environ.get("H3_NATIVE_ROOT", "").strip()
    if not value:
        path_file = root / "native_env.path"
        if path_file.is_file():
            lines = path_file.read_text(encoding="utf-8-sig").splitlines()
            value = lines[0].strip() if lines else ""
    return Path(value).expanduser().resolve() if value else None


def _candidate_paths(root: Path, native_root: Optional[Path]) -> Iterable[Path]:
    env_value = os.environ.get("H3_BOOTSTRAP_PYTHON", "").strip()
    if env_value:
        yield Path(env_value).expanduser()
    yield root / "runtime" / "bootstrap" / "python.exe"
    yield root / "userdata" / "cache" / "runtime" / "comfyui_runtime" / "python_embeded" / "python.exe"
    if native_root:
        yield native_root / "python_embeded" / "python.exe"
    current = Path(sys.executable)
    if current.name.lower().startswith("python"):
        yield current
    found = shutil.which("python")
    if found:
        yield Path(found)


def resolve_bootstrap_python(root: Optional[Path] = None,
                             native_root: Optional[Path] = None) -> Optional[Path]:
    root = Path(root or project_root()).resolve()
    native_root = native_root or configured_native_root(root)
    seen: set[str] = set()
    for candidate in _candidate_paths(root, native_root):
        candidate = Path(candidate).expanduser()
        key = os.path.normcase(str(candidate))
        if key in seen:
            continue
        seen.add(key)
        if candidate.is_file():
            return candidate.resolve()
    return None


__all__ = ["configured_native_root", "project_root", "resolve_bootstrap_python"]
