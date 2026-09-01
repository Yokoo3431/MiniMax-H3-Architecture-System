"""System API (PATCH2.8-I1): Environment Center backend.

Read-only environment probe + path configuration. NEVER exposes or modifies
workflow JSON, runtime contracts, prompt pipeline, or system registry.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Dict

from .environment_service import EnvironmentService
from .installer_service import InstallationService
from runtime.windows_integration import set_startup_enabled


class SystemAPI:
    def __init__(self, store, env_overrides=None) -> None:
        self.service = EnvironmentService(store, env_overrides)
        self.installer = InstallationService(store, env_overrides)

    def environment(self) -> Dict[str, Any]:
        return self.service.environment()

    def configure(self, body: Dict[str, Any]) -> Dict[str, Any]:
        return self.service.configure(
            native_root=body.get("native_root", ""),
            models_root=body.get("models_root", ""),
        )

    def recheck(self) -> Dict[str, Any]:
        return self.service.recheck()

    def repair_model_paths(self) -> Dict[str, Any]:
        return self.service.repair_model_paths()

    def open_comfyui(self, job_id: str = "") -> Dict[str, Any]:
        return self.service.open_comfyui(job_id)

    def current_workflow(self, job_id: str = "") -> Dict[str, Any]:
        return self.service.current_workflow(job_id)

    def restart_comfyui(self) -> Dict[str, Any]:
        return self.service.restart_comfyui()

    def runtime_update_status(self) -> Dict[str, Any]:
        return self.service.runtime_update_status()

    def engine_status(self) -> Dict[str, Any]:
        return self.service.engine_status()

    def capabilities(self) -> Dict[str, Any]:
        from runtime.generation_capabilities import capability_matrix
        return {"workflows": capability_matrix()}

    def pick_folder(self) -> Dict[str, Any]:
        """Open an app-owned native Windows folder picker when available."""
        preset = os.environ.get("ARCHITECT_VIDEO_STUDIO_PICK_FOLDER", "").strip()
        if preset:
            return {"path": preset, "cancelled": False, "native": False}
        if os.name != "nt":
            return {"path": "", "cancelled": True, "native": False}
        script = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "$d=New-Object System.Windows.Forms.FolderBrowserDialog; "
            "$d.Description='选择 Architect Video Studio 视频保存位置'; "
            "if($d.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) "
            "{[Console]::Out.Write($d.SelectedPath)}"
        )
        try:
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-STA", "-Command", script],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=120, check=False)
            path = (result.stdout or "").strip()
            if result.returncode != 0:
                raise ValueError("无法打开 Windows 文件夹选择器")
            return {"path": path, "cancelled": not bool(path), "native": True}
        except (OSError, subprocess.TimeoutExpired):
            return {"path": "", "cancelled": True, "native": False}

    def open_path(self, path: str) -> Dict[str, Any]:
        target = Path(str(path or "")).expanduser()
        if not target.exists():
            raise ValueError("文件或文件夹不存在")
        if os.name == "nt":
            os.startfile(str(target))  # type: ignore[attr-defined]
        return {"path": str(target), "opened": True}

    def desktop_settings(self) -> Dict[str, Any]:
        path = self._desktop_settings_path()
        try:
            data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        except (OSError, ValueError):
            data = {}
        return {
            "startup_enabled": bool(data.get("startup_enabled", False)),
            "tray_minimized": bool(data.get("tray_minimized", False)),
        }

    def save_desktop_settings(self, body: Dict[str, Any]) -> Dict[str, Any]:
        startup_enabled = bool(body.get("startup_enabled", False))
        tray_minimized = bool(body.get("tray_minimized", False))
        executable = self._desktop_executable()
        applied = set_startup_enabled(startup_enabled, executable)
        path = self._desktop_settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "startup_enabled": startup_enabled and applied,
            "tray_minimized": tray_minimized,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        return self.desktop_settings() | {"applied": applied, "executable": str(executable)}

    def _desktop_settings_path(self) -> Path:
        return Path(self.service.store.data_root).parent / "system" / "desktop_settings.json"

    def _desktop_executable(self) -> Path:
        configured = os.environ.get("ARCHITECT_VIDEO_STUDIO_EXE")
        if configured:
            return Path(configured)
        install_root = Path(self.service.store.data_root).parent.parent
        return install_root / "launcher" / "ArchitectVideoStudioDesktop.exe"

    def install_plan(self, body: Dict[str, Any] | None = None) -> Dict[str, Any]:
        body = body or {}
        return self.installer.build_install_plan(
            native_root=body.get("native_root") or None,
            models_root=body.get("models_root") or None,
            # Environment Center adopts active assets and checks sizes without
            # hashing multi-GB weights. Dependency metadata is cheap and must
            # reflect the active Runtime instead of the deferred install plan.
            verify_existing=bool(body.get("verify_existing", False)),
            verify_dependencies=bool(body.get("verify_dependencies", True)),
        )

    def install(self, body: Dict[str, Any]) -> Dict[str, Any]:
        return self.installer.start_install(body)

    def install_job(self, job_id: str) -> Dict[str, Any]:
        return self.installer.get_job(job_id)

    def cancel_install(self, job_id: str) -> Dict[str, Any]:
        return self.installer.cancel_job(job_id)

    def repair(self, body: Dict[str, Any]) -> Dict[str, Any]:
        return self.installer.repair(body)
