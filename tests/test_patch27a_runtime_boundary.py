"""RC3.4 PATCH2.7-A - Runtime Boundary contract tests.

Covers the VideoGenerationRequest contract, MockRuntimeAdapter lifecycle
(generate/status/cancel), Runtime Status -> existing Job Status mapping, and
the VideoGenerationOutput contract. No GPU / CUDA / ComfyUI / model calls.
"""

import sys
import unittest
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from runtime.adapters.runtime_adapter import (  # noqa: E402
    DEFAULT_CONTRACT,
    MockRuntimeAdapter,
    VideoGenerationRequest,
    load_contract,
    map_runtime_status,
    validate_request,
)


def make_request(**overrides):
    request = {
        "study_id": "facade_motion_study",
        "reference_assets": [
            {"asset_id": "ref-1", "role": "first_frame",
             "path_or_ref": "mock://assets/facade.png", "sha256": "A" * 64},
        ],
        "workflow_id": "01_Exterior_Hero",
        "camera_motion": "slow_push",
        "generation_parameters": {
            "resolution": "1344x768", "fps": 24, "duration": 4.0,
            "quality": "diagnostic", "seed": 42,
        },
        "prompt_payload": {
            "mode": "I2VA",
            "prompt": "For the target video, at 0.00 seconds ...",
            "alignment": "alignment",
            "integrated_multimodal_description": "desc",
            "overall_soundscape": "ambient",
            "non_diegetic_music": "N/A",
            "prompt_hash": "B" * 64,
            "provenance_ref": "proj-x/report/provenance.json",
        },
        "output_spec": {
            "container": "mp4", "codec": "h264", "fps": 24,
            "resolution": "1344x768", "report_format": "json",
        },
        "gates": {
            "reference_approved": True,
            "intent_confirmed": True,
            "prompt_verified": True,
            "risk_reviewed": True,
        },
    }
    request.update(overrides)
    return request


