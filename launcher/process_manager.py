"""Process Manager for the production launcher (PATCH2.8-B).

Manages Native ComfyUI (8189) and Architect Video Studio (8788).
Lifecycle: STARTING -> RUNNING / FAILED -> STOPPED. No auto restart.
"""

from __future__ import annotations

import os
import socket
import subprocess
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional


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
                 studio_data: Optional[Path] = None) -> None:
        self.native_root = Path(native_root)
        self.repo_root = Path(repo_root)
        self.python = Path(python) if python else self.native_root / "python_embeded" / "python.exe"
        self.logs_dir = Path(logs_dir) if logs_dir else self.repo_root / "Logs"
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.dry_run = dry_run
        self._popen = popen or subprocess.Popen
        self.studio_app = Path(studio_app) if studio_app else self.repo_root / "apps" / "architect_video_studio"
        self.studio_workdir = Path(studio_workdir) if studio_workdir else self.repo_root
        self.studio_data = Path(studio_data) if studio_data else self.studio_app / "data"
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
            self._make_service(
                "comfyui",
                [str(self.python), "-s", "ComfyUI\\main.py",
                 "--windows-standalone-build", "--port", str(self.COMFYUI_PORT),
                 "--disable-dynamic-vram", "--disable-pinned-memory"],
                cwd=self.native_root,
                health_url=f"http://127.0.0.1:{self.COMFYUI_PORT}/system_stats",
                log_name="comfyui.log",
                env_extra={"H3_WINDOWS_SAFE_LOAD": "pread"},
            )
        return self.services["comfyui"]

    def studio_service(self) -> Service:
        if "studio" not in self.services:
            cmd = [str(self.python),
                   str(self.studio_app / "run_prototype.py"),
                   "--runtime", "real", "--port", str(self.STUDIO_PORT),
                   "--data", str(self.studio_data)]
            self._make_service(
                "studio",
                cmd,
                cwd=self.studio_workdir,
                health_url=f"http://127.0.0.1:{self.STUDIO_PORT}/api/projects",
                log_name="studio.log",
            )
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
        env = os.environ.copy()
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

    def start_studio(self, health_timeout: float = 60.0) -> Service:
        return self.start(self.studio_service(), health_timeout)

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
        return {name: svc.state for name, svc in self.services.items()}

    def _port_of(self, service: Service) -> str:
        if service.port is not None:
            return str(service.port)
        if service.name == "comfyui":
            return str(self.COMFYUI_PORT)
        return str(self.STUDIO_PORT)
