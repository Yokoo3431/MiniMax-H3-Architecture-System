"""RC3.4 PATCH2.8-B - Production Launcher tests (NO GPU).

Covers: environment validation, port detection, lock protection, process
lifecycle, failure handling. All runtime logic is exercised with stubs/dry-run.
"""

import hashlib
import json
import os
import socket
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from launcher.env_check import EnvChecker, EnvPaths  # noqa: E402
from launcher.bootstrap import resolve_launch_python  # noqa: E402
from launcher.launcher import (  # noqa: E402
    Launcher, PortManager as LauncherPortManager, validate_app_only_data_root,
)
from launcher.lock_manager import LockManager  # noqa: E402
from launcher.process_manager import PortManager, ProcessManager, Service  # noqa: E402


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def _write_model(path: Path, content: bytes = b"model-bytes") -> str:
    path.write_bytes(content)
    return _hash(content)


def _make_paths(tmp: Path) -> EnvPaths:
    native = tmp / "native"
    models = tmp / "models"
    (native / "python_embeded").mkdir(parents=True, exist_ok=True)
    (native / "ComfyUI" / "custom_nodes").mkdir(parents=True, exist_ok=True)
    (native / "ComfyUI" / "custom_nodes" / "windows_safe_load").mkdir(exist_ok=True)
    (native / "python_embeded" / "python.exe").write_text("fake", encoding="utf-8")
    (native / "ComfyUI" / "main.py").write_text("fake", encoding="utf-8")
    return EnvPaths(
        native_root=native,
        repo_root=tmp,
        models_root=models,
        baseline_path=tmp / "baseline.json",
        env_report_path=tmp / "env_report.json",
    )


def _write_baseline(tmp: Path, model_dir: Path) -> dict:
    specs = {
        "dit": ("diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors", b"D"),
        "text_encoder": ("text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors", b"T"),
        "video_vae": ("vae/minimax_h3_video_vae_fp16.safetensors", b"V"),
        "audio_vae": ("vae/minimax_h3_audio_vae_fp32.safetensors", b"A"),
    }
    models = {}
    for key, (rel, data) in specs.items():
        path = model_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        sha = _write_model(path, data)
        models[key] = {"filename": Path(rel).name, "sha256": sha}
    baseline = {"models": models}
    (tmp / "baseline.json").write_text(
        json.dumps(baseline, indent=2), encoding="utf-8")
    return baseline


class TestEnvironmentValidation(unittest.TestCase):
    def _checker(self, tmp: Path, **overrides):
        paths = _make_paths(tmp)
        _write_baseline(tmp, paths.models_root)
        kwargs = {
            "paths": paths,
            "torch_available": True,
            "memory_gb": 60.0,
            "disk_free_gb": 100.0,
            "python_version": "Python 3.13.12",
            "comfyui_version": "0.33.1",
            "frontend_version": "1.48.7",
        }
        kwargs.update(overrides)
        return EnvChecker(**kwargs)

    def test_pass_when_all_ok(self):
        with tempfile.TemporaryDirectory() as tmpd:
            tmp = Path(tmpd)
            os.environ["H3_WINDOWS_SAFE_LOAD"] = "pread"
            try:
                report = self._checker(tmp).check_all()
                self.assertEqual(report["overall"], "PASS")
                self.assertTrue((tmp / "env_report.json").is_file())
            finally:
                os.environ.pop("H3_WINDOWS_SAFE_LOAD", None)

    def test_model_hash_mismatch_blocks(self):
        with tempfile.TemporaryDirectory() as tmpd:
            tmp = Path(tmpd)
            paths = _make_paths(tmp)
            _write_baseline(tmp, paths.models_root)
            # corrupt one model after baseline was written
            (paths.models_root / "diffusion_models"
             / "minimax_h3_fl2va_pruned_int8_convrot.safetensors").write_bytes(b"TAMPERED")
            checker = EnvChecker(paths=paths, torch_available=True, memory_gb=60,
                                 disk_free_gb=100, python_version="Python 3.13.12",
                                 comfyui_version="0.33.1", frontend_version="1.48.7")
            report = checker.check_all()
            self.assertEqual(report["overall"], "BLOCK")
            self.assertEqual(report["checks"]["models"]["status"], "BLOCK")

    def test_memory_thresholds(self):
        with tempfile.TemporaryDirectory() as tmpd:
            tmp = Path(tmpd)
            checker = self._checker(tmp)
            self.assertEqual(checker.check_memory()["status"], "PASS")
            self.assertEqual(EnvChecker(memory_gb=40.0).check_memory()["status"], "WARNING")
            self.assertEqual(EnvChecker(memory_gb=25.0).check_memory()["status"], "BLOCK")

    def test_gpu_unavailable_blocks(self):
        with tempfile.TemporaryDirectory() as tmpd:
            checker = self._checker(Path(tmpd), torch_available=False)
            self.assertEqual(checker.check_gpu()["status"], "BLOCK")


