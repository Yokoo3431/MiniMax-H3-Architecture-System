"""Canonical execution paths for the installed Architect Video Studio runtime.

The job layer receives one resolved contract instead of reconstructing paths
from the current working directory or placeholder strings.  This module is
purely filesystem/configuration logic; it never loads a model or touches CUDA.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional


class RuntimePathError(ValueError):
    """The selected installation cannot satisfy the execution path contract."""


def _clean(value: object) -> Optional[str]:
    text = str(value or "").strip()
    if not text or "<NATIVE_ROOT>" in text or "<APP_ROOT>" in text:
        return None
    return text


def _configured_file(root: Path, name: str) -> Optional[Path]:
    path = root / name
    try:
        # PowerShell's UTF-8 writer may emit a BOM.  It is metadata, not part
        # of a Windows path; accepting both BOM and BOM-less files keeps an
        # installed path contract stable across launcher versions.
        value = _clean(path.read_text(encoding="utf-8-sig").splitlines()[0])
    except (OSError, IndexError):
        return None
    return Path(value).expanduser().resolve() if value else None


def _infer_app_root(data_root: Path, environ: Mapping[str, str], repo_root: Path) -> Path:
    explicit = _clean(environ.get("H3_APP_INSTALL_ROOT"))
    if explicit:
        return Path(explicit).expanduser().resolve()
    root = Path(data_root).resolve()
    if root.name.lower() == "studio" and root.parent.name.lower() == "userdata":
        return root.parent.parent
    return Path(repo_root).resolve()


@dataclass(frozen=True)
class RuntimePathContract:
    app_install_root: Path
    runtime_root: Path
    comfy_root: Path
    embedded_python: Path
    comfy_main: Path
    models_root: Path
    custom_nodes_root: Path
    input_root: Path
    output_root: Path
    temp_root: Path
    ffmpeg: Optional[Path]
    ffprobe: Optional[Path]
    workflow_root: Path

    def as_dict(self) -> dict[str, str | None]:
        return {
            key: (str(value) if value is not None else None)
            for key, value in self.__dict__.items()
        }

    def validate(self, *, create_io: bool = False) -> None:
        checks = {
            "runtime_root": self.runtime_root,
            "comfy_root": self.comfy_root,
            "embedded_python": self.embedded_python,
            "comfy_main": self.comfy_main,
            "models_root": self.models_root,
            "custom_nodes_root": self.custom_nodes_root,
            "workflow_root": self.workflow_root,
        }
        for name, path in checks.items():
            if name.endswith("_root") and name in {"runtime_root", "comfy_root", "models_root", "custom_nodes_root", "workflow_root"}:
                if not path.is_dir():
                    raise RuntimePathError(f"{name} 不存在: {path}")
            elif not path.is_file():
                raise RuntimePathError(f"{name} 不存在: {path}")
        if create_io:
            for path in (self.input_root, self.output_root, self.temp_root):
                path.mkdir(parents=True, exist_ok=True)
        else:
            for name, path in (("input_root", self.input_root), ("output_root", self.output_root)):
                if not path.is_dir():
                    raise RuntimePathError(f"{name} 不存在: {path}")

    def validate_for_job(self) -> None:
        self.validate(create_io=True)


def resolve_runtime_paths(data_root: Path, *, repo_root: Optional[Path] = None,
                          environ: Optional[Mapping[str, str]] = None) -> RuntimePathContract:
    """Resolve the active installed Runtime/Models pair once.

    Explicit process configuration wins, followed by the installed
    ``native_env.path`` / ``models_env.path`` files.  There is deliberately no
    CWD or nearby-folder fallback.
    """
    env = environ or os.environ
    repo = Path(repo_root or Path(__file__).resolve().parents[2]).resolve()
    app_root = _infer_app_root(Path(data_root), env, repo)
    runtime = _clean(env.get("H3_NATIVE_ROOT"))
    models = _clean(env.get("H3_MODELS_ROOT"))
    # The installed path files are the durable product contract.  A launcher
    # can inherit stale package-relative H3_* variables from an older process;
    # allowing those variables to override native_env.path would split the
    # Studio input/output tree from the Runtime that actually serves ComfyUI.
    configured_runtime = _configured_file(app_root, "native_env.path")
    configured_models = _configured_file(app_root, "models_env.path")
    runtime_root = (configured_runtime if configured_runtime and configured_runtime.is_dir()
                    else (Path(runtime).expanduser().resolve() if runtime else None))
    models_root = (configured_models if configured_models and configured_models.is_dir()
                   else (Path(models).expanduser().resolve() if models else None))
    if runtime_root is None:
        raise RuntimePathError("未配置 Native Runtime，请前往环境修复。")
    if models_root is None:
        # Final production layout keeps the shared Models root beside the
        # managed Runtime.  Explicit models_env.path / H3_MODELS_ROOT still
        # wins, so existing installations remain adoptable during migration.
        models_root = app_root / "Models"
    comfy_root = runtime_root / "ComfyUI"
    explicit_input = _clean(env.get("H3_COMFY_INPUT"))
    explicit_output = _clean(env.get("H3_COMFY_OUTPUT"))
    explicit_temp = _clean(env.get("H3_COMFY_TEMP"))
    # When the selected Runtime is configured by native_env.path, derive its
    # I/O folders from that Runtime instead of trusting possibly stale
    # package-relative H3_COMFY_* variables.
    input_root = comfy_root / "input" if configured_runtime and runtime_root == configured_runtime \
        else (Path(explicit_input).expanduser().resolve() if explicit_input else comfy_root / "input")
    output_root = comfy_root / "output" if configured_runtime and runtime_root == configured_runtime \
        else (Path(explicit_output).expanduser().resolve() if explicit_output else comfy_root / "output")
    temp_root = Path(explicit_temp).expanduser().resolve() if explicit_temp else app_root / "userdata" / "temp"

    def executable(name: str, *relative: str) -> Optional[Path]:
        value = _clean(env.get(name))
        if value:
            candidate = Path(value).expanduser().resolve()
            return candidate
        for base in (runtime_root, app_root):
            for rel in relative:
                candidate = base / rel
                if candidate.is_file():
                    return candidate.resolve()
        found = shutil.which(name.lower().replace("_", ""))
        return Path(found).resolve() if found else None

    return RuntimePathContract(
        app_install_root=app_root,
        runtime_root=runtime_root,
        comfy_root=comfy_root,
        embedded_python=runtime_root / "python_embeded" / "python.exe",
        comfy_main=comfy_root / "main.py",
        models_root=models_root,
        custom_nodes_root=comfy_root / "custom_nodes",
        input_root=input_root,
        output_root=output_root,
        temp_root=temp_root,
        ffmpeg=executable("H3_FFMPEG", "ffmpeg.exe", "bin/ffmpeg.exe"),
        ffprobe=executable("H3_FFPROBE", "ffprobe.exe", "bin/ffprobe.exe"),
        workflow_root=app_root / "workflows",
    )


__all__ = ["RuntimePathContract", "RuntimePathError", "resolve_runtime_paths"]
