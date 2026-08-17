"""Environment Center service (PATCH2.8-I1).

Builds the environment report (system / runtime / models / skill / workflows /
paths / gates), persists user path configuration, and maps the overall status:
READY / WARNING / SETUP_REQUIRED / BLOCK. Reuses the frozen EnvChecker and the
Official Skill pin. No GPU inference.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from ._paths import REPO_ROOT
from .setup_state import SetupState

# launcher is a sibling (repo root) or parent-sibling (distribution/studio).
_LAUNCHER_CANDIDATES = [
    REPO_ROOT / "launcher",
    REPO_ROOT.parent / "launcher",
]
_LAUNCHER_DIR = next((p for p in _LAUNCHER_CANDIDATES if p.is_dir()), None)
if _LAUNCHER_DIR is not None and str(_LAUNCHER_DIR) not in sys.path:
    sys.path.insert(0, str(_LAUNCHER_DIR))

if _LAUNCHER_DIR is not None:
    from env_check import EnvChecker, EnvPaths  # noqa: E402


def _gb(size_bytes: Optional[int]) -> str:
    if not size_bytes:
        return "?"
    return f"~{size_bytes / (1024 ** 3):.1f} GB"


def _free_commit_gb() -> float:
    import ctypes

    class _M(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    st = _M()
    st.dwLength = ctypes.sizeof(_M)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
    return round(st.ullAvailPageFile / (1024 ** 3), 1)


class EnvironmentService:
    MODEL_SUBDIRS = {
        "dit": "diffusion_models",
        "text_encoder": "text_encoders",
        "video_vae": "vae",
        "audio_vae": "vae",
    }

    def __init__(self, store, env_overrides: Optional[Dict[str, Any]] = None) -> None:
        self.store = store
        self.state = SetupState(store)
        self.overrides = env_overrides or {}

    # ------------------------------------------------------------------ #
    def _paths(self) -> EnvPaths:
        return EnvPaths()  # reads H3_* env vars set by launcher/config

    def _light_env_report(self) -> Dict[str, Any]:
        if _LAUNCHER_DIR is None:
            return {"checks": {}, "overall": "BLOCK"}
        checker = EnvChecker(paths=self._paths())
        return checker.check_all(light=True)

    # ------------------------------------------------------------------ #
    def environment(self) -> Dict[str, Any]:
        state = self.state.load()
        native_root = state.get("native_root") or os.environ.get("H3_NATIVE_ROOT", "")
        models_root = state.get("models_root") or os.environ.get("H3_MODELS_ROOT", "")

        system = self._system_status()
        runtime = self._runtime_status(native_root)
        models = self._models_status(models_root)
        skill = self._skill_status()
        workflows = self._workflow_status()
        paths = {
            "native_root": native_root or "",
            "models_root": models_root or "",
            "configured": bool(native_root),
        }

        gates = {
            "native_root_configured": bool(native_root),
            "comfyui_present": runtime["present"],
            "pread_present": runtime["pread"],
            "gpu_ready": system["gpu_ready"],
            "models_4of4": all(m["status"] == "READY" for m in models["items"]),
            "skill_pinned_ready": skill["generation_allowed"],
            "workflows_5of5": workflows["ready"] == 5,
            "free_commit_ok": system["free_commit"] >= 30,
            "contract_valid": self._contract_valid(),
        }

        overall = self._overall(system, runtime, models, skill, gates)
        setup_completed = bool(state.get("setup_completed")) and all(gates.values())

        return {
            "overall": overall,
            "setup_completed": setup_completed,
            "system": system,
            "runtime": runtime,
            "models": models,
            "skill": skill,
            "workflows": workflows,
            "paths": paths,
            "gates": gates,
        }

    # ------------------------------------------------------------------ #
    def _system_status(self) -> Dict[str, Any]:
        import platform
        mem = self.overrides.get("memory_gb")
        disk = self.overrides.get("disk_free_gb")
        gpu = self.overrides.get("torch_available")
        if gpu is None and _LAUNCHER_DIR is not None:
            gpu = EnvChecker(paths=self._paths(),
                             torch_available=None).check_gpu()["status"] == "PASS"
        if mem is None:
            mem = _free_commit_gb()
        if disk is None:
            try:
                disk = round(
                    __import__("shutil").disk_usage(self._paths().models_root).free
                    / (1024 ** 3), 1)
            except Exception:
                disk = 0.0
        return {
            "os": platform.system(),
            "gpu_name": self.overrides.get("gpu_name", "NVIDIA GPU"),
            "cuda": bool(gpu),
            "gpu_ready": bool(gpu),
            "memory_gb": self.overrides.get("ram_gb"),
            "free_commit": float(mem or 0.0),
            "disk_free_gb": float(disk or 0.0),
        }

    def _runtime_status(self, native_root: str) -> Dict[str, Any]:
        root = Path(native_root) if native_root else None
        main = (root / "ComfyUI" / "main.py") if root else None
        shim = (root / "ComfyUI" / "custom_nodes" / "windows_safe_load") if root else None
        present = bool(main and main.is_file())
        pread = bool(shim and shim.is_dir()) and \
            os.environ.get("H3_WINDOWS_SAFE_LOAD", "").lower() == "pread"
        return {
            "path": str(root) if root else "",
            "present": present,
            "version": self.overrides.get("comfyui_version", "0.33.1") if present else None,
            "frontend": self.overrides.get("frontend_version", "1.48.7") if present else None,
            "pread": pread,
            "port": 8189,
        }

    def _models_status(self, models_root: str) -> Dict[str, Any]:
        baseline = json.loads(
            (REPO_ROOT / "configs" / "native_production_baseline.json")
            .read_text(encoding="utf-8"))
        items = []
        for key, sub in self.MODEL_SUBDIRS.items():
            meta = baseline.get("models", {}).get(key, {})
            filename = meta.get("filename", "")
            path = (Path(models_root) / sub / filename) if models_root else None
            exists = bool(path and path.is_file())
            items.append({
                "key": key,
                "name": meta.get("name") or {
                    "dit": "MiniMax H3 DiT",
                    "text_encoder": "Text Encoder",
                    "video_vae": "Video VAE",
                    "audio_vae": "Audio VAE",
                }[key],
                "filename": filename,
                "size": _gb(meta.get("size_bytes")),
                "path": str(path) if path else "",
                "status": "READY" if exists else "MISSING",
            })
        return {"count": len(items), "ready": sum(1 for m in items if m["status"] == "READY"),
                "items": items}

    def _skill_status(self) -> Dict[str, Any]:
        from runtime.prompt_bridge.skill_version import check_skill_version
        gate = check_skill_version()
        if gate["status"] != "GENERATION_ALLOWED":
            status = "REVISION_MISMATCH"
        elif "OFFICIAL_SKILL_UPDATE_AVAILABLE" in gate["flags"]:
            status = "UPDATE_AVAILABLE"
        else:
            status = "READY"
        return {
            "pinned_revision": gate.get("pinned_revision"),
            "installed_revision": gate.get("installed_skill_revision"),
            "latest_upstream": gate.get("latest_upstream_skill_revision"),
            "status": status,
            "flags": gate.get("flags", []),
            "generation_allowed": gate["status"] == "GENERATION_ALLOWED",
        }

    def _workflow_status(self) -> Dict[str, Any]:
        import yaml
        mapping = yaml.safe_load(
            (REPO_ROOT / "runtime" / "contracts" / "workflow_mapping.yaml")
            .read_text(encoding="utf-8"))
        registry = mapping["workflow_registry"]
        items = []
        for wf, entry in registry.items():
            asset = REPO_ROOT / entry["native_asset"]
            items.append({
                "workflow": wf,
                "display_name": entry["display_name"],
                "status": "READY" if asset.is_file() else "INVALID",
            })
        ready = sum(1 for i in items if i["status"] == "READY")
        return {"count": len(items), "ready": ready, "items": items}

    def _contract_valid(self) -> bool:
        for name in ("video_generation_request.yaml", "workflow_mapping.yaml",
                     "native_runtime_contract.yaml"):
            if not (REPO_ROOT / "runtime" / "contracts" / name).is_file():
                return False
        return True

    def _overall(self, system, runtime, models, skill, gates) -> str:
        if not system["gpu_ready"] or system["free_commit"] < 30:
            return "BLOCK"
        if not (gates["native_root_configured"] and gates["comfyui_present"]
                and gates["models_4of4"] and gates["pread_present"]):
            return "SETUP_REQUIRED"
        if not skill["generation_allowed"] or gates["workflows_5of5"] is False \
                or gates["contract_valid"] is False:
            return "SETUP_REQUIRED"
        if skill["status"] == "UPDATE_AVAILABLE" or \
                runtime["version"] in (None, "UNVERIFIED") or \
                runtime["frontend"] in (None, "UNVERIFIED"):
            return "WARNING"
        return "READY"

    # ------------------------------------------------------------------ #
    def configure(self, native_root: str = "", models_root: str = "") -> Dict[str, Any]:
        native = Path(native_root or "").resolve() if native_root else None
        models = Path(models_root or "").resolve() if models_root else None
        if native is not None and not native.is_dir():
            raise ValueError(f"native_root is not a directory: {native}")
        if models is not None and not models.is_dir():
            raise ValueError(f"models_root is not a directory: {models}")
        state = {
            "native_root": str(native) if native else "",
            "models_root": str(models) if models else "",
            "environment_status": "SETUP_REQUIRED",
        }
        self.state.save(state)
        self._write_native_env_path(str(native) if native else "")
        report = self.environment()
        if report["overall"] == "READY":
            self.state.save({"setup_completed": True,
                             "environment_status": "READY",
                             "skill_status": report["skill"]["status"]})
        return self.environment()

    def recheck(self) -> Dict[str, Any]:
        return self.environment()

    def _write_native_env_path(self, native_root: str) -> None:
        launcher_root = _LAUNCHER_DIR
        if launcher_root is None:
            return
        env_path = launcher_root.parent / "native_env.path"
        env_path.write_text(native_root + "\n", encoding="utf-8")

    def open_comfyui(self) -> Dict[str, Any]:
        launcher_root = _LAUNCHER_DIR
        bat = launcher_root.parent / "Open_Native_ComfyUI.bat" if launcher_root else None
        if bat is None or not bat.is_file():
            raise ValueError("Open_Native_ComfyUI.bat not found")
        return {"advanced_entry": str(bat), "note": "Advanced / Developer only"}
