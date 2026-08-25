"""Process Manager for the production launcher (PATCH2.8-B).

Manages Native ComfyUI (8189) and Architect Video Studio (8788).
Lifecycle: STARTING -> RUNNING / FAILED -> STOPPED. Known stale service
processes are restarted before a new managed instance is launched.
"""

from __future__ import annotations

import os
import json
import socket
import subprocess
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

from runtime.storage_policy import ensure_cache_dirs, process_environment
from runtime.h3_model_root import (
    COMFY_MODEL_PATHS_FILENAME,
    ensure_h3_model_root_bridge,
    h3_process_environment,
    write_comfy_model_paths_config,
)


class PortManager:
    @staticmethod
    def port_in_use(port: int, host: str = "127.0.0.1") -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1.0)
            try:
                s.connect((host, port))
                return True
            except OSError:
                return False

    @staticmethod
    def find_pid(port: int, netstat_output: Optional[str] = None) -> Optional[int]:
        if netstat_output is None:
            out = subprocess.run(["netstat", "-ano"], capture_output=True,
                                 text=True, timeout=20).stdout
        else:
            out = netstat_output
        for line in out.splitlines():
            if f":{port}" in line and "LISTENING" in line:
                try:
                    return int(line.split()[-1])
                except ValueError:
                    return None
        return None

    @staticmethod
    def process_commandline(pid: Optional[int]) -> str:
        """Return a Windows process command line without touching the process.

        Port ownership alone is not sufficient authority to terminate a
        process. The launcher therefore asks Windows for the command line and
        only restarts a process after the caller verifies its service shape.
        Query failures intentionally return an empty string, which is treated
        as an unknown/conflicting process by the caller.
        """
        if not pid or os.name != "nt":
            return ""
        powershell = os.path.join(
            os.environ.get("WINDIR", r"C:\Windows"),
            "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
        if not os.path.isfile(powershell):
            powershell = "powershell.exe"
        command = (
            f"$p=Get-CimInstance Win32_Process -Filter 'ProcessId = {int(pid)}' "
            "-ErrorAction SilentlyContinue; if ($p) { $p.CommandLine }"
        )
        try:
            result = subprocess.run(
                [powershell, "-NoLogo", "-NoProfile", "-NonInteractive",
                 "-ExecutionPolicy", "Bypass", "-Command", command],
                capture_output=True, text=True, timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return result.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return ""

    @staticmethod
    def is_managed_commandline(commandline: str, service_kind: str) -> bool:
        """Recognize only the two service shapes the launcher owns."""
        text = (commandline or "").lower().replace("/", "\\")
        if service_kind == "studio":
            return ("run_architect_video_studio.py" in text or "run_prototype.py" in text) and "--port 8788" in text
        if service_kind == "comfyui":
            return "comfyui" in text and "main.py" in text and "--port 8189" in text
        return False

    @staticmethod
    def terminate_pid(pid: int, timeout: float = 10.0) -> bool:
        """Terminate one already-identified service process tree."""
        if not pid or pid == os.getpid():
            return False
        if os.name != "nt":
            return False
        try:
            result = subprocess.run(
                ["taskkill", "/PID", str(int(pid)), "/T", "/F"],
                capture_output=True, text=True,
                timeout=max(1.0, timeout),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return result.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    @classmethod
    def wait_until_free(cls, port: int, timeout: float = 12.0) -> bool:
        deadline = time.time() + max(0.1, timeout)
        while time.time() < deadline:
            if not cls.port_in_use(port):
                return True
            time.sleep(0.25)
        return not cls.port_in_use(port)

    @classmethod
    def restart_managed_conflict(cls, port: int, service_kind: str,
                                 timeout: float = 12.0) -> dict:
        """Restart a recognizable stale service, or report a safe block.

        The result is deliberately structured so the UI/launcher can explain
        an unknown port owner instead of waiting indefinitely or killing an
        unrelated application.
        """
        if not cls.port_in_use(port):
            return {"status": "free", "pid": None, "commandline": ""}
        pid = cls.find_pid(port)
        commandline = cls.process_commandline(pid)
        if not cls.is_managed_commandline(commandline, service_kind):
            return {"status": "unknown", "pid": pid, "commandline": commandline}
        if not cls.terminate_pid(pid, timeout=min(timeout, 10.0)):
            return {"status": "failed", "pid": pid, "commandline": commandline}
        if not cls.wait_until_free(port, timeout=timeout):
            return {"status": "still_in_use", "pid": pid, "commandline": commandline}
        return {"status": "restarted", "pid": pid, "commandline": commandline}

    @classmethod
    def conflicts(cls, ports) -> Dict[int, dict]:
        result = {}
        for port in ports:
            if cls.port_in_use(port):
                result[port] = {"in_use": True, "pid": cls.find_pid(port)}
            else:
                result[port] = {"in_use": False, "pid": None}
        return result


def _http_ok(url: str, timeout: float = 3.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


@dataclass
class Service:
    name: str
    command: list
    cwd: Path
    health_url: str
    log_path: Path
    env_extra: dict = field(default_factory=dict)
    port: Optional[int] = None
    proc: Optional[subprocess.Popen] = None
    state: str = "STOPPED"
    dry_run: bool = False


class ProcessManager:
    COMFYUI_PORT = 8189
    STUDIO_PORT = 8788

    def __init__(self, native_root: Path, repo_root: Path,
                 python: Optional[Path] = None, logs_dir: Optional[Path] = None,
                 dry_run: bool = False, popen=None,
                 studio_app: Optional[Path] = None,
                 studio_workdir: Optional[Path] = None,
                 studio_data: Optional[Path] = None,
                 bootstrap_python: Optional[Path] = None) -> None:
        self.native_root = Path(native_root)
        self.repo_root = Path(repo_root)
        self.python = Path(python) if python else self.native_root / "python_embeded" / "python.exe"
        self.bootstrap_python = Path(bootstrap_python) if bootstrap_python else self.python
        self.logs_dir = Path(logs_dir) if logs_dir else self.repo_root / "Logs"
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.dry_run = dry_run
        self._popen = popen or subprocess.Popen
        self.studio_app = Path(studio_app) if studio_app else self.repo_root / "apps" / "architect_video_studio"
        self.studio_workdir = Path(studio_workdir) if studio_workdir else self.repo_root
        self.studio_data = Path(studio_data) if studio_data else Path(
            os.environ.get("H3_STUDIO_DATA", str(self.studio_app / "data")))
        self.services: Dict[str, Service] = {}

    # ------------------------------------------------------------------ #
    def _make_service(self, name: str, command: list, cwd: Path,
                      health_url: str, log_name: str,
                      env_extra: Optional[dict] = None) -> Service:
        svc = Service(
            name=name, command=command, cwd=cwd, health_url=health_url,
            log_path=self.logs_dir / log_name, env_extra=env_extra or {},
            dry_run=self.dry_run,
        )
        self.services[name] = svc
        return svc

    def comfyui_service(self) -> Service:
        if "comfyui" not in self.services:
            comfy_env = {"H3_WINDOWS_SAFE_LOAD": "pread"}
            configured_models = os.environ.get("H3_MODELS_ROOT", "").strip()
            command = [str(self.python), "-s", "ComfyUI\\main.py",
                       "--windows-standalone-build", "--port", str(self.COMFYUI_PORT),
                       # The pinned H3 VAE path is not safe with ComfyUI's
                       # asynchronous weight-offload worker on Windows/Blackwell.
                       # Keep both transfer safety switches explicit and local
                       # to the managed ComfyUI child; no global environment
                       # or model/runtime mutation is required.
                       "--disable-dynamic-vram", "--disable-async-offload",
                       "--disable-pinned-memory"]
            if configured_models:
                comfy_env.update(h3_process_environment(configured_models))
                if not self.dry_run and (Path(configured_models) / "MiniMax-H3").is_dir():
                    # The pinned H3 resolver has a Runtime-local fallback in
                    # addition to its private environment contract. Establish
                    # the same selected root there so an already-running or
                    # independently-started ComfyUI cannot silently diverge.
                    ensure_h3_model_root_bridge(self.native_root, configured_models)
                # The ComfyUI child must consume a path map owned by the
                # selected production Runtime.  Writing this beside Studio's
                # development data made a packaged install depend on the
                # repository/userdata tree and leaked that path into argv.
                config_path = write_comfy_model_paths_config(
                    configured_models,
                    self.native_root / "ComfyUI" / COMFY_MODEL_PATHS_FILENAME)
                comfy_env["H3_COMFY_EXTRA_MODEL_PATHS"] = str(config_path)
                command.extend(["--extra-model-paths-config", str(config_path)])
            self._make_service(
                "comfyui",
                command,
                cwd=self.native_root,
                health_url=f"http://127.0.0.1:{self.COMFYUI_PORT}/system_stats",
                log_name="comfyui.log",
                 env_extra=comfy_env,
            )
        return self.services["comfyui"]

    def studio_service(self, runtime: str = "real") -> Service:
        if "studio" not in self.services:
            cmd = [str(self.bootstrap_python),
                   str(self.studio_app / "run_architect_video_studio.py"),
                   "--runtime", runtime, "--port", str(self.STUDIO_PORT),
                   "--data", str(self.studio_data)]
            studio_env = {
                "H3_WINDOWS_SAFE_LOAD": "pread",
                "H3_NATIVE_ROOT": str(self.native_root),
                "H3_COMFY_INPUT": str(self.native_root / "ComfyUI" / "input"),
                "H3_COMFY_OUTPUT": str(self.native_root / "ComfyUI" / "output"),
            }
            configured_models = os.environ.get("H3_MODELS_ROOT", "").strip()
            if configured_models:
                studio_env["H3_MODELS_ROOT"] = configured_models
                studio_env.update(h3_process_environment(configured_models))
            self._make_service(
                "studio",
                cmd,
                cwd=self.studio_workdir,
                health_url=f"http://127.0.0.1:{self.STUDIO_PORT}/api/health",
                log_name="studio.log",
                env_extra=studio_env,
            )
        elif "--runtime" in self.services["studio"].command and runtime not in self.services["studio"].command:
            raise RuntimeError("Studio service already exists with a different runtime mode")
        return self.services["studio"]

    # ------------------------------------------------------------------ #
    def start(self, service: Service, health_timeout: float = 120.0) -> Service:
        if service.state in ("RUNNING", "STARTING"):
            return service
        if not service.dry_run and PortManager.port_in_use(int(self._port_of(service))):
            service.state = "FAILED"
            service.failure = f"port {self._port_of(service)} already in use"
            return service
        service.state = "STARTING"
        if service.dry_run:
            service.proc = None
            service.state = "RUNNING"
            return service
        # Cache/temp routing is intentionally limited to the child process.
        ensure_cache_dirs(self.repo_root)
        env = process_environment(self.repo_root)
        env.update(service.env_extra)
        with open(service.log_path, "a", encoding="utf-8") as log:
            log.write(f"\n===== START {service.name} =====\n")
            log.flush()
            service.proc = self._popen(
                service.command, cwd=str(service.cwd), env=env,
                stdout=log, stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        deadline = time.time() + health_timeout
        while time.time() < deadline:
            if service.proc.poll() is not None:
                service.state = "FAILED"
                service.failure = f"{service.name} exited early (code {service.proc.returncode})"
                return service
            if _http_ok(service.health_url):
                service.state = "RUNNING"
                return service
            time.sleep(2)
        service.state = "FAILED"
        service.failure = f"{service.name} health check timeout after {health_timeout:.0f}s"
        return service

    def start_comfyui(self, health_timeout: float = 120.0) -> Service:
        return self.start(self.comfyui_service(), health_timeout)

    def start_studio(self, health_timeout: float = 60.0,
                     setup_mode: bool = False) -> Service:
        return self.start(self.studio_service("mock" if setup_mode else "real"), health_timeout)

    def stop(self, name: str) -> Service:
        svc = self.services.get(name)
        if svc is None:
            raise KeyError(f"unknown service {name}")
        if svc.proc is not None and svc.proc.poll() is None:
            svc.proc.terminate()
            try:
                svc.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                svc.proc.kill()
        svc.state = "STOPPED"
        return svc

    def status(self) -> Dict[str, str]:
        self.refresh()
        return {name: svc.state for name, svc in self.services.items()}

    def refresh(self) -> Dict[str, str]:
        """Publish unexpected child exits without restarting them implicitly."""
        for service in self.services.values():
            if service.state in ("RUNNING", "STARTING") and service.proc is not None:
                code = service.proc.poll()
                if code is not None:
                    service.state = "FAILED"
                    service.exit_code = code
                    if service.name == "comfyui":
                        service.failure = f"COMFYUI_CRASHED (exit code {code})"
                        marker = self.logs_dir / "comfyui.crash.json"
                        try:
                            marker.write_text(json.dumps({
                                "status": "COMFYUI_CRASHED",
                                "pid": getattr(service.proc, "pid", None),
                                "exit_code": code,
                                "timestamp": time.time(),
                                "log_path": str(service.log_path),
                            }, indent=2), encoding="utf-8")
                        except OSError:
                            pass
                    else:
                        service.failure = f"{service.name} exited (code {code})"
        return {name: svc.state for name, svc in self.services.items()}

    def _port_of(self, service: Service) -> str:
        if service.port is not None:
            return str(service.port)
        if service.name == "comfyui":
            return str(self.COMFYUI_PORT)
        return str(self.STUDIO_PORT)
