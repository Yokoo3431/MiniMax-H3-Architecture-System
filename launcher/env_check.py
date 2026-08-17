"""Environment Check for the production launcher (PATCH2.8-B).

Checks: Python, GPU/CUDA, model files (SHA-256 vs frozen baseline), ComfyUI
version, Frontend version, PREAD shim, disk space, Free Commit.
Output: Launcher/env_report.json. NO auto-fix.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional


@dataclass
class EnvPaths:
    native_root: Path = field(default_factory=lambda: Path(
        os.environ.get("H3_NATIVE_ROOT", "<NATIVE_ROOT>")))
    repo_root: Path = field(default_factory=lambda: Path(__file__).resolve().parent.parent)
    models_root: Path = field(default_factory=lambda: Path(
        os.environ.get("H3_MODELS_ROOT", "<MODELS_ROOT>")))
    baseline_path: Path = field(default_factory=lambda: Path(
        os.environ.get("H3_BASELINE",
                       str(Path(__file__).resolve().parent.parent / "configs"
                           / "native_production_baseline.json"))))
    env_report_path: Path = field(default_factory=lambda: Path(
        os.environ.get("H3_ENV_REPORT",
                       str(Path(__file__).resolve().parent / "env_report.json"))))

    @property
    def python(self) -> Path:
        return self.native_root / "python_embeded" / "python.exe"

    @property
    def comfy_main(self) -> Path:
        return self.native_root / "ComfyUI" / "main.py"

    @property
    def shim_dir(self) -> Path:
        return self.native_root / "ComfyUI" / "custom_nodes" / "windows_safe_load"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().upper()


class _MEMORYSTATUSEX(ctypes.Structure):
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


def free_commit_gb() -> float:
    st = _MEMORYSTATUSEX()
    st.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
    return round(st.ullAvailPageFile / (1024 ** 3), 1)


class EnvChecker:
    """Environment validation with injectable overrides (tests / dry runs)."""

    MODEL_SUBDIRS = {
        "dit": "diffusion_models",
        "text_encoder": "text_encoders",
        "video_vae": "vae",
        "audio_vae": "vae",
    }

    def __init__(self, paths: Optional[EnvPaths] = None,
                 torch_available: Optional[bool] = None,
                 hash_fn: Callable[[Path], str] = sha256_file,
                 memory_gb: Optional[float] = None,
                 disk_free_gb: Optional[float] = None,
                 python_version: Optional[str] = None,
                 comfyui_version: Optional[str] = None,
                 frontend_version: Optional[str] = None) -> None:
        self.paths = paths or EnvPaths()
        self.torch_available = torch_available
        self.hash_fn = hash_fn
        self.memory_gb = memory_gb
        self.disk_free_gb = disk_free_gb
        self.python_version = python_version
        self.comfyui_version = comfyui_version
        self.frontend_version = frontend_version

    # ------------------------------------------------------------------ #
    def check_python(self) -> dict:
        py = self.paths.python
        if not py.is_file():
            return {"status": "BLOCK", "detail": f"python not found: {py}"}
        version = self.python_version
        if version is None:
            try:
                res = subprocess.run(
                    [str(py), "--version"], capture_output=True, text=True, timeout=20)
                version = (res.stdout or res.stderr).strip()
            except Exception as exc:
                return {"status": "BLOCK", "detail": f"python version check failed: {exc}"}
        ok = "3.13" in version or version.startswith("Python 3.13")
        return {"status": "PASS" if ok else "BLOCK",
                "detail": version, "expected": "Python 3.13+"}

    def check_gpu(self) -> dict:
        avail = self.torch_available
        if avail is None:
            try:
                res = subprocess.run(
                    [str(self.paths.python), "-c",
                     "import torch; print(torch.cuda.is_available())"],
                    capture_output=True, text=True, timeout=60)
                avail = res.stdout.strip().lower() == "true"
            except Exception as exc:
                return {"status": "BLOCK", "detail": f"torch cuda check failed: {exc}"}
        return {"status": "PASS" if avail else "BLOCK",
                "detail": f"cuda_available={avail}", "expected": True}

    def check_models(self) -> dict:
        baseline = json.loads(self.paths.baseline_path.read_text(encoding="utf-8"))
        models = baseline.get("models", {})
        results = []
        all_pass = True
        for key, sub in self.MODEL_SUBDIRS.items():
            meta = models.get(key, {})
            filename = meta.get("filename")
            expected_sha = meta.get("sha256")
            path = self.paths.models_root / sub / (filename or "")
            if not path.is_file():
                results.append({"key": key, "status": "BLOCK",
                                "detail": f"missing {path}"})
                all_pass = False
                continue
            actual = self.hash_fn(path)
            if expected_sha and actual != expected_sha:
                results.append({"key": key, "status": "BLOCK",
                                "detail": f"sha256 mismatch {path.name}"})
                all_pass = False
            else:
                results.append({"key": key, "status": "PASS",
                                "detail": filename, "sha256": actual})
        return {"status": "PASS" if all_pass else "BLOCK",
                "models": results}

    def check_comfyui(self) -> dict:
        main = self.paths.comfy_main
        if not main.is_file():
            return {"status": "BLOCK", "detail": f"ComfyUI main.py missing: {main}"}
        version = self.comfyui_version
        if version is None:
            version = "UNVERIFIED"
        ok = version == "0.33.1"
        return {"status": "PASS" if ok else "WARNING",
                "detail": version, "expected": "0.33.1",
                "note": "BLOCK only on definite mismatch; UNVERIFIED = WARNING"}

    def check_frontend(self) -> dict:
        version = self.frontend_version
        if version is None:
            version = "UNVERIFIED"
        ok = version == "1.48.7"
        return {"status": "PASS" if ok else "WARNING",
                "detail": version, "expected": "1.48.7"}

    def check_pread(self) -> dict:
        env_ok = os.environ.get("H3_WINDOWS_SAFE_LOAD", "").lower() == "pread"
        shim_ok = self.paths.shim_dir.is_dir()
        if env_ok and shim_ok:
            return {"status": "PASS", "detail": "H3_WINDOWS_SAFE_LOAD=pread + shim present"}
        missing = []
        if not env_ok:
            missing.append("H3_WINDOWS_SAFE_LOAD=pread env var")
        if not shim_ok:
            missing.append("windows_safe_load shim dir")
        return {"status": "BLOCK", "detail": "missing: " + ", ".join(missing)}

    def check_memory(self) -> dict:
        gb = self.memory_gb if self.memory_gb is not None else free_commit_gb()
        if gb >= 50:
            status = "PASS"
        elif gb >= 30:
            status = "WARNING"
        else:
            status = "BLOCK"
        return {"status": status, "free_commit_gb": round(float(gb), 1),
                "rule": ">=50 PASS, 30-50 WARNING, <30 BLOCK"}

    def check_disk(self) -> dict:
        gb = self.disk_free_gb
        if gb is None:
            try:
                usage = shutil.disk_usage(self.paths.models_root)
                gb = round(usage.free / (1024 ** 3), 1)
            except Exception as exc:
                return {"status": "WARNING", "detail": f"disk check failed: {exc}"}
        if gb < 10:
            status = "BLOCK"
        elif gb < 50:
            status = "WARNING"
        else:
            status = "PASS"
        return {"status": status, "free_gb": round(float(gb), 1),
                "rule": ">=50 PASS, 10-50 WARNING, <10 BLOCK"}

    # ------------------------------------------------------------------ #
    def check_all(self) -> dict:
        checks = {
            "python": self.check_python(),
            "gpu": self.check_gpu(),
            "models": self.check_models(),
            "comfyui": self.check_comfyui(),
            "frontend": self.check_frontend(),
            "pread": self.check_pread(),
            "memory": self.check_memory(),
            "disk": self.check_disk(),
        }
        if any(c.get("status") == "BLOCK" for c in checks.values()):
            overall = "BLOCK"
        elif any(c.get("status") == "WARNING" for c in checks.values()):
            overall = "WARNING"
        else:
            overall = "PASS"
        report = {
            "overall": overall,
            "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "checks": checks,
            "no_auto_fix": True,
        }
        self.paths.env_report_path.parent.mkdir(parents=True, exist_ok=True)
        self.paths.env_report_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        return report


if __name__ == "__main__":
    print(json.dumps(EnvChecker().check_all(), indent=2, ensure_ascii=False))
