"""Current-user Windows integration, kept separate from product logic."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


APP_NAME = "Architect Video Studio"
APP_KEY = r"Software\Microsoft\Windows\CurrentVersion\App Paths\ArchitectVideoStudio.exe"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\ArchitectVideoStudio"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def registration_plan(install_root: Path, version: str = "0.8.0-rc1") -> dict[str, Any]:
    """Return a side-effect-free plan used by the installer and tests."""
    exe = Path(install_root) / "launcher" / "ArchitectVideoStudioDesktop.exe"
    return {
        "app_name": APP_NAME,
        "executable": str(exe),
        "start_menu_shortcut": str(Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs/Architect Video Studio.lnk"),
        "app_paths_key": APP_KEY,
        "uninstall_key": UNINSTALL_KEY,
        "version": version,
        "startup_default": False,
    }


def set_startup_enabled(enabled: bool, executable: Path) -> bool:
    """Set only this application's HKCU startup value on Windows."""
    if os.name != "nt":
        return False
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, f'"{executable}"')
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass
    return True

