from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from launcher.lock_manager import LockManager
from launcher.process_manager import ProcessManager
from apps.architect_video_studio.mock_api.job_api import _classify_failure
from runtime.adapters.comfyui_client import ComfyUIOfflineError


class TestNativeCrashRecovery(unittest.TestCase):
    def test_managed_comfy_command_disables_async_and_pinned_offload(self):
        with tempfile.TemporaryDirectory() as tmpd, mock.patch(
            "launcher.process_manager.detect_hardware_facts",
            return_value={"gpu_vram_gb": 12.0, "system_ram_gb": 32.0,
                          "source": ["test"], "errors": []},
        ):
            root = Path(tmpd)
            pm = ProcessManager(root, root, python=root / "python.exe", dry_run=True)
            service = pm.comfyui_service()
            command = service.command
            self.assertIn("--disable-async-offload", command)
            self.assertIn("--disable-pinned-memory", command)
            self.assertEqual(service.env_extra["H3_DEPLOYMENT_PROFILE"], "COMPATIBILITY")
            self.assertEqual(service.env_extra["H3_PROFILE_HARDWARE_SOURCE"], "test")
            self.assertIn("--lowvram", service.command)

    def test_dead_lock_is_removed_and_reclaimed(self):
        with tempfile.TemporaryDirectory() as tmpd:
            path = Path(tmpd) / "runtime.lock"
            path.write_text(json.dumps({"pid": 999999999, "started_at": "old"}), encoding="utf-8")
            manager = LockManager(path)
            self.assertIsNone(manager.read_lock())
            self.assertFalse(path.exists())
            lock = manager.acquire(pid=os.getpid())
            self.assertIn("process_path", lock)
            manager.release()

    def test_pid_identity_mismatch_is_stale(self):
        with tempfile.TemporaryDirectory() as tmpd:
            path = Path(tmpd) / "runtime.lock"
            path.write_text(json.dumps({
                "pid": os.getpid(),
                "process_path": "C:\\\\unrelated\\\\launcher.exe",
            }), encoding="utf-8")
            manager = LockManager(path)
            with mock.patch.object(manager, "_pid_alive", return_value=True), \
                 mock.patch("launcher.lock_manager._windows_process_path",
                            return_value="C:\\\\actual\\\\python.exe"):
                self.assertIsNone(manager.read_lock())
            self.assertFalse(path.exists())

    def test_valid_lock_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmpd:
            path = Path(tmpd) / "runtime.lock"
            manager = LockManager(path)
            manager.acquire(pid=os.getpid())
            self.assertIsNotNone(manager.read_lock())
            self.assertTrue(path.exists())
            manager.release()

    def test_unexpected_comfy_exit_is_published_as_crash(self):
        class Proc:
            def poll(self):
                return 3221225477

        with tempfile.TemporaryDirectory() as tmpd:
            root = Path(tmpd)
            pm = ProcessManager(root, root, python=root / "python.exe", dry_run=True)
            service = pm._make_service("comfyui", [], root, "", "comfy.log")
            service.proc = Proc()
            service.state = "RUNNING"
            pm.refresh()
            self.assertEqual(service.state, "FAILED")
            self.assertIn("COMFYUI_CRASHED", service.failure)

    def test_offline_comfy_is_product_crash_not_gpu_failure(self):
        category, message = _classify_failure(
            ComfyUIOfflineError("ComfyUI offline after native process exit"))
        self.assertEqual(category, "COMFYUI_CRASHED")
        self.assertIn("意外退出", message)


if __name__ == "__main__":
    unittest.main()
