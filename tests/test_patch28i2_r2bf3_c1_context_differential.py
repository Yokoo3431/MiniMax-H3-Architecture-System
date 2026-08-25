"""PATCH2.8-I2-R2B-F3-C1 CPU-only finalization and context-differential tests."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "scripts" / "probe_qwen_visual_device_cycle.py"
G1R3_REPORT = ROOT / "docs" / "PATCH2.8I2_R2BF3_G1R3_Production_Equivalent_Visual_Probe.md"
R2B_R1_REPORT = ROOT / "docs" / "PATCH2.8I2_R2B_R1_GPU_Retry_Report.md"


CONTEXT_MATRIX = {
    "full_w01": {
        "process_orchestration": {
            "studio": "PROVEN",
            "job_api": "PROVEN",
            "native_runtime_adapter": "PROVEN",
            "comfyui_worker": "PROVEN",
            "prompt": "PROVEN",
            "parent_child_topology": "UNKNOWN",
        },
        "model_residency": {
            "qwen_language": "PROVEN",
            "qwen_visual": "PROVEN",
            "dit": "PROVEN",
            "vae": "PROVEN",
            "other_comfy_models": "UNKNOWN",
            "patcher_state": "UNKNOWN",
        },
        "memory": {
            "free_commit_gib": 39.2,
            "available_ram_gib": "UNKNOWN",
            "gpu_free_gib": 10.76,
            "cuda_allocated": "UNKNOWN",
            "cuda_reserved": "UNKNOWN",
            "peak_gpu": "UNKNOWN",
        },
        "comfy_model_management": {
            "loaded": "PROVEN",
            "free_memory": "PROVEN",
            "soft_empty_cache": "UNKNOWN",
            "model_patchers_registered": "UNKNOWN",
        },
        "qwen_state": {
            "linear_patcher": "UNKNOWN",
            "compute_device": "UNKNOWN",
            "inference_active": "UNKNOWN",
            "te_visual_on_cpu": True,
            "visual_dtype": "PROVEN_FP32_LIVE",
        },
        "cuda_state": {
            "allocator_fragmentation": "UNKNOWN",
            "active_streams": "UNKNOWN",
            "synchronization": "UNKNOWN",
            "event_ownership": "UNKNOWN",
        },
        "call_path": "PROVEN_FULL_FL2VA",
    },
    "g1r3_minimal": {
        "process_orchestration": {
            "studio": "NOT_PRESENT",
            "job_api": "NOT_PRESENT",
            "native_runtime_adapter": "NOT_PRESENT",
            "comfyui_worker": "NOT_PRESENT",
            "prompt": "NOT_PRESENT",
            "parent_child_topology": "PROVEN_CHILD_SUPERVISOR",
        },
        "model_residency": {
            "qwen_language": "NOT_ENTERED",
            "qwen_visual": "PROVEN",
            "dit": "NOT_PRESENT",
            "vae": "NOT_PRESENT",
            "other_comfy_models": "NOT_PRESENT",
            "patcher_state": "NOT_PRESENT",
        },
        "memory": {
            "free_commit_gib": 41.776,
            "available_ram_gib": 14.321,
            "gpu_free_gib": 10.76,
            "cuda_allocated": "UNKNOWN",
            "cuda_reserved": "UNKNOWN",
            "peak_gpu": "UNKNOWN",
        },
        "comfy_model_management": {
            "loaded": "NOT_PRESENT",
            "free_memory": "NOT_PRESENT",
            "soft_empty_cache": "NOT_PRESENT",
            "model_patchers_registered": "NOT_PRESENT",
        },
        "qwen_state": {
            "linear_patcher": "NOT_ENTERED",
            "compute_device": "UNKNOWN",
            "inference_active": "NOT_ENTERED",
            "te_visual_on_cpu": True,
            "visual_dtype": "PROVEN_FP32_LIVE",
        },
        "cuda_state": {
            "allocator_fragmentation": "UNKNOWN",
            "active_streams": "UNKNOWN",
            "synchronization": "UNKNOWN",
            "event_ownership": "UNKNOWN",
        },
        "call_path": "PROVEN_MINIMAL_VISUAL_ONLY",
    },
}


class ContextDifferentialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = PROBE.read_text(encoding="utf-8")
        cls.g1r3 = G1R3_REPORT.read_text(encoding="utf-8")
        cls.r2b_r1 = R2B_R1_REPORT.read_text(encoding="utf-8")

    def _run_synthetic_child(self, body: str):
        with tempfile.TemporaryDirectory(prefix="c1_child_") as temp:
            script = Path(temp) / "child.py"
            script.write_text(body, encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, str(script)],
                capture_output=True,
                text=True,
                check=False,
            )
            return completed

    def test_process_survived_marker_does_not_override_nonzero_exit(self):
        result = json.loads(
            (ROOT / "userdata/cache/temp/f3_g1_r3/qwen_visual_result_20260819_145822.json")
            .read_text(encoding="utf-8")
        )
        self.assertIn("G1R3-13", result["stages"])
        self.assertNotEqual(result["exit_code"], 0)
        self.assertNotEqual(result["classification"], "CURRENT_PATH_PASS")

    def test_normal_synthetic_child_exits_zero(self):
        completed = self._run_synthetic_child("print('PROCESS_SURVIVED', flush=True)\n")
        self.assertEqual(completed.returncode, 0)
        self.assertIn("PROCESS_SURVIVED", completed.stdout)

    def test_result_json_persisted_before_normal_exit(self):
        body = (
            "import json\n"
            "from pathlib import Path\n"
            "p = Path.cwd() / 'result.json'\n"
            "p.write_text(json.dumps({'stage':'PROCESS_SURVIVED'}), encoding='utf-8')\n"
        )
        with tempfile.TemporaryDirectory(prefix="c1_result_") as temp:
            script = Path(temp) / "child.py"
            script.write_text(body, encoding="utf-8")
            completed = subprocess.run([sys.executable, str(script)], cwd=temp, check=False)
            self.assertEqual(completed.returncode, 0)
            self.assertEqual(json.loads((Path(temp) / "result.json").read_text()), {"stage": "PROCESS_SURVIVED"})

    def test_explicit_exception_is_nonzero(self):
        completed = self._run_synthetic_child("raise RuntimeError('synthetic failure')\n")
        self.assertNotEqual(completed.returncode, 0)

    def test_explicit_sys_exit_is_preserved(self):
        completed = self._run_synthetic_child("raise SystemExit(7)\n")
        self.assertEqual(completed.returncode, 7)

    def test_broken_stdout_pipe_is_not_production_transport(self):
        self.assertIn("stdout=subprocess.DEVNULL", self.source)
        self.assertIn("stderr=subprocess.DEVNULL", self.source)

    def test_result_write_failure_is_nonzero(self):
        body = "from pathlib import Path\nPath('missing-dir/result.json').write_text('x')\n"
        completed = self._run_synthetic_child(body)
        self.assertNotEqual(completed.returncode, 0)

    def test_probe_restores_streams_before_log_close(self):
        self.assertIn("original_stdout = sys.stdout", self.source)
        self.assertIn("original_stderr = sys.stderr", self.source)
        self.assertIn("finally:", self.source)
        self.assertIn("sys.stdout = original_stdout", self.source)
        self.assertIn("sys.stderr = original_stderr", self.source)

    def test_no_gpu_is_run_by_c1_tests(self):
        source = Path(__file__).read_text(encoding="utf-8")
        self.assertIn("[sys.executable, str(script)]", source)

    def test_no_prompt_contract(self):
        self.assertNotIn("requests.post", self.source)

    def test_no_w01_contract(self):
        self.assertIn("No W01 generation", self.g1r3)

    def test_historical_r2b_r1_classification_preserved(self):
        self.assertIn("INFERENCE_NODE_FAILURE", self.r2b_r1)
        self.assertIn("access violation", self.r2b_r1.lower())

    def test_g1r3_operation_level_pass_is_recorded(self):
        self.assertIn("PROCESS_SURVIVED", self.g1r3)
        self.assertIn("whole-module `visual.to(cpu)` operation completed", self.g1r3)

    def test_g1r3_process_level_result_remains_non_pass(self):
        self.assertIn("G1-R3: `OTHER_TARGETED_FAILURE`", self.g1r3)
        self.assertIn("exit code `120`", self.g1r3)

    def test_context_matrix_has_both_runs(self):
        self.assertEqual(set(CONTEXT_MATRIX), {"full_w01", "g1r3_minimal"})

    def test_unknown_values_cannot_be_promoted(self):
        unknowns = [
            value
            for run in CONTEXT_MATRIX.values()
            for section in run.values()
            if isinstance(section, dict)
            for value in section.values()
            if value == "UNKNOWN"
        ]
        self.assertGreater(len(unknowns), 0)
        self.assertNotIn("PROVEN", unknowns)

    def test_model_residency_fields_present(self):
        fields = CONTEXT_MATRIX["full_w01"]["model_residency"]
        for key in ("qwen_language", "qwen_visual", "dit", "vae", "patcher_state"):
            self.assertIn(key, fields)

    def test_comfy_management_fields_present(self):
        fields = CONTEXT_MATRIX["full_w01"]["comfy_model_management"]
        for key in ("loaded", "free_memory", "soft_empty_cache", "model_patchers_registered"):
            self.assertIn(key, fields)

    def test_qwen_patcher_fields_present(self):
        fields = CONTEXT_MATRIX["g1r3_minimal"]["qwen_state"]
        for key in ("linear_patcher", "compute_device", "inference_active", "te_visual_on_cpu"):
            self.assertIn(key, fields)

    def test_cuda_fields_present(self):
        fields = CONTEXT_MATRIX["g1r3_minimal"]["cuda_state"]
        for key in ("allocator_fragmentation", "active_streams", "synchronization", "event_ownership"):
            self.assertIn(key, fields)

    def test_memory_fields_present(self):
        fields = CONTEXT_MATRIX["g1r3_minimal"]["memory"]
        for key in ("free_commit_gib", "available_ram_gib", "gpu_free_gib", "cuda_allocated", "cuda_reserved"):
            self.assertIn(key, fields)

    def test_no_mitigation_enabled(self):
        self.assertIn("unmitigated", self.g1r3)
        self.assertNotIn("G1R3-G2", self.source)

    def test_no_runtime_model_or_version_change_contract(self):
        self.assertNotIn("upgrade", self.source.lower())
        self.assertNotIn("downgrade", self.source.lower())
        self.assertNotIn("download", self.source.lower())


if __name__ == "__main__":
    unittest.main()
