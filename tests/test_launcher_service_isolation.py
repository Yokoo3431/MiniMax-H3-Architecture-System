"""Synthetic lifecycle tests for independent Studio service maintenance."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from launcher.env_check import EnvPaths  # noqa: E402
from launcher.launcher import Launcher  # noqa: E402
from launcher.process_manager import (  # noqa: E402
    EXPERIMENTAL_COMFY_SERVICE,
    PRODUCTION_COMFY_SERVICE,
    STUDIO_SERVICE,
    ProcessManager,
    Service,
)


class FakeProcess:
    def __init__(self, pid: int, exit_code: int | None = None,
                 terminate_sticks: bool = False) -> None:
        self.pid = pid
        self.returncode = exit_code
        self.terminated = False
        self.killed = False
        self.terminate_sticks = terminate_sticks
        self.long_task_active = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        if not self.terminate_sticks:
            self.returncode = 0

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None):
        if self.returncode is None:
            raise subprocess.TimeoutExpired("synthetic-child", timeout)
        return self.returncode


def _manager(root: Path, popen=None) -> ProcessManager:
    return ProcessManager(
        native_root=root / "runtime",
        repo_root=root / "source",
        python=Path(sys.executable),
        bootstrap_python=Path(sys.executable),
        logs_dir=root / "logs",
        studio_port=18788,
        popen=popen,
    )


def _service(name: str, pid: int, proc: FakeProcess,
             state: str = "RUNNING") -> Service:
    return Service(
        name=name,
        command=["synthetic", "--port", "18788"],
        cwd=Path.cwd(),
        health_url="http://127.0.0.1:18788/api/health",
        log_path=Path.cwd() / "synthetic.log",
        proc=proc,
        owned_pid=pid,
        state=state,
    )


class TestStudioLifecycleIsolation(unittest.TestCase):
    def test_service_roles_are_explicit_and_distinct(self):
        self.assertEqual(len({STUDIO_SERVICE, PRODUCTION_COMFY_SERVICE,
                              EXPERIMENTAL_COMFY_SERVICE}), 3)
        with tempfile.TemporaryDirectory() as temp:
            manager = _manager(Path(temp))
            studio = manager.studio_service()
            production = manager._make_service(
                PRODUCTION_COMFY_SERVICE, [], Path(temp), "", "comfy.log")
            experimental = manager._make_service(
                EXPERIMENTAL_COMFY_SERVICE, [], Path(temp), "", "experimental.log")
            self.assertEqual(studio.runtime_role, "studio")
            self.assertEqual(production.runtime_role, "production")
            self.assertEqual(experimental.runtime_role, "experimental")

    def test_normal_exit_and_crash_are_reported_without_touching_other_children(self):
        for exit_code in (0, 7):
            with self.subTest(exit_code=exit_code), tempfile.TemporaryDirectory() as temp:
                manager = _manager(Path(temp))
                studio = _service(STUDIO_SERVICE, 1001,
                                  FakeProcess(1001, exit_code=exit_code))
                comfy_proc = FakeProcess(1002)
                comfy_proc.long_task_active = True
                comfy = _service(PRODUCTION_COMFY_SERVICE, 1002, comfy_proc)
                manager.services.update({STUDIO_SERVICE: studio,
                                         PRODUCTION_COMFY_SERVICE: comfy})

                states = manager.refresh()

                self.assertEqual(states[STUDIO_SERVICE], "FAILED")
                self.assertEqual(states[PRODUCTION_COMFY_SERVICE], "RUNNING")
                self.assertTrue(comfy_proc.long_task_active)
                self.assertFalse(comfy_proc.terminated)

    def test_restart_replaces_only_studio_and_preserves_comfy_long_task(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            created = []

            def popen(*_args, **_kwargs):
                proc = FakeProcess(2000 + len(created))
                created.append(proc)
                return proc

            manager = _manager(root, popen=popen)
            old_studio = FakeProcess(1001)
            manager.services[STUDIO_SERVICE] = _service(STUDIO_SERVICE, 1001, old_studio)
            comfy_proc = FakeProcess(1002)
            comfy_proc.long_task_active = True
            comfy = _service(PRODUCTION_COMFY_SERVICE, 1002, comfy_proc)
            manager.services[PRODUCTION_COMFY_SERVICE] = comfy

            with mock.patch("launcher.process_manager.PortManager.port_in_use",
                            return_value=False), \
                 mock.patch("launcher.process_manager.PortManager.wait_until_free",
                            return_value=True), \
                 mock.patch("launcher.process_manager.PortManager.find_pid",
                            side_effect=lambda _port: created[-1].pid), \
                 mock.patch("launcher.process_manager._http_ok", return_value=True):
                result = manager.restart_studio_only(health_timeout=1)

            self.assertEqual(result.state, "RUNNING")
            self.assertEqual(result.owned_pid, created[0].pid)
            self.assertTrue(old_studio.terminated)
            self.assertEqual(comfy.state, "RUNNING")
            self.assertFalse(comfy_proc.terminated)
            self.assertTrue(comfy_proc.long_task_active)

    def test_two_sequential_studio_restarts_keep_comfy_untouched(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            created = []

            def popen(*_args, **_kwargs):
                proc = FakeProcess(3000 + len(created))
                created.append(proc)
                return proc

            manager = _manager(root, popen=popen)
            first = FakeProcess(1001)
            manager.services[STUDIO_SERVICE] = _service(STUDIO_SERVICE, 1001, first)
            comfy_proc = FakeProcess(1002)
            manager.services[PRODUCTION_COMFY_SERVICE] = _service(
                PRODUCTION_COMFY_SERVICE, 1002, comfy_proc)
            with mock.patch("launcher.process_manager.PortManager.port_in_use",
                            return_value=False), \
                 mock.patch("launcher.process_manager.PortManager.wait_until_free",
                            return_value=True), \
                 mock.patch("launcher.process_manager.PortManager.find_pid",
                            side_effect=lambda _port: created[-1].pid), \
                 mock.patch("launcher.process_manager._http_ok", return_value=True):
                one = manager.restart_studio_only(health_timeout=1)
                two = manager.restart_studio_only(health_timeout=1)

            self.assertEqual(one.state, "RUNNING")
            self.assertEqual(two.state, "RUNNING")
            self.assertEqual(len(created), 2)
            self.assertEqual(manager.services[STUDIO_SERVICE].owned_pid, created[1].pid)
            self.assertEqual(manager.services[PRODUCTION_COMFY_SERVICE].state, "RUNNING")
            self.assertFalse(comfy_proc.terminated)

    def test_occupied_port_fails_closed_without_killing_listener(self):
        with tempfile.TemporaryDirectory() as temp:
            manager = _manager(Path(temp), popen=mock.Mock())
            with mock.patch("launcher.process_manager.PortManager.port_in_use",
                            return_value=True), \
                 mock.patch("launcher.process_manager.PortManager.terminate_pid") as terminate:
                result = manager.start_studio_only(health_timeout=0.01)
            self.assertEqual(result.state, "FAILED")
            self.assertIn("already in use", result.failure)
            manager._popen.assert_not_called()
            terminate.assert_not_called()

    def test_studio_start_preparation_failure_does_not_touch_comfy(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manager = _manager(root)
            comfy_proc = FakeProcess(1002)
            comfy = _service(PRODUCTION_COMFY_SERVICE, 1002, comfy_proc)
            manager.services[PRODUCTION_COMFY_SERVICE] = comfy
            with mock.patch("launcher.process_manager.ensure_cache_dirs",
                            side_effect=PermissionError("synthetic denied path")):
                result = manager.start_studio_only(health_timeout=0.01)

            self.assertEqual(result.state, "FAILED")
            self.assertIn("PermissionError", result.failure)
            self.assertEqual(comfy.state, "RUNNING")
            self.assertFalse(comfy_proc.terminated)

    def test_pid_mismatch_refuses_to_signal_studio_handle(self):
        with tempfile.TemporaryDirectory() as temp:
            manager = _manager(Path(temp))
            proc = FakeProcess(1111)
            studio = _service(STUDIO_SERVICE, 2222, proc)
            manager.services[STUDIO_SERVICE] = studio

            result = manager.stop_studio_only()

            self.assertEqual(result.state, "FAILED")
            self.assertIn("identity mismatch", result.failure)
            self.assertFalse(proc.terminated)
            self.assertFalse(proc.killed)

    def test_health_does_not_adopt_a_foreign_listener_on_studio_port(self):
        with tempfile.TemporaryDirectory() as temp:
            manager = _manager(Path(temp))
            proc = FakeProcess(1111)
            manager.services[STUDIO_SERVICE] = _service(STUDIO_SERVICE, 1111, proc)
            with mock.patch("launcher.process_manager.PortManager.find_pid",
                            return_value=9999), \
                 mock.patch("launcher.process_manager._http_ok", return_value=True):
                self.assertFalse(manager.health_studio_only())

    def test_restart_timeout_cleans_only_new_child_and_leaves_comfy_running(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            created = []

            def popen(*_args, **_kwargs):
                proc = FakeProcess(4000 + len(created))
                created.append(proc)
                return proc

            manager = _manager(root, popen=popen)
            old_studio = FakeProcess(1001)
            manager.services[STUDIO_SERVICE] = _service(STUDIO_SERVICE, 1001, old_studio)
            comfy_proc = FakeProcess(1002)
            comfy = _service(PRODUCTION_COMFY_SERVICE, 1002, comfy_proc)
            manager.services[PRODUCTION_COMFY_SERVICE] = comfy
            with mock.patch("launcher.process_manager.PortManager.port_in_use",
                            return_value=False), \
                 mock.patch("launcher.process_manager.PortManager.wait_until_free",
                            return_value=True), \
                 mock.patch("launcher.process_manager._http_ok", return_value=False):
                result = manager.restart_studio_only(health_timeout=0)

            self.assertEqual(result.state, "FAILED")
            self.assertTrue(old_studio.terminated)
            self.assertTrue(created[0].terminated)
            self.assertEqual(comfy.state, "RUNNING")
            self.assertFalse(comfy_proc.terminated)

    def test_stop_timeout_kills_only_the_owned_popen_handle(self):
        with tempfile.TemporaryDirectory() as temp:
            manager = _manager(Path(temp))
            proc = FakeProcess(1111, terminate_sticks=True)
            manager.services[STUDIO_SERVICE] = _service(STUDIO_SERVICE, 1111, proc)
            with mock.patch("launcher.process_manager.PortManager.terminate_pid") as terminate_pid:
                result = manager.stop_studio_only(timeout=0.01)
            self.assertEqual(result.state, "STOPPED")
            self.assertTrue(proc.terminated)
            self.assertTrue(proc.killed)
            terminate_pid.assert_not_called()

    def test_launcher_keeps_supervising_after_studio_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            paths = EnvPaths(
                native_root=root / "runtime", repo_root=root,
                models_root=root / "models", baseline_path=root / "baseline.json",
                env_report_path=root / "env.json",
            )
            launcher = Launcher(dry_run=True, lock_path=root / "runtime.lock", paths=paths)
            comfy_proc = FakeProcess(1002)
            comfy_proc.long_task_active = True
            running = Service(
                name=STUDIO_SERVICE, command=[], cwd=root,
                health_url="", log_path=root / "studio.log", state="RUNNING")
            launcher.pm.status = mock.Mock(side_effect=[
                {PRODUCTION_COMFY_SERVICE: "RUNNING", STUDIO_SERVICE: "FAILED"},
                {PRODUCTION_COMFY_SERVICE: "RUNNING", STUDIO_SERVICE: "RUNNING"},
            ])
            launcher.pm.restart_studio_only = mock.Mock(return_value=running)
            launcher.lock.heartbeat = mock.Mock()
            launcher.lock.assert_safe_shutdown = mock.Mock()
            launcher._shutdown = mock.Mock(return_value=0)
            with mock.patch("launcher.launcher.time.sleep",
                            side_effect=[None, None, KeyboardInterrupt]):
                result = launcher._serve()

            self.assertEqual(result, 0)
            launcher.pm.restart_studio_only.assert_called_once()
            self.assertEqual(launcher.pm.status.call_count, 2)
            self.assertTrue(comfy_proc.long_task_active)
            self.assertFalse(comfy_proc.terminated)
            launcher._shutdown.assert_called_once()  # only the synthetic Ctrl+C exit

    def test_studio_restart_exception_does_not_escalate_to_launcher_shutdown(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            paths = EnvPaths(
                native_root=root / "runtime", repo_root=root,
                models_root=root / "models", baseline_path=root / "baseline.json",
                env_report_path=root / "env.json",
            )
            launcher = Launcher(dry_run=True, lock_path=root / "runtime.lock", paths=paths)
            comfy_proc = FakeProcess(1002)
            comfy_proc.long_task_active = True
            launcher.pm.status = mock.Mock(side_effect=[
                {PRODUCTION_COMFY_SERVICE: "RUNNING", STUDIO_SERVICE: "FAILED"},
            ])
            launcher.pm.restart_studio_only = mock.Mock(
                side_effect=OSError("synthetic startup preparation failure"))
            launcher.lock.heartbeat = mock.Mock()
            launcher.lock.assert_safe_shutdown = mock.Mock()
            launcher._shutdown = mock.Mock(return_value=0)
            with mock.patch("launcher.launcher.time.sleep",
                            side_effect=[None, KeyboardInterrupt]):
                result = launcher._serve()

            self.assertEqual(result, 0)
            launcher.pm.restart_studio_only.assert_called_once()
            self.assertTrue(comfy_proc.long_task_active)
            self.assertFalse(comfy_proc.terminated)
            launcher._shutdown.assert_called_once()  # only the synthetic Ctrl+C exit

    def test_initial_studio_failure_does_not_stop_started_comfy_service(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            paths = EnvPaths(
                native_root=root / "runtime", repo_root=root,
                models_root=root / "models", baseline_path=root / "baseline.json",
                env_report_path=root / "env.json",
            )
            launcher = Launcher(dry_run=True, lock_path=root / "runtime.lock", paths=paths)
            comfy_proc = FakeProcess(1002)
            comfy = _service(PRODUCTION_COMFY_SERVICE, 1002, comfy_proc)
            failed_studio = _service(STUDIO_SERVICE, 1003,
                                     FakeProcess(1003, exit_code=2), state="FAILED")
            launcher.pm.start_comfyui = mock.Mock(return_value=comfy)
            launcher.pm.start_studio = mock.Mock(return_value=failed_studio)
            launcher.pm.stop = mock.Mock()
            launcher._prepare_port = mock.Mock(return_value=True)
            launcher._environment_report = mock.Mock(return_value={"overall": "READY"})
            launcher._serve = mock.Mock(return_value=0)

            try:
                result = launcher.start(skip_env=True)
                self.assertEqual(result, 0)
                launcher.pm.stop.assert_not_called()
                self.assertEqual(comfy.state, "RUNNING")
                self.assertIsNone(comfy_proc.returncode)
            finally:
                launcher.lock.release()

    def test_explicit_launcher_shutdown_stops_only_its_tracked_services(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            paths = EnvPaths(
                native_root=root / "runtime", repo_root=root,
                models_root=root / "models", baseline_path=root / "baseline.json",
                env_report_path=root / "env.json",
            )
            launcher = Launcher(dry_run=False, lock_path=root / "runtime.lock", paths=paths)
            studio_proc = FakeProcess(1001)
            comfy_proc = FakeProcess(1002)
            launcher.pm.services[STUDIO_SERVICE] = _service(STUDIO_SERVICE, 1001, studio_proc)
            launcher.pm.services[PRODUCTION_COMFY_SERVICE] = _service(
                PRODUCTION_COMFY_SERVICE, 1002, comfy_proc)
            launcher.lock.acquire(pid=os.getpid())

            result = launcher._shutdown()

            self.assertEqual(result, 0)
            self.assertTrue(studio_proc.terminated)
            self.assertTrue(comfy_proc.terminated)
            self.assertFalse((root / "runtime.lock").exists())

    def test_launcher_studio_restart_is_blocked_while_job_is_running(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            paths = EnvPaths(
                native_root=root / "runtime", repo_root=root,
                models_root=root / "models", baseline_path=root / "baseline.json",
                env_report_path=root / "env.json",
            )
            launcher = Launcher(dry_run=True, lock_path=root / "runtime.lock", paths=paths)
            launcher.lock.acquire(pid=os.getpid())
            launcher.lock.set_job_running(True)
            launcher.pm.restart_studio_only = mock.Mock()
            try:
                with self.assertRaisesRegex(RuntimeError, "GPU job is running"):
                    launcher.restart_studio_only()
                launcher.pm.restart_studio_only.assert_not_called()
            finally:
                launcher.lock.set_job_running(False)
                launcher.lock.release()


if __name__ == "__main__":
    unittest.main()