class FakeClock:
    def __init__(self, value: float = 0.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


class TestRequestContract(unittest.TestCase):
    def test_contract_yaml_loads(self):
        contract = load_contract(DEFAULT_CONTRACT)
        self.assertIn("video_generation_request", contract)
        self.assertIn("runtime_status", contract)
        self.assertIn("state_mapping", contract)
        self.assertEqual(
            contract["video_generation_request"]["workflow_id"]["allowed"],
            ["01_Exterior_Hero", "02_Day_Night_Transition",
             "03_Material_Detail", "04_Drone_Aerial", "05_Slow_Walkthrough"],
        )

    def test_valid_request_passes(self):
        self.assertEqual(validate_request(make_request()), [])

    def test_missing_required_field_rejected(self):
        errors = validate_request({})
        for field in ("study_id", "reference_assets", "workflow_id",
                      "camera_motion", "generation_parameters",
                      "prompt_payload", "output_spec", "gates"):
            self.assertTrue(any(field in e for e in errors), field)

    def test_invalid_workflow_rejected(self):
        errors = validate_request(make_request(workflow_id="99_Unknown"))
        self.assertTrue(any("workflow_id" in e for e in errors))

    def test_invalid_camera_rejected(self):
        errors = validate_request(make_request(camera_motion="flyover_360"))
        self.assertTrue(any("camera_motion" in e for e in errors))

    def test_gate_missing_rejected(self):
        gates = {"reference_approved": True, "intent_confirmed": True,
                 "prompt_verified": True, "risk_reviewed": False}
        errors = validate_request(make_request(gates=gates))
        self.assertTrue(any("risk_reviewed" in e for e in errors))

    def test_request_roundtrip(self):
        data = make_request()
        req = VideoGenerationRequest.from_dict(data)
        self.assertEqual(req.to_dict(), data)
        self.assertEqual(validate_request(req.to_dict()), [])


class TestStateMapping(unittest.TestCase):
    def test_mapping_table(self):
        cases = {
            "QUEUED": "PREPARING",
            "PREPARING": "PREPARING",
            "LOADING_MODEL": "LOADING_MODEL",
            "SAMPLING": "SAMPLING",
            "ENCODING": "ENCODING",
            "EXPORTING": "EXPORTING",
            "COMPLETED": "COMPLETED",
            "FAILED": "GPU_FAILED",
            "CANCELLED": "GPU_FAILED",
        }
        for runtime, existing in cases.items():
            self.assertEqual(map_runtime_status(runtime), existing, runtime)

    def test_unknown_status_rejected(self):
        with self.assertRaises(ValueError):
            map_runtime_status("MELTING")


class TestMockRuntimeAdapter(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock(0.0)
        self.adapter = MockRuntimeAdapter(clock=self.clock)

    def test_generate_returns_queued_job(self):
        job = self.adapter.generate(make_request())
        self.assertEqual(job["status"], "QUEUED")
        self.assertEqual(job["adapter"], "mock")
        self.assertTrue(job["job_id"].startswith("rt-"))
        self.assertFalse(job["has_output"])

    def test_status_progression_to_completed(self):
        job = self.adapter.generate(make_request())
        self.clock.value = 0.4
        self.assertEqual(self.adapter.status(job["job_id"])["status"], "QUEUED")
        self.clock.value = 0.8
        self.assertEqual(self.adapter.status(job["job_id"])["status"], "PREPARING")
        self.clock.value = 1.5
        self.assertEqual(self.adapter.status(job["job_id"])["status"], "LOADING_MODEL")
        self.clock.value = 2.5
        self.assertEqual(self.adapter.status(job["job_id"])["status"], "SAMPLING")
        self.clock.value = 3.5
        self.assertEqual(self.adapter.status(job["job_id"])["status"], "ENCODING")
        self.clock.value = 4.5
        self.assertEqual(self.adapter.status(job["job_id"])["status"], "EXPORTING")
        self.clock.value = 5.5
        final = self.adapter.status(job["job_id"])
        self.assertEqual(final["status"], "COMPLETED")
        self.assertEqual(final["existing_job_status"], "COMPLETED")
        self.assertTrue(final["has_output"])

    def test_generate_rejects_invalid_request(self):
        with self.assertRaises(ValueError) as ctx:
            self.adapter.generate(make_request(workflow_id="bad"))
        self.assertIn("contract violation", str(ctx.exception))

    def test_cancel_and_no_retry(self):
        job = self.adapter.generate(make_request())
        self.clock.value = 1.2
        cancelled = self.adapter.cancel(job["job_id"])
        self.assertEqual(cancelled["status"], "CANCELLED")
        self.assertEqual(cancelled["existing_job_status"], "GPU_FAILED")
        self.clock.value = 999.0
        after = self.adapter.status(job["job_id"])
        self.assertEqual(after["status"], "CANCELLED")  # no auto retry

    def test_cancel_terminal_rejected(self):
        job = self.adapter.generate(make_request())
        self.clock.value = 999.0
        self.assertEqual(self.adapter.status(job["job_id"])["status"], "COMPLETED")
        with self.assertRaises(ValueError):
            self.adapter.cancel(job["job_id"])

    def test_output_contract_after_completion(self):
        job = self.adapter.generate(make_request())
        self.clock.value = 999.0
        out = self.adapter.get_output(job["job_id"])
        self.assertEqual(out["job_id"], job["job_id"])
        self.assertTrue(out["video_path"].startswith("mock://"))
        self.assertTrue(out["preview_path"].startswith("mock://"))
        self.assertEqual(out["metadata"]["workflow_id"], "01_Exterior_Hero")
        self.assertEqual(out["metadata"]["camera_motion"], "slow_push")
        self.assertEqual(out["metadata"]["resolution"], "1344x768")
        self.assertEqual(out["metadata"]["fps"], 24)
        self.assertFalse(out["runtime_info"]["gpu_invoked"])
        self.assertFalse(out["runtime_info"]["comfyui_invoked"])
        self.assertFalse(out["runtime_info"]["native_runtime_invoked"])

    def test_output_unavailable_until_completed(self):
        job = self.adapter.generate(make_request())
        self.clock.value = 2.0
        with self.assertRaises(ValueError):
            self.adapter.get_output(job["job_id"])

    def test_unknown_job_rejected(self):
        with self.assertRaises(KeyError):
            self.adapter.status("rt-nope")


class TestNoGpuBoundary(unittest.TestCase):
    def test_adapter_source_has_no_gpu_or_comfyui_imports(self):
        source = (SYSTEM_ROOT / "runtime" / "adapters" / "runtime_adapter.py") \
            .read_text(encoding="utf-8")
        import_lines = [l.strip() for l in source.splitlines()
                        if l.strip().startswith(("import ", "from "))]
        for forbidden in ("torch", "comfy", "safetensors", "cuda", "openai", "requests"):
            self.assertFalse(
                any(forbidden in l.lower() for l in import_lines),
                f"forbidden import token {forbidden!r} in {import_lines}",
            )


if __name__ == "__main__":
    unittest.main()
