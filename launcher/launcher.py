"""Production Launcher (PATCH2.8-B).

Double-click flow:
    launcher -> env check -> restart stale owned services -> start Native
    ComfyUI -> health -> start Studio -> desktop shell READY

    Safety: runtime.lock (single instance); shutdown/cleanup/update blocked while a
    GPU job is running. Only recognizable ComfyUI/Studio processes are restarted;
    unrelated port owners are reported as a bounded actionable conflict.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import webbrowser
from pathlib import Path

_LAUNCHER_DIR = Path(__file__).resolve().parent
REPO_ROOT = _LAUNCHER_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(_LAUNCHER_DIR) not in sys.path:
    sys.path.insert(0, str(_LAUNCHER_DIR))

from dist_config import DistributionConfig
from env_check import EnvChecker, EnvPaths
from bootstrap import resolve_launch_python
from apps.architect_video_studio.mock_api.environment_resolution import resolve_active_environment
from apps.architect_video_studio.mock_api.environment_service import EnvironmentService
from apps.architect_video_studio.mock_api.store import StudioStore
from runtime.h3_model_root import h3_process_environment
from lock_manager import LockManager
from logger import LauncherLogger
from process_manager import PortManager, ProcessManager, _http_ok

DEFAULT_LOCK = Path(__file__).resolve().parent / "runtime.lock"
DEFAULT_LOGS = REPO_ROOT / "Logs"
DEFAULT_DIST_CONFIG = Path(__file__).resolve().parent.parent / "distribution_config.yaml"


def _open_browser(url: str) -> bool:
    """Open a browser without allowing browser integration to kill the server."""
    try:
        return bool(webbrowser.open(url, new=2))
    except Exception:
        return False


def validate_app_only_data_root(data_root: Path, application_root: Path) -> Path:
    """Require isolated data and application roots with no ancestor overlap."""
    data = Path(data_root).resolve()
    application = Path(application_root).resolve()
    try:
        common = Path(os.path.commonpath((str(data), str(application)))).resolve()
    except ValueError as exc:
        raise ValueError("App-only data root and application root must be on a comparable local path") from exc
    normalize = lambda path: os.path.normcase(os.path.normpath(str(path)))
    common_key = normalize(common)
    if common_key in {normalize(data), normalize(application)}:
        raise ValueError("App-only data root must be separate from and not contain the application/source root")
    return data


class Launcher:
    def __init__(self, dry_run: bool = False, no_browser: bool = False,
                 logs_dir: Path = DEFAULT_LOGS,
                 lock_path: Path = DEFAULT_LOCK,
                 paths: EnvPaths | None = None,
                 env_checker=None,
                 dist_config_path: Path | None = None,
                 app_only: bool = False,
                 studio_port: int | None = None,
                 studio_data: Path | None = None) -> None:
        self.dry_run = dry_run
        self.no_browser = no_browser
        self.app_only = bool(app_only)
        app_data_root = None
        if self.app_only:
            if studio_data is None:
                raise ValueError("App-only mode requires an explicit isolated data root")
            app_data_root = validate_app_only_data_root(Path(studio_data), REPO_ROOT)
        self.dist_config = None
        cfg_path = Path(dist_config_path or DEFAULT_DIST_CONFIG)
        if cfg_path.is_file():
            self.dist_config = DistributionConfig(cfg_path)
            self.dist_config.apply_environment()
            self._clear_unbound_app_only_runtime_defaults(self.dist_config)
            logs_dir = (app_data_root / "logs" if self.app_only
                        else self.dist_config.logs)
            (logs_dir).mkdir(parents=True, exist_ok=True)
        elif self.app_only:
            logs_dir = app_data_root / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
        if paths is None and not dry_run and not self.app_only:
            self._adopt_existing_environment()
        self.logger = LauncherLogger(logs_dir, "launcher")
        self.lock = LockManager(lock_path)
        self.paths = paths or EnvPaths()
        self._env_checker = env_checker
        bootstrap_python = (
            Path(sys.executable) if self.app_only and sys.executable else
            resolve_launch_python(
                REPO_ROOT, self.paths.native_root,
                Path(sys.executable) if sys.executable else None,
            )
        )
        pm_kwargs = {"app_only": self.app_only, "studio_port": studio_port}
        if self.dist_config is not None:
            pm_kwargs.update({
                "studio_app": self.dist_config.studio_app,
                "studio_workdir": self.dist_config.studio_workdir,
                "studio_data": (app_data_root / "studio" if self.app_only else
                                Path(studio_data) if studio_data else
                                self.dist_config.userdata / "studio"),
            })
        elif self.app_only:
            pm_kwargs["studio_data"] = app_data_root / "studio"
        elif os.environ.get("H3_STUDIO_DATA"):
            pm_kwargs["studio_data"] = Path(studio_data or os.environ["H3_STUDIO_DATA"])
        elif studio_data is not None:
            pm_kwargs["studio_data"] = Path(studio_data)
        self.pm = ProcessManager(
            native_root=self.paths.native_root,
            repo_root=self.paths.repo_root,
            python=self.paths.python,
            logs_dir=logs_dir,
            dry_run=dry_run,
            bootstrap_python=bootstrap_python,
            **pm_kwargs,
        )

    @staticmethod
    def _clear_unbound_app_only_runtime_defaults(dist_config: DistributionConfig) -> None:
        """Remove only package-default runtime paths for an unbound App-only install."""
        state_path = dist_config.userdata / "system" / "setup_state.json"
        try:
            import json
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return
        if (str(state.get("install_mode", "")).casefold() != "app_only"
                or str(state.get("native_root", "")).strip()):
            return
        defaults = {
            "H3_NATIVE_ROOT": dist_config.native_comfyui_root,
            "H3_MODELS_ROOT": dist_config.models_root,
            "H3_COMFY_INPUT": dist_config.comfy_input,
            "H3_COMFY_OUTPUT": dist_config.comfy_output,
        }
        for name, configured_default in defaults.items():
            current = os.environ.get(name, "").strip()
            if not current:
                continue
            try:
                if Path(current).resolve() == configured_default.resolve():
                    os.environ.pop(name, None)
            except (OSError, RuntimeError, ValueError):
                continue

    def _adopt_existing_environment(self) -> None:
        """Make the launcher use an adopted pair before the first env check."""
        data_root = Path(os.environ.get("H3_STUDIO_DATA", str(REPO_ROOT / "userdata" / "studio")))
        state_path = data_root.parent / "system" / "setup_state.json"
        if not state_path.is_file():
            state_path = REPO_ROOT / "userdata" / "system" / "setup_state.json"
        try:
            import json
            state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.is_file() else {}
        except (OSError, ValueError):
            state = {}
        active = resolve_active_environment(REPO_ROOT, state, os.environ,
                                             use_legacy_config=True,
                                             auto_discover=True)
        if active.native_root:
            native = active.native_root.resolve()
            os.environ["H3_NATIVE_ROOT"] = str(native)
            # DistributionConfig initially exports paths relative to the
            # package.  Once an existing Runtime is adopted, those inherited
            # values must follow the adopted Runtime as well; otherwise the
            # Studio job service stages references into a dead package-local
            # input directory while ComfyUI runs from the adopted Runtime.
            os.environ["H3_COMFY_INPUT"] = str(native / "ComfyUI" / "input")
            os.environ["H3_COMFY_OUTPUT"] = str(native / "ComfyUI" / "output")
        if active.models_root:
            os.environ["H3_MODELS_ROOT"] = str(active.models_root)
            os.environ.update(h3_process_environment(active.models_root))

    # ------------------------------------------------------------------ #
    @staticmethod
    def _production_ready(report: dict) -> bool:
        normalized = report.get("environment_state")
        if normalized:
            gates = normalized.get("gates", {})
            required = (
                "native_root_configured", "comfyui_present", "pread_present",
                "gpu_ready", "models_4of4", "h3_model_root_ready",
                "h3_assets_ready", "h3_support_ready", "video_support_ready",
                "support_dependencies_ready", "skill_pinned_ready",
                "workflows_5of5", "contract_valid", "free_commit_ok",
            )
            return normalized.get("overall") != "BLOCK" and all(gates.get(key) for key in required)
        checks = report.get("checks", {})
        gpu = checks.get("gpu", {}).get("status")
        memory = checks.get("memory", {}).get("status")
        comfyui = checks.get("comfyui", {}).get("status")
        models = checks.get("models", {}).get("status")
        pread = checks.get("pread", {}).get("status")
        return bool(gpu == "PASS" and memory != "BLOCK" and comfyui != "BLOCK"
                    and models != "BLOCK" and pread == "PASS")

    def _production_bootstrap_ready(self, report: dict) -> bool:
        """Start the real services when only live Comfy discovery is pending.

        Model discovery is performed by the ComfyUI process itself.  Treating
        an offline discovery check as an incomplete installation forced the
        launcher into setup/mock mode, where a job could be marked complete
        without a real video.  Static installation contracts still have to be
        valid; only the live ComfyUI discovery result may be pending here.
        """
        state_path = Path(self.pm.studio_data).parent / "system" / "setup_state.json"
        try:
            import json
            setup_state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        # setup_completed may be stale after a live Comfy probe ran offline.
        if not setup_state.get("native_root") or not setup_state.get("models_root"):
            return False
        normalized = report.get("environment_state") or {}
        gates = normalized.get("gates", {})
        required = (
            "native_root_configured", "comfyui_present", "pread_present",
            "gpu_ready", "h3_model_root_ready", "h3_assets_ready",
            "h3_support_ready", "video_support_ready",
            "support_dependencies_ready", "skill_pinned_ready",
            "workflows_5of5", "contract_valid", "free_commit_ok",
        )
        if not all(gates.get(key) for key in required):
            return False
        items = (normalized.get("models") or {}).get("items") or []
        return bool(items) and all(item.get("status") == "READY" for item in items)

    def _environment_report(self) -> dict:
        """Run the same normalized environment source used by the UI.

        The legacy EnvChecker remains injectable for unit tests and old
        diagnostics, but production startup no longer makes an independent
        GPU/model/provenance decision from its stale report format.
        """
        if self._env_checker is not None:
            return self._env_checker.check_all(light=True)
        data_root = Path(os.environ.get("H3_STUDIO_DATA", str(REPO_ROOT / "userdata" / "studio")))
        state = EnvironmentService(StudioStore(data_root)).environment()
        return {
            "overall": state["environment_state"]["overall"],
            "environment_state": state["environment_state"],
            "checked_at": state["environment_state"].get("checked_at"),
        }

    def _prepare_port(self, port: int, service_kind: str) -> bool:
        """Ensure a service port is free without hanging on stale dev state."""
        expected_executable = (
            self.pm.python if service_kind == "comfyui"
            else self.pm.bootstrap_python if service_kind == "studio"
            else None
        )
        result = PortManager.restart_managed_conflict(
            port, service_kind,
            expected_executable=(str(Path(expected_executable).expanduser().resolve())
                                 if expected_executable else None))
        status = result["status"]
        if status == "free":
            return True
        if status == "restarted":
            message = f"restarted stale {service_kind} process (pid {result['pid']})"
            self.logger.info(message)
            print(f"[RESTARTED] {message}")
            return True

        pid = result.get("pid")
        if status == "unknown":
            message = f"port {port} is occupied by an unrecognized process"
        elif status == "still_in_use":
            message = f"managed {service_kind} process stopped but port {port} is still in use"
        else:
            message = f"could not restart managed {service_kind} process on port {port}"
        self.logger.error(f"{message} (pid {pid})")
        print(f"[PORT_CONFLICT] {message} (pid {pid})")
        print("Close that application or choose its supported runtime, then start Architect Video Studio again.")
        return False

    def _start_app_only(self) -> int:
        """Start only the isolated Studio setup service; never inspect/start ComfyUI."""
        url = f"http://127.0.0.1:{self.pm.STUDIO_PORT}"
        if self.dry_run:
            print(f"[APP_ONLY_DRY_RUN] Studio setup service would use {url}")
            return 0
        try:
            self.lock.acquire()
        except RuntimeError as exc:
            self.logger.error(str(exc))
            print(f"[BLOCK] {exc}")
            return 2
        if not self._prepare_port(self.pm.STUDIO_PORT, "studio"):
            self.lock.release()
            return 1
        self.logger.info("APP_ONLY: starting Studio setup service only; ComfyUI is not inspected or started")
        studio = self.pm.start_studio(setup_mode=True)
        if studio.state == "FAILED":
            self.logger.error(f"Studio failed: {studio.failure}")
            print(f"[FAILED] Studio setup service: {studio.failure}")
            self.lock.release()
            return 1
        print(f"[APP_ONLY] Studio setup service RUNNING ({url}); ComfyUI was not started")
        return self._serve()

    def start(self, skip_env: bool = False) -> int:
        self.logger.info("launcher starting")
        if self.app_only:
            return self._start_app_only()
        try:
            self.lock.acquire()
        except RuntimeError as exc:
            self.logger.error(str(exc))
            print(f"[BLOCK] {exc}")
            return 2

        try:
            if not skip_env:
                report = self._environment_report()
                print("Environment check:", report["overall"])
                if self.pm.bootstrap_python is None or not Path(self.pm.bootstrap_python).is_file():
                    self.logger.error("bootstrap python BLOCK")
                    self.lock.release()
                    print("[BLOCK] bootstrap Python not found")
                    return 1
                if self.dry_run and report.get("checks", {}).get("python", {}).get("status") == "BLOCK":
                    self.logger.error("environment check BLOCK (dry-run)")
                    self.lock.release()
                    return 1
            else:
                self.logger.warning("env check skipped (--skip-env)")
                report = {"overall": "READY"}

            production_ready = self._production_ready(report) if not skip_env else True
            if not production_ready and not skip_env:
                production_ready = self._production_bootstrap_ready(report)
            if not production_ready:
                # First-run / incomplete environment -> SETUP_REQUIRED.
                # Start Studio ONLY (Environment Center); do not start ComfyUI.
                if not self._prepare_port(ProcessManager.STUDIO_PORT, "studio"):
                    self.lock.release()
                    return 1
                self.logger.info("SETUP_REQUIRED: starting Studio in Setup Mode")
                studio = self.pm.start_studio(setup_mode=True)
                if studio.state == "FAILED":
                    self.logger.error(f"Studio failed: {studio.failure}")
                    self.lock.release()
                    return 1
                url = "http://127.0.0.1:8788"
                # Normal startup is owned by the desktop shell; never open a
                # system browser implicitly.
                opened = False
                print(f"[SETUP_REQUIRED] Studio running in Setup Mode ({url})")
                print(f"Architect Video Studio is running at: {url}")
                print("  请完成 Environment Center 配置后继续。日志：Logs\\launcher.log")
                return self._serve()

            if not self._prepare_port(ProcessManager.COMFYUI_PORT, "comfyui"):
                self.lock.release()
                return 1
            if not self._prepare_port(ProcessManager.STUDIO_PORT, "studio"):
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
            # Retain the URL for diagnostics, but do not create a browser
            # window from the production launcher.
            opened = False
            print(f"[READY] {url}  (Ctrl+C to stop)")
            print(f"Architect Video Studio is running at: {url}")
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
        crash_published = False
        while True:
            try:
                time.sleep(30)
            except KeyboardInterrupt:
                return self._shutdown()
            self.lock.heartbeat()
            for name, state in self.pm.status().items():
                if state == "FAILED":
                    if name == "comfyui" and not crash_published:
                        # ComfyUI is a replaceable child service. Keep Studio
                        # alive so the user can see the crash state and use
                        # Restart Engine; do not misclassify a native crash as
                        # an installation/setup failure.
                        crash_published = True
                        self.logger.error("service comfyui FAILED; Studio remains available for recovery")
                        print("[COMFYUI_CRASHED] Studio remains available; use Restart Engine.")
                        continue
                    if name == "comfyui":
                        continue
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

    def start_native(self) -> int:
        """Advanced-only Native ComfyUI entry; never starts Studio."""
        try:
            self.lock.acquire()
        except RuntimeError as exc:
            print(f"[BLOCK] {exc}")
            return 2
        try:
            root = Path(self.paths.native_root)
            if not (root / "python_embeded" / "python.exe").is_file():
                print("Native Runtime is not configured.")
                print("Please run Start_ArchitectVideoStudio.bat and complete System Setup first.")
                self.lock.release()
                return 1
            if not (root / "ComfyUI" / "main.py").is_file():
                print(f"Native Runtime is not compatible: {root}")
                self.lock.release()
                return 1
            if not self._prepare_port(ProcessManager.COMFYUI_PORT, "comfyui"):
                self.lock.release()
                return 1
            service = self.pm.start_comfyui()
            if service.state == "FAILED":
                print(f"[FAILED] Native ComfyUI: {service.failure}")
                self.lock.release()
                return 1
            url = "http://127.0.0.1:8189"
            # Native ComfyUI is an explicit Advanced diagnostic surface.
            opened = False
            print(f"[READY] Native ComfyUI is running at: {url}")
            return self._serve()
        except KeyboardInterrupt:
            return self._shutdown()
        except Exception as exc:
            self.logger.error(f"native launcher error: {exc}")
            print(f"[ERROR] {exc}")
            self.lock.release()
            return 1


def json_dump(obj) -> str:
    import json
    return json.dumps(obj, indent=2, ensure_ascii=False)


def main() -> int:
    parser = argparse.ArgumentParser(description="Architect Video Studio Launcher")
    parser.add_argument("command", nargs="?", default="start",
                        choices=["start", "native", "status", "shutdown", "update-check"])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--skip-env", action="store_true")
    parser.add_argument("--app-only", action="store_true",
                        help="Start only the isolated Studio setup service; never start ComfyUI")
    parser.add_argument("--studio-port", type=int,
                        help="Required with --app-only; must not be a production/runtime port")
    parser.add_argument("--data-root", type=Path,
                        help="Required with --app-only; separate isolated Studio data directory")
    args = parser.parse_args()
    if args.app_only:
        if args.command != "start" or args.skip_env:
            parser.error("--app-only is only valid for start and cannot be combined with --skip-env")
        if args.studio_port is None or args.data_root is None:
            parser.error("--app-only requires explicit --studio-port and --data-root")
        if not 1024 <= args.studio_port <= 65535 or args.studio_port in {8189, 8190, 8788}:
            parser.error("--app-only Studio port must be an isolated non-production port")
        try:
            validate_app_only_data_root(args.data_root, REPO_ROOT)
        except ValueError as exc:
            parser.error(str(exc))
    elif args.studio_port is not None or args.data_root is not None:
        parser.error("--studio-port and --data-root require --app-only")
    launcher = Launcher(
        dry_run=args.dry_run,
        no_browser=args.no_browser,
        app_only=args.app_only,
        studio_port=args.studio_port,
        studio_data=args.data_root,
    )
    if args.command == "start":
        return launcher.start(skip_env=args.skip_env)
    if args.command == "native":
        return launcher.start_native()
    if args.command == "status":
        return launcher.status()
    if args.command == "shutdown":
        return launcher.shutdown()
    return launcher.update_check()


if __name__ == "__main__":
    sys.exit(main())
