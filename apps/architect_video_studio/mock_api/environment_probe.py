"""Bounded, layered local hardware/runtime probe for Environment Center.

This module does not load models or run inference.  It deliberately keeps GPU
hardware, driver, embedded Python, Torch import, CUDA availability, and the
product hardware policy as separate facts so one failed sub-probe cannot erase
the other evidence.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


NVIDIA_SMI_TIMEOUT_SECONDS = 5
TORCH_PROBE_TIMEOUT_SECONDS = 15
WINDOWS_GPU_TIMEOUT_SECONDS = 5
MAX_DIAGNOSTIC_TEXT = 4000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _trim(value: Any) -> str:
    return str(value or "")[-MAX_DIAGNOSTIC_TEXT:]


def resolve_runtime_python(runtime_root: str | Path | None) -> Optional[Path]:
    """Resolve the embedded Python from the selected Runtime only."""
    if not runtime_root:
        return None
    root = Path(runtime_root)
    candidates = (
        root / "python_embeded" / "python.exe",
        root / "runtime" / "bootstrap" / "python.exe",
        root / "ComfyUI" / "python_embeded" / "python.exe",
        root / "python.exe",
    )
    return next((candidate for candidate in candidates if candidate.is_file()), None)


def _policy(vram_bytes: Optional[int]) -> Dict[str, Any]:
    if not vram_bytes:
        return {"status": "UNKNOWN", "label": "UNKNOWN", "reason": "VRAM was not detected."}
    gib = vram_bytes / (1024 ** 3)
    if gib >= 24:
        return {"status": "SUPPORTED", "label": "SUPPORTED", "reason": "24 GB-class H3 target."}
    if gib >= 11.5:
        return {
            "status": "EXPERIMENTAL",
            "label": "EXPERIMENTAL",
            "reason": "12 GB-class hardware; below the validated 24 GB-class H3 target.",
        }
    return {"status": "UNSUPPORTED", "label": "UNSUPPORTED", "reason": "Below the current H3 hardware floor."}


class EnvironmentProbe:
    """Run all lightweight probes and return one serializable contract."""

    def __init__(self, runtime_root: str | Path | None,
                 overrides: Optional[Dict[str, Any]] = None) -> None:
        self.runtime_root = str(runtime_root or "")
        self.overrides = overrides or {}

    @staticmethod
    def _command(command: list[str], timeout: int) -> Dict[str, Any]:
        try:
            result = subprocess.run(
                command, capture_output=True, text=True, timeout=timeout, check=False,
            )
            return {
                "status": "PASS" if result.returncode == 0 else "ISSUE",
                "exit_code": result.returncode,
                "stdout": _trim(result.stdout),
                "stderr": _trim(result.stderr),
                "exception": "",
            }
        except subprocess.TimeoutExpired as exc:
            return {
                "status": "TIMEOUT", "exit_code": None,
                "stdout": _trim(getattr(exc, "stdout", "")),
                "stderr": _trim(getattr(exc, "stderr", "")),
                "exception": f"timeout after {timeout}s",
            }
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            return {
                "status": "UNAVAILABLE", "exit_code": None,
                "stdout": "", "stderr": "", "exception": f"{type(exc).__name__}: {exc}",
            }

    def _nvidia_smi(self) -> tuple[Dict[str, Any], str, str, Optional[int]]:
        command = [
            "nvidia-smi", "--query-gpu=name,driver_version,memory.total",
            "--format=csv,noheader,nounits",
        ]
        detail = self._command(command, NVIDIA_SMI_TIMEOUT_SECONDS)
        detail["command"] = command
        name = driver = ""
        vram = None
        if detail["status"] == "PASS":
            line = next((line.strip() for line in detail["stdout"].splitlines() if line.strip()), "")
            parts = [part.strip() for part in line.split(",")]
            if parts:
                name = parts[0]
                driver = parts[1] if len(parts) > 1 else ""
                try:
                    # nvidia-smi reports memory.total in MiB with nounits.
                    vram = int(float(parts[2]) * 1024 * 1024) if len(parts) > 2 else None
                except (TypeError, ValueError):
                    detail["status"] = "ISSUE"
                    detail["exception"] = "invalid memory.total from nvidia-smi"
        return detail, name, driver, vram

    def _windows_gpu_fallback(self) -> tuple[Dict[str, Any], str, str, Optional[int]]:
        powershell = Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        command = [
            str(powershell), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command",
            "Get-CimInstance Win32_VideoController | Where-Object { $_.Name -match 'NVIDIA' } | Select-Object -First 1 Name,AdapterRAM,DriverVersion | ConvertTo-Json -Compress",
        ]
        detail = self._command(command, WINDOWS_GPU_TIMEOUT_SECONDS)
        detail["command"] = command
        name = driver = ""
        vram = None
        if detail["status"] == "PASS":
            try:
                data = json.loads(detail["stdout"].splitlines()[-1])
                name = str(data.get("Name") or "")
                driver = str(data.get("DriverVersion") or "")
                if data.get("AdapterRAM"):
                    vram = int(data["AdapterRAM"])
            except (IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
                detail["status"] = "ISSUE"
                detail["exception"] = f"invalid Windows GPU probe output: {exc}"
        return detail, name, driver, vram

    def _torch(self, python: Optional[Path]) -> tuple[Dict[str, Any], Dict[str, Any]]:
        runtime: Dict[str, Any] = {
            "runtime_python_found": bool(python),
            "runtime_python_path": str(python) if python else "",
            "torch_import_ok": False,
            "torch_version": "",
            "torch_cuda_available": False,
            "torch_cuda_version": "",
            "torch_gpu_name": "",
            "torch_gpu_total_memory": None,
        }
        if not python:
            return {
                "status": "UNAVAILABLE", "exit_code": None, "stdout": "", "stderr": "",
                "exception": "selected Runtime embedded Python was not found",
                "command": [],
            }, runtime

        code = (
            "import json, torch; "
            "ok=bool(torch.cuda.is_available()); "
            "p=torch.cuda.get_device_properties(0) if ok else None; "
            "print(json.dumps({'torch':str(torch.__version__),"
            "'cuda':str(torch.version.cuda or ''),'ok':ok,"
            "'name':torch.cuda.get_device_name(0) if ok else '',"
            "'vram':int(p.total_memory) if p else None}, ensure_ascii=False))"
        )
        command = [str(python), "-c", code]
        detail = self._command(command, TORCH_PROBE_TIMEOUT_SECONDS)
        detail["command"] = command
        if detail["status"] == "PASS":
            try:
                data = json.loads(detail["stdout"].splitlines()[-1])
                runtime.update({
                    "torch_import_ok": True,
                    "torch_version": str(data.get("torch") or ""),
                    "torch_cuda_available": bool(data.get("ok")),
                    "torch_cuda_version": str(data.get("cuda") or ""),
                    "torch_gpu_name": str(data.get("name") or ""),
                    "torch_gpu_total_memory": int(data["vram"]) if data.get("vram") else None,
                })
            except (IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
                detail["status"] = "ISSUE"
                detail["exception"] = f"invalid Torch probe output: {exc}"
        return detail, runtime

    def run(self) -> Dict[str, Any]:
        started = _now()
        diagnostics: Dict[str, Any] = {}
        errors: list[str] = []

        override_cuda = self.overrides.get("torch_available")
        override_name = str(self.overrides.get("gpu_name") or "")
        python = resolve_runtime_python(self.runtime_root)
        smi_detail, smi_name, smi_driver, smi_vram = self._nvidia_smi()
        diagnostics["nvidia_smi"] = smi_detail

        fallback_detail: Dict[str, Any] = {}
        fallback_name = fallback_driver = ""
        fallback_vram = None
        if smi_detail["status"] != "PASS" or not smi_name:
            fallback_detail, fallback_name, fallback_driver, fallback_vram = self._windows_gpu_fallback()
            diagnostics["windows_gpu_fallback"] = fallback_detail

        torch_detail: Dict[str, Any]
        torch_runtime: Dict[str, Any]
        if override_cuda is not None:
            torch_detail = {
                "status": "PASS" if override_cuda else "ISSUE", "exit_code": 0,
                "stdout": "", "stderr": "", "exception": "fixture override",
                "command": [],
            }
            torch_runtime = {
                "runtime_python_found": bool(python),
                "runtime_python_path": str(python) if python else "",
                "torch_import_ok": bool(override_cuda),
                "torch_version": "fixture" if override_cuda else "",
                "torch_cuda_available": bool(override_cuda),
                "torch_cuda_version": "fixture" if override_cuda else "",
                "torch_gpu_name": override_name,
                "torch_gpu_total_memory": None,
            }
        else:
            torch_detail, torch_runtime = self._torch(python)
        diagnostics["torch"] = torch_detail

        gpu_name = override_name or smi_name or fallback_name or torch_runtime["torch_gpu_name"]
        driver_version = smi_driver or fallback_driver
        vram_bytes = smi_vram or fallback_vram or torch_runtime["torch_gpu_total_memory"]
        gpu_detected = bool(gpu_name or vram_bytes)
        # A zero-exit command with empty output is not evidence of a driver.
        # Require an actual driver version or a parsed GPU fallback record.
        driver_detected = bool(driver_version)
        if override_cuda is not None:
            gpu_detected = bool(override_name or gpu_detected or override_cuda)
            driver_detected = bool(override_cuda or driver_detected)

        if not gpu_detected:
            errors.append("GPU hardware was not detected")
        if not driver_detected:
            errors.append("NVIDIA driver was not detected")
        if not torch_runtime["runtime_python_found"]:
            errors.append("selected Runtime embedded Python was not found")
        if not torch_runtime["torch_import_ok"]:
            errors.append(torch_detail.get("exception") or "Torch import probe failed")
        elif not torch_runtime["torch_cuda_available"]:
            errors.append("torch.cuda.is_available() returned false")

        policy = _policy(vram_bytes)
        finished = _now()
        contract = {
            "schema_version": 1,
            "windows": platform.platform(),
            "gpu_detected": gpu_detected,
            "gpu_name": gpu_name,
            "gpu_vram_bytes": vram_bytes,
            "driver_detected": driver_detected,
            "driver_version": driver_version,
            "runtime_python_found": torch_runtime["runtime_python_found"],
            "runtime_python_path": torch_runtime["runtime_python_path"],
            "torch_import_ok": torch_runtime["torch_import_ok"],
            "torch_version": torch_runtime["torch_version"],
            "torch_cuda_available": torch_runtime["torch_cuda_available"],
            "torch_cuda_version": torch_runtime["torch_cuda_version"],
            "torch_gpu_name": torch_runtime["torch_gpu_name"],
            "torch_gpu_total_memory": torch_runtime["torch_gpu_total_memory"],
            "comfy_runtime_present": False,
            "h3_upstream_ready": False,
            "h3_support_layer_ready": False,
            "models_ready": False,
            "prompt_skill_ready": False,
            "workflows_ready": False,
            "hardware_policy": policy,
            "probe_status": "READY" if gpu_detected and driver_detected and torch_runtime["torch_cuda_available"] else "ISSUE",
            "probe_error": "; ".join(dict.fromkeys(errors)),
            "last_probe_started": started,
            "last_probe_finished": finished,
            "diagnostics": diagnostics,
        }
        return contract


__all__ = ["EnvironmentProbe", "resolve_runtime_python"]
