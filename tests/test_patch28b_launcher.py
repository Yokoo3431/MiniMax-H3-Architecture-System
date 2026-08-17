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
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from launcher.env_check import EnvChecker, EnvPaths  # noqa: E402
from launcher.launcher import Launcher  # noqa: E402
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
    def test_env_block_stops_launcher(self):
        with tempfile.TemporaryDirectory() as tmpd:
            tmp = Path(tmpd)
            paths = _make_paths(tmp)
            class Blocker:
                def check_all(self):
                    return {"overall": "BLOCK", "checks": {}}
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
