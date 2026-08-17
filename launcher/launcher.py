"""Production Launcher (PATCH2.8-B).

Double-click flow:
    launcher -> env check -> start Native ComfyUI -> health -> start Studio
    -> open browser -> READY

Safety: runtime.lock (single instance); shutdown/cleanup/update blocked while a
GPU job is running. No auto restart. No auto-fix.
"""

from __future__ import annotations

import argparse
import sys
import time
import webbrowser
from pathlib import Path

_LAUNCHER_DIR = Path(__file__).resolve().parent
if str(_LAUNCHER_DIR) not in sys.path:
    sys.path.insert(0, str(_LAUNCHER_DIR))

from dist_config import DistributionConfig
from env_check import EnvChecker, EnvPaths
from lock_manager import LockManager
from logger import LauncherLogger
from process_manager import PortManager, ProcessManager

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOCK = Path(__file__).resolve().parent / "runtime.lock"
DEFAULT_LOGS = REPO_ROOT / "Logs"
DEFAULT_DIST_CONFIG = Path(__file__).resolve().parent.parent / "distribution_config.yaml"


def _open_browser(url: str) -> None:
    webbrowser.open(url)


class Launcher:
    def __init__(self, dry_run: bool = False, no_browser: bool = False,
                 logs_dir: Path = DEFAULT_LOGS,
                 lock_path: Path = DEFAULT_LOCK,
                 paths: EnvPaths | None = None,
                 env_checker=None,
                 dist_config_path: Path | None = None) -> None:
        self.dry_run = dry_run
        self.no_browser = no_browser
        self.dist_config = None
        cfg_path = Path(dist_config_path or DEFAULT_DIST_CONFIG)
        if cfg_path.is_file():
            self.dist_config = DistributionConfig(cfg_path)
            self.dist_config.apply_environment()
            logs_dir = self.dist_config.logs
            (logs_dir).mkdir(parents=True, exist_ok=True)
        self.logger = LauncherLogger(logs_dir, "launcher")
        self.lock = LockManager(lock_path)
        self.paths = paths or EnvPaths()
        self._env_checker = env_checker
        pm_kwargs = {}
        if self.dist_config is not None:
            pm_kwargs = {
                "studio_app": self.dist_config.studio_app,
                "studio_workdir": self.dist_config.studio_workdir,
                "studio_data": self.dist_config.userdata / "studio",
            }
        self.pm = ProcessManager(
            native_root=self.paths.native_root,
            repo_root=self.paths.repo_root,
            python=self.paths.python,
            logs_dir=logs_dir,
            dry_run=dry_run,
            **pm_kwargs,
        )

    # ------------------------------------------------------------------ #
    @staticmethod
    def _production_ready(report: dict) -> bool:
        checks = report.get("checks", {})
        gpu = checks.get("gpu", {}).get("status")
        memory = checks.get("memory", {}).get("status")
        comfyui = checks.get("comfyui", {}).get("status")
        models = checks.get("models", {}).get("status")
        pread = checks.get("pread", {}).get("status")
        return bool(gpu == "PASS" and memory != "BLOCK" and comfyui != "BLOCK"
                    and models != "BLOCK" and pread == "PASS")

    def start(self, skip_env: bool = False) -> int:
        self.logger.info("launcher starting")
        try:
            self.lock.acquire()
        except RuntimeError as exc:
            self.logger.error(str(exc))
            print(f"[BLOCK] {exc}")
            return 2

        try:
            if not skip_env:
                checker = self._env_checker or EnvChecker(paths=self.paths)
                report = checker.check_all(light=True)
                print("Environment check:", report["overall"])
                if report["checks"].get("python", {}).get("status") == "BLOCK":
                    self.logger.error("bootstrap python BLOCK")
                    self.lock.release()
                    return 1
            else:
                self.logger.warning("env check skipped (--skip-env)")

            production_ready = self._production_ready(report) if not skip_env else True
            if not production_ready:
                # First-run / incomplete environment -> SETUP_REQUIRED.
                # Start Studio ONLY (Environment Center); do not start ComfyUI.
                conflicts = PortManager.conflicts([ProcessManager.STUDIO_PORT])
                if conflicts[ProcessManager.STUDIO_PORT]["in_use"]:
                    self.logger.error("port 8788 in use")
                    print("[BLOCK] port 8788 in use")
                    self.lock.release()
                    return 1
                self.logger.info("SETUP_REQUIRED: starting Studio in Setup Mode")
                studio = self.pm.start_studio()
                if studio.state == "FAILED":
                    self.logger.error(f"Studio failed: {studio.failure}")
                    self.lock.release()
                    return 1
                url = "http://127.0.0.1:8788"
                if not self.no_browser and not self.dry_run:
                    _open_browser(url)
                print(f"[SETUP_REQUIRED] Studio running in Setup Mode ({url})")
                print("  请完成 Environment Center 配置后继续。日志：logs\\launcher.log")
                return self._serve()

            conflicts = PortManager.conflicts(
                [ProcessManager.COMFYUI_PORT, ProcessManager.STUDIO_PORT])
            for port, info in conflicts.items():
                if info["in_use"]:
                    self.logger.error(f"port {port} in use (pid {info['pid']})")
                    print(f"[BLOCK] port {port} in use (pid {info['pid']})")
                    self.lock.release()
                    return 1

            self.logger.info("starting Native ComfyUI (port 8189)")
            comfyui = self.pm.start_comfyui()
            if comfyui.state == "FAILED":
                self.logger.error(f"ComfyUI failed: {comfyui.failure}")
                print(f"[FAILED] ComfyUI: {comfyui.failure}")
                self.lock.release()
                return 1
            print("[OK] Native ComfyUI RUNNING (8189)")

            self.logger.info("starting Architect Video Studio (port 8788)")
            studio = self.pm.start_studio()
            if studio.state == "FAILED":
                self.logger.error(f"Studio failed: {studio.failure}")
                self.pm.stop("comfyui")
                self.lock.release()
                return 1
            print("[OK] Architect Video Studio RUNNING (8788)")

            url = "http://127.0.0.1:8788"
            if not self.no_browser and not self.dry_run:
                _open_browser(url)
            print(f"[READY] {url}  (Ctrl+C to stop)")
            self.logger.info("READY")
            return self._serve()
        except KeyboardInterrupt:
            return self._shutdown()
        except Exception as exc:  # noqa: BLE001
            self.logger.error(f"launcher error: {exc}")
            print(f"[ERROR] {exc}")
            self._shutdown()
            return 1

    def _serve(self) -> int:
        while True:
            try:
                time.sleep(30)
            except KeyboardInterrupt:
                return self._shutdown()
            self.lock.heartbeat()
            for name, state in self.pm.status().items():
                if state == "FAILED":
                    self.logger.error(f"service {name} FAILED; stopping")
                    return self._shutdown()

    def _shutdown(self) -> int:
        try:
            self.lock.assert_safe_shutdown()
        except RuntimeError as exc:
            self.logger.error(f"shutdown blocked: {exc}")
            print(f"[BLOCK] {exc}")
            return 3
        self.logger.info("shutting down")
        for name in ("studio", "comfyui"):
            if name in self.pm.services:
                self.pm.stop(name)
        self.lock.release()
        print("[STOPPED]")
        return 0

    # ------------------------------------------------------------------ #
    def status(self) -> int:
        lock = self.lock.read_lock()
        print(json_dump({
            "launcher_running": lock is not None,
            "lock": lock,
            "services": self.pm.status(),
            "ports": PortManager.conflicts(
                [ProcessManager.COMFYUI_PORT, ProcessManager.STUDIO_PORT]),
        }))
        return 0

    def shutdown(self) -> int:
        try:
            self.lock.assert_safe_shutdown()
        except RuntimeError as exc:
            print(f"[BLOCK] {exc}")
            return 3
        self.lock.release()
        print("[LOCK RELEASED] (services managed by launcher process)")
        return 0

    def update_check(self) -> int:
        try:
            self.lock.assert_safe_update()
        except RuntimeError as exc:
            print(f"[BLOCK] {exc}")
            return 3
        print("[OK] no GPU job running; update allowed (design gate)")
        return 0


def json_dump(obj) -> str:
    import json
    return json.dumps(obj, indent=2, ensure_ascii=False)


def main() -> int:
    parser = argparse.ArgumentParser(description="Architect Video Studio Launcher")
    parser.add_argument("command", nargs="?", default="start",
                        choices=["start", "status", "shutdown", "update-check"])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--skip-env", action="store_true")
    args = parser.parse_args()
    launcher = Launcher(dry_run=args.dry_run, no_browser=args.no_browser)
    if args.command == "start":
        return launcher.start(skip_env=args.skip_env)
    if args.command == "status":
        return launcher.status()
    if args.command == "shutdown":
        return launcher.shutdown()
    return launcher.update_check()


if __name__ == "__main__":
    sys.exit(main())