class TestPortDetection(unittest.TestCase):
    def test_port_in_use(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
            s.listen(1)
            self.assertTrue(PortManager.port_in_use(port))

    def test_free_port(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        self.assertFalse(PortManager.port_in_use(port))

    def test_find_pid_from_netstat_output(self):
        canned = (
            "  TCP    127.0.0.1:8189    0.0.0.0:0    LISTENING    4242\n"
            "  TCP    127.0.0.1:8788    0.0.0.0:0    LISTENING    5151\n")
        self.assertEqual(PortManager.find_pid(8189, netstat_output=canned), 4242)
        self.assertEqual(PortManager.find_pid(8788, netstat_output=canned), 5151)
        self.assertIsNone(PortManager.find_pid(9999, netstat_output=canned))

    def test_only_known_service_command_lines_are_restartable(self):
        self.assertTrue(PortManager.is_managed_commandline(
            r"python.exe ComfyUI\\main.py --windows-standalone-build --port 8189",
            "comfyui"))
        self.assertTrue(PortManager.is_managed_commandline(
            r"python.exe apps\\architect_video_studio\\run_prototype.py --port 8788",
            "studio"))
        self.assertFalse(PortManager.is_managed_commandline(
            r"python.exe unrelated_server.py --port 8788", "studio"))
        self.assertFalse(PortManager.is_managed_commandline(
            r"unknown.exe --port 8189", "comfyui"))
        self.assertFalse(PortManager.is_managed_commandline(
            r"D:\Experimental\python.exe ComfyUI\\main.py --port 8190",
            "comfyui"))

    def test_managed_studio_identity_uses_explicit_isolated_port(self):
        command = r"python.exe apps\\architect_video_studio\\run_architect_video_studio.py --port 18788"
        self.assertTrue(PortManager.is_managed_commandline(
            command, "studio", expected_port=18788))
        self.assertFalse(PortManager.is_managed_commandline(
            command, "studio", expected_port=8788))

    def test_app_only_studio_service_is_port_and_runtime_isolated(self):
        with tempfile.TemporaryDirectory() as tmpd:
            root = Path(tmpd)
            manager = ProcessManager(
                native_root=root / "unused-runtime",
                repo_root=root / "app",
                python=Path(sys.executable),
                bootstrap_python=Path(sys.executable),
                logs_dir=root / "app" / "Logs",
                studio_app=root / "app" / "apps" / "architect_video_studio",
                studio_workdir=root / "app",
                studio_data=root / "separate-data" / "studio",
                studio_port=18788,
                app_only=True,
            )
            service = manager.studio_service("mock")
            self.assertEqual(service.command[1], "-B")
            self.assertIn("18788", service.command)
            self.assertIn("mock", service.command)
            self.assertEqual(service.env_extra["H3_STUDIO_PORT"], "18788")
            self.assertNotIn("H3_NATIVE_ROOT", service.env_extra)
            self.assertNotIn("H3_MODELS_ROOT", service.env_extra)

    def test_app_only_child_environment_drops_inherited_runtime_identity(self):
        with tempfile.TemporaryDirectory() as tmpd:
            root = Path(tmpd)
            child = SimpleNamespace(poll=lambda: None)
            manager = ProcessManager(
                native_root=root / "unused-runtime",
                repo_root=root / "app",
                python=Path(sys.executable),
                bootstrap_python=Path(sys.executable),
                logs_dir=root / "app" / "Logs",
                studio_app=root / "app" / "apps" / "architect_video_studio",
                studio_workdir=root / "app",
                studio_data=root / "separate-data" / "studio",
                studio_port=18788,
                app_only=True,
                popen=mock.Mock(return_value=child),
            )
            service = manager.studio_service("mock")
            with mock.patch.dict(os.environ, {
                    "H3_NATIVE_ROOT": str(root / "production-comfy"),
                    "H3_MODELS_ROOT": str(root / "production-models"),
                    "MINIMAX_H3_WEIGHTS_ROOTS": str(root / "weights"),
            }), mock.patch("launcher.process_manager.PortManager.port_in_use", return_value=False), \
                 mock.patch("launcher.process_manager._http_ok", return_value=True):
                result = manager.start(service, health_timeout=1)
            self.assertEqual(result.state, "RUNNING")
            child_env = manager._popen.call_args.kwargs["env"]
            self.assertNotIn("H3_NATIVE_ROOT", child_env)
            self.assertNotIn("H3_MODELS_ROOT", child_env)
            self.assertNotIn("MINIMAX_H3_WEIGHTS_ROOTS", child_env)
            self.assertEqual(child_env["H3_STUDIO_PORT"], "18788")
            self.assertTrue(child_env["TEMP"].startswith(str(root / "separate-data")))
            self.assertNotIn(str(root / "app"), child_env["TEMP"])

    def test_app_only_data_root_must_not_overlap_application_root(self):
        with tempfile.TemporaryDirectory() as tmpd:
            root = Path(tmpd)
            application = root / "app"
            self.assertEqual(
                validate_app_only_data_root(root / "separate-data", application),
                (root / "separate-data").resolve(),
            )
            for data_root in (application, application / "data", root):
                with self.subTest(data_root=data_root):
                    with self.assertRaisesRegex(ValueError, "separate"):
                        validate_app_only_data_root(data_root, application)

    def test_app_only_logs_and_studio_data_are_outside_install_root(self):
        with tempfile.TemporaryDirectory() as tmpd, mock.patch.dict(os.environ, {}, clear=False):
            root = Path(tmpd)
            application = root / "install"
            application.mkdir()
            config_path = application / "distribution_config.yaml"
            config_path.write_text(
                (SYSTEM_ROOT / "distribution_config.yaml").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            data_root = root / "external-data"
            with mock.patch("launcher.launcher.REPO_ROOT", application):
                launcher = Launcher(
                    dry_run=True,
                    app_only=True,
                    studio_port=18788,
                    studio_data=data_root,
                    dist_config_path=config_path,
                    lock_path=application / "launcher" / "runtime.lock",
                    paths=_make_paths(root / "path-fixtures"),
                )
            self.assertEqual(launcher.pm.studio_data, data_root / "studio")
            self.assertEqual(launcher.pm.logs_dir, data_root / "logs")
            self.assertTrue((data_root / "logs").is_dir())
            self.assertFalse((application / "Logs").exists())
            self.assertFalse((application / "userdata").exists())

    def test_app_launcher_process_probes_do_not_bypass_execution_policy(self):
        for relative in (
                "launcher/process_manager.py",
                "apps/architect_video_studio/mock_api/environment_probe.py"):
            source = (SYSTEM_ROOT / relative).read_text(encoding="utf-8")
            self.assertNotIn("ExecutionPolicy", source)
            self.assertNotIn("Bypass", source)

    def test_experimental_runtime_executable_is_never_killed_as_production(self):
        with mock.patch.object(PortManager, "port_in_use", return_value=True), \
             mock.patch.object(PortManager, "find_pid", return_value=5151), \
             mock.patch.object(PortManager, "process_commandline",
                               return_value=(r"D:\Experimental\python.exe "
                                             r"ComfyUI\\main.py --port 8189")), \
             mock.patch.object(PortManager, "process_executable",
                               return_value=r"D:\Experimental\python.exe"), \
             mock.patch.object(PortManager, "terminate_pid") as terminate:
            result = PortManager.restart_managed_conflict(
                8189, "comfyui", expected_executable=r"D:\Production\python.exe")
        self.assertEqual(result["status"], "unknown")
        terminate.assert_not_called()

    def test_managed_port_cleanup_targets_exact_runtime_executable(self):
        with mock.patch.object(PortManager, "port_in_use", return_value=True), \
             mock.patch.object(PortManager, "find_pid", return_value=5151), \
             mock.patch.object(PortManager, "process_commandline",
                               return_value=(r"D:\Production\python.exe "
                                             r"ComfyUI\\main.py --port 8189")), \
             mock.patch.object(PortManager, "process_executable",
                               return_value=r"D:\Production\python.exe"), \
             mock.patch.object(PortManager, "terminate_pid", return_value=True) as terminate, \
             mock.patch.object(PortManager, "wait_until_free", return_value=True):
            result = PortManager.restart_managed_conflict(
                8189, "comfyui", expected_executable=r"D:\Production\python.exe")
        self.assertEqual(result["status"], "restarted")
        terminate.assert_called_once_with(5151, timeout=10.0)

    def test_relative_expected_executable_matches_absolute_windows_identity(self):
        absolute_python = str(Path.cwd() / "synthetic_runtime" / "python.exe")
        relative_python = os.path.relpath(absolute_python)
        with mock.patch.object(PortManager, "port_in_use", return_value=True), \
             mock.patch.object(PortManager, "find_pid", return_value=5151), \
             mock.patch.object(PortManager, "process_commandline",
                               return_value=(r"python.exe ComfyUI\\main.py "
                                             r"--port 8189")), \
             mock.patch.object(PortManager, "process_executable",
                               return_value=absolute_python), \
             mock.patch.object(PortManager, "terminate_pid", return_value=True) as terminate, \
             mock.patch.object(PortManager, "wait_until_free", return_value=True):
            result = PortManager.restart_managed_conflict(
                8189, "comfyui", expected_executable=relative_python)
        self.assertEqual(result["status"], "restarted")
        terminate.assert_called_once_with(5151, timeout=10.0)

    def test_managed_process_is_not_killed_without_expected_executable_identity(self):
        with mock.patch.object(PortManager, "port_in_use", return_value=True), \
             mock.patch.object(PortManager, "find_pid", return_value=5151), \
             mock.patch.object(PortManager, "process_commandline",
                               return_value=(r"D:\Production\python.exe "
                                             r"ComfyUI\\main.py --port 8189")), \
             mock.patch.object(PortManager, "terminate_pid") as terminate:
            result = PortManager.restart_managed_conflict(8189, "comfyui")
        self.assertEqual(result["status"], "unknown")
        terminate.assert_not_called()

    def test_unknown_port_owner_is_not_terminated(self):
        with mock.patch.object(PortManager, "port_in_use", return_value=True), \
             mock.patch.object(PortManager, "find_pid", return_value=5151), \
             mock.patch.object(PortManager, "process_commandline",
                               return_value=r"python.exe unrelated_server.py --port 8788"), \
             mock.patch.object(PortManager, "terminate_pid") as terminate:
            result = PortManager.restart_managed_conflict(8788, "studio")
        self.assertEqual(result["status"], "unknown")
        terminate.assert_not_called()


class TestLockProtection(unittest.TestCase):
    def test_duplicate_start_blocked(self):
        with tempfile.TemporaryDirectory() as tmpd:
            lock_path = Path(tmpd) / "runtime.lock"
            l1 = LockManager(lock_path)
            l1.acquire(pid=os.getpid())
            l2 = LockManager(lock_path)
            with self.assertRaises(RuntimeError):
                l2.acquire(pid=os.getpid())
            l1.release()

    def test_stale_lock_allowed(self):
        with tempfile.TemporaryDirectory() as tmpd:
            lock_path = Path(tmpd) / "runtime.lock"
            lock_path.write_text(json.dumps({
                "pid": 999999999, "started_at": "x", "heartbeat": 0,
                "job_running": False}), encoding="utf-8")
            lm = LockManager(lock_path)
            self.assertIsNone(lm.read_lock())  # dead pid -> stale
            lock = lm.acquire(pid=os.getpid())
            self.assertEqual(lock["pid"], os.getpid())
            lm.release()

    def test_job_running_blocks_shutdown(self):
        with tempfile.TemporaryDirectory() as tmpd:
            lm = LockManager(Path(tmpd) / "runtime.lock")
            lm.acquire(pid=os.getpid())
            lm.set_job_running(True)
            with self.assertRaises(RuntimeError):
                lm.assert_safe_shutdown()
            with self.assertRaises(RuntimeError):
                lm.assert_safe_update()
            lm.set_job_running(False)
            lm.assert_safe_shutdown()  # no raise
            lm.release()


class TestProcessLifecycle(unittest.TestCase):
    class FakeProc:
        def __init__(self, exit_code=None):
            self._exit = exit_code
            self.returncode = exit_code
            self.terminated = False
            self.killed = False

        def poll(self):
            return self._exit

        def terminate(self):
            self.terminated = True
            self._exit = 0

        def kill(self):
            self.killed = True
            self._exit = 0

        def wait(self, timeout=None):
            return self._exit

    def test_dry_run_states(self):
        with tempfile.TemporaryDirectory() as tmpd:
            tmp = Path(tmpd)
            pm = ProcessManager(native_root=tmp, repo_root=tmp,
                                python=tmp / "python.exe", logs_dir=tmp / "Logs",
                                dry_run=True)
            svc = pm.start_comfyui()
            self.assertEqual(svc.state, "RUNNING")
            self.assertEqual(pm.status()["comfyui"], "RUNNING")
            pm.stop("comfyui")
            self.assertEqual(pm.status()["comfyui"], "STOPPED")

    def test_failed_process_no_auto_restart(self):
        with tempfile.TemporaryDirectory() as tmpd:
            tmp = Path(tmpd)
            def fake_popen(*args, **kwargs):
                return self.FakeProc(exit_code=3)
            pm = ProcessManager(native_root=tmp, repo_root=tmp,
                                python=tmp / "python.exe", logs_dir=tmp / "Logs",
                                dry_run=False, popen=fake_popen)
            svc = pm._make_service(
                "test", ["fake-cmd"],
                cwd=tmp, health_url="http://127.0.0.1:9/none",
                log_name="test.log")
            svc.port = 0  # skip real port check in unit test
            pm.start(svc, health_timeout=10)
            self.assertEqual(svc.state, "FAILED")
            self.assertIn("exited early", svc.failure)
            # no auto restart: second start still FAILED
            pm.start(svc, health_timeout=5)
            self.assertEqual(svc.state, "FAILED")

    def test_real_process_stop(self):
        with tempfile.TemporaryDirectory() as tmpd:
            tmp = Path(tmpd)
            pm = ProcessManager(native_root=tmp, repo_root=tmp,
                                python=tmp / "python.exe", logs_dir=tmp / "Logs",
                                dry_run=False)
            proc = self.FakeProc()
            svc = Service(name="test", command=[], cwd=tmp, health_url="",
                          log_path=tmp / "test.log", proc=proc, state="RUNNING")
            pm.services["test"] = svc
            pm.stop("test")
            self.assertEqual(svc.state, "STOPPED")
            self.assertTrue(proc.terminated)


class TestLauncherFailureHandling(unittest.TestCase):
    def test_invalid_app_only_python_pin_fails_closed_without_system_fallback(self):
        with tempfile.TemporaryDirectory() as tmpd:
            root = Path(tmpd)
            (root / "bootstrap_python.path").write_text(
                str(root / "missing-python.exe"), encoding="utf-8")
            self.assertIsNone(resolve_launch_python(root, fallback=Path(sys.executable)))

    def test_system_python_fallback_remains_available_without_explicit_pin(self):
        with tempfile.TemporaryDirectory() as tmpd:
            root = Path(tmpd)
            self.assertEqual(resolve_launch_python(root, fallback=Path(sys.executable)),
                             Path(sys.executable).resolve())

    def test_unbound_app_only_clears_only_distribution_runtime_defaults(self):
        with tempfile.TemporaryDirectory() as tmpd:
            root = Path(tmpd)
            data = root / "userdata"
            state_path = data / "system" / "setup_state.json"
            state_path.parent.mkdir(parents=True)
            state_path.write_text('{"install_mode":"app_only","native_root":""}',
                                  encoding="utf-8")
            paths = {
                "H3_NATIVE_ROOT": root / "ArchitectVideoStudio_Runtime",
                "H3_MODELS_ROOT": root / "Models",
                "H3_COMFY_INPUT": root / "ArchitectVideoStudio_Runtime" / "ComfyUI" / "input",
                "H3_COMFY_OUTPUT": root / "ArchitectVideoStudio_Runtime" / "ComfyUI" / "output",
            }
            config = SimpleNamespace(userdata=data, **{
                "native_comfyui_root": paths["H3_NATIVE_ROOT"],
                "models_root": paths["H3_MODELS_ROOT"],
                "comfy_input": paths["H3_COMFY_INPUT"],
                "comfy_output": paths["H3_COMFY_OUTPUT"],
            })
            explicit_runtime = root / "user-selected-runtime"
            with mock.patch.dict(os.environ, {
                    **{name: str(path) for name, path in paths.items()},
            }, clear=False):
                os.environ["H3_NATIVE_ROOT"] = str(explicit_runtime)
                Launcher._clear_unbound_app_only_runtime_defaults(config)
                self.assertEqual(os.environ.get("H3_NATIVE_ROOT"), str(explicit_runtime))
                for name in ("H3_MODELS_ROOT", "H3_COMFY_INPUT", "H3_COMFY_OUTPUT"):
                    self.assertNotIn(name, os.environ)

    def test_prepare_port_supplies_the_selected_runtime_python_identity(self):
        with tempfile.TemporaryDirectory() as tmpd:
            tmp = Path(tmpd)
            paths = _make_paths(tmp)
            launcher = Launcher(dry_run=True, lock_path=tmp / "runtime.lock",
                                paths=paths)
            with mock.patch.object(LauncherPortManager, "restart_managed_conflict",
                                   return_value={"status": "free"}) as prepare:
                self.assertTrue(launcher._prepare_port(8189, "comfyui"))
            self.assertEqual(prepare.call_args.kwargs["expected_executable"],
                             str(launcher.pm.python.resolve()))

    def test_env_block_stops_launcher(self):
        with tempfile.TemporaryDirectory() as tmpd:
            tmp = Path(tmpd)
            paths = _make_paths(tmp)
            class Blocker:
                def check_all(self, light=False):
                    # Bootstrap-level failure (python missing) -> hard BLOCK exit.
                    return {"overall": "BLOCK",
                            "checks": {"python": {"status": "BLOCK"}}}
            launcher = Launcher(dry_run=True, lock_path=tmp / "runtime.lock",
                                paths=paths, env_checker=Blocker())
            self.assertEqual(launcher.start(), 1)
            self.assertFalse((tmp / "runtime.lock").exists())

    def test_duplicate_lock_stops_launcher(self):
        with tempfile.TemporaryDirectory() as tmpd:
            tmp = Path(tmpd)
            lock_path = tmp / "runtime.lock"
            LockManager(lock_path).acquire(pid=os.getpid())
            launcher = Launcher(dry_run=True, lock_path=lock_path,
                                paths=_make_paths(tmp))
            self.assertEqual(launcher.start(), 2)


if __name__ == "__main__":
    unittest.main()
