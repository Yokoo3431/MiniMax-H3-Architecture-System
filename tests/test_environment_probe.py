"""Focused tests for the Environment Center's layered local probe."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from apps.architect_video_studio.mock_api.environment_probe import (  # noqa: E402
    EnvironmentProbe,
    _policy,
)
from apps.architect_video_studio.mock_api.environment_service import (  # noqa: E402
    EnvironmentService,
)


def _completed(stdout="", stderr="", returncode=0):
    return mock.Mock(stdout=stdout, stderr=stderr, returncode=returncode)


def _torch_json(ok=True, name="NVIDIA GeForce RTX 5070", vram=12_227 * 1024 * 1024):
    return json.dumps({
        "torch": "2.13.0+cu130",
        "cuda": "13.0",
        "ok": ok,
        "name": name if ok else "",
        "vram": vram if ok else None,
    })


class TestEnvironmentProbe(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.runtime = Path(self.tmp.name) / "runtime"
        python = self.runtime / "python_embeded" / "python.exe"
        python.parent.mkdir(parents=True)
        python.write_bytes(b"fixture")

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, command, **_kwargs):
        executable = str(command[0]).lower()
        if executable == "nvidia-smi":
            return _completed("NVIDIA GeForce RTX 5070, 591.86, 12227\n")
        if executable.endswith("python.exe"):
            return _completed(_torch_json())
        raise AssertionError(f"unexpected probe command: {command}")

    def test_nvidia_smi_parse_and_torch_success(self):
        with mock.patch("apps.architect_video_studio.mock_api.environment_probe.subprocess.run", side_effect=self._run):
            result = EnvironmentProbe(self.runtime).run()
        self.assertTrue(result["gpu_detected"])
        self.assertEqual(result["gpu_name"], "NVIDIA GeForce RTX 5070")
        self.assertEqual(result["driver_version"], "591.86")
        self.assertEqual(result["gpu_vram_bytes"], 12_227 * 1024 * 1024)
        self.assertTrue(result["torch_import_ok"])
        self.assertTrue(result["torch_cuda_available"])
        self.assertEqual(result["probe_status"], "READY")

    def test_nvidia_smi_failure_uses_windows_fallback(self):
        def fallback(command, **_kwargs):
            executable = str(command[0]).lower()
            if executable == "nvidia-smi":
                raise FileNotFoundError("nvidia-smi missing")
            if executable.endswith("powershell.exe"):
                return _completed(json.dumps({
                    "Name": "NVIDIA GeForce RTX 5070",
                    "AdapterRAM": 12_227 * 1024 * 1024,
                    "DriverVersion": "591.86",
                }))
            return _completed(_torch_json())

        with mock.patch("apps.architect_video_studio.mock_api.environment_probe.subprocess.run", side_effect=fallback):
            result = EnvironmentProbe(self.runtime).run()
        self.assertTrue(result["gpu_detected"])
        self.assertTrue(result["driver_detected"])
        self.assertEqual(result["gpu_name"], "NVIDIA GeForce RTX 5070")
        self.assertIn("windows_gpu_fallback", result["diagnostics"])

    def test_torch_import_failure_preserves_hardware_evidence(self):
        def torch_failure(command, **_kwargs):
            if str(command[0]).lower() == "nvidia-smi":
                return _completed("NVIDIA GeForce RTX 5070, 591.86, 12227\n")
            return _completed(stderr="ModuleNotFoundError: No module named torch", returncode=1)

        with mock.patch("apps.architect_video_studio.mock_api.environment_probe.subprocess.run", side_effect=torch_failure):
            result = EnvironmentProbe(self.runtime).run()
        self.assertTrue(result["gpu_detected"])
        self.assertTrue(result["driver_detected"])
        self.assertFalse(result["torch_import_ok"])
        self.assertFalse(result["torch_cuda_available"])
        self.assertEqual(result["probe_status"], "ISSUE")
        self.assertIn("ModuleNotFoundError", result["diagnostics"]["torch"]["stderr"])

    def test_torch_cuda_false_is_runtime_issue_not_missing_hardware(self):
        def torch_false(command, **_kwargs):
            if str(command[0]).lower() == "nvidia-smi":
                return _completed("NVIDIA GeForce RTX 5070, 591.86, 12227\n")
            return _completed(_torch_json(ok=False))

        with mock.patch("apps.architect_video_studio.mock_api.environment_probe.subprocess.run", side_effect=torch_false):
            result = EnvironmentProbe(self.runtime).run()
        self.assertTrue(result["gpu_detected"])
        self.assertTrue(result["driver_detected"])
        self.assertTrue(result["torch_import_ok"])
        self.assertFalse(result["torch_cuda_available"])
        self.assertEqual(result["probe_status"], "ISSUE")

    def test_probe_timeout_is_bounded_and_diagnostic(self):
        def timeout(command, **_kwargs):
            raise __import__("subprocess").TimeoutExpired(command[0], 5)

        with mock.patch("apps.architect_video_studio.mock_api.environment_probe.subprocess.run", side_effect=timeout):
            result = EnvironmentProbe(self.runtime).run()
        self.assertEqual(result["probe_status"], "ISSUE")
        self.assertEqual(result["diagnostics"]["nvidia_smi"]["status"], "TIMEOUT")
        self.assertEqual(result["diagnostics"]["torch"]["status"], "TIMEOUT")
        self.assertIn("timeout", result["probe_error"])

    def test_empty_nvidia_smi_output_does_not_fake_driver_ready(self):
        def empty(command, **_kwargs):
            if str(command[0]).lower() == "nvidia-smi":
                return _completed("")
            if str(command[0]).lower().endswith("powershell.exe"):
                return _completed("")
            return _completed(_torch_json())

        with mock.patch("apps.architect_video_studio.mock_api.environment_probe.subprocess.run", side_effect=empty):
            result = EnvironmentProbe(self.runtime).run()
        self.assertTrue(result["gpu_detected"])
        self.assertFalse(result["driver_detected"])

    def test_experimental_policy_is_not_unsupported(self):
        policy = _policy(12_227 * 1024 * 1024)
        self.assertEqual(policy["status"], "EXPERIMENTAL")

    def test_block_semantics_are_independent_from_experimental_policy(self):
        service = object.__new__(EnvironmentService)
        system = {"gpu_ready": True, "free_commit": 60}
        runtime = {"present": True, "pread": True, "version": "0.33.1", "frontend": "1.48.7"}
        models = {"ready": 4, "count": 4}
        support = {"h3": {"ready": True}, "video": {"ready": True}, "dependencies": {"ready": True}}
        skill = {"generation_allowed": True, "status": "READY"}
        gates = {
            "native_root_configured": True, "comfyui_present": True,
            "models_4of4": True, "pread_present": True,
            "h3_model_root_ready": True, "h3_assets_ready": True,
            "h3_support_ready": True, "video_support_ready": True,
            "support_dependencies_ready": True, "workflows_5of5": True,
            "contract_valid": True,
        }
        self.assertEqual(service._overall(system, runtime, models, support, skill, gates), "READY")
        system["gpu_ready"] = False
        self.assertEqual(service._overall(system, runtime, models, support, skill, gates), "BLOCK")

    def test_recheck_runs_a_fresh_probe_each_time(self):
        service = object.__new__(EnvironmentService)
        service.overrides = {"memory_gb": 64, "disk_free_gb": 100}
        contract = {
            "gpu_detected": True, "gpu_name": "RTX 5070", "gpu_vram_bytes": 12_227 * 1024 * 1024,
            "driver_detected": True, "driver_version": "591.86", "torch_import_ok": True,
            "torch_cuda_available": True, "torch_version": "2.13", "torch_cuda_version": "13.0",
            "torch_gpu_name": "RTX 5070", "torch_gpu_total_memory": 12_227 * 1024 * 1024,
            "runtime_python_found": True, "runtime_python_path": "fixture", "probe_error": "",
            "hardware_policy": _policy(12_227 * 1024 * 1024), "probe_status": "READY",
            "diagnostics": {"nvidia_smi": {"status": "PASS"}},
        }
        with mock.patch.object(EnvironmentProbe, "run", side_effect=[contract, contract]) as probe:
            service._system_status("", "")
            service._system_status("", "")
        self.assertEqual(probe.call_count, 2)


if __name__ == "__main__":
    unittest.main()
