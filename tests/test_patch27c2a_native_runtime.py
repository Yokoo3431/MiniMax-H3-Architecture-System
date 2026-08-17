"""RC3.4 PATCH2.7-C2-A - Native Runtime integration tests (NO real GPU).

Covers:
1. Contract compatibility (VideoGenerationRequest -> native payload)
2. Mock runtime compatibility (RuntimeAdapter interface via FakeClient)
3. ComfyUI client isolation (stdlib-only HTTP boundary)
4. Error mapping (offline / workflow missing / timeout; no auto retry)
5. Output collection (history -> VideoGenerationOutput)
"""

import sys
import unittest
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from runtime.adapters.comfyui_client import (  # noqa: E402
    ComfyUIClient,
    ComfyUIExecutionError,
    ComfyUIOfflineError,
    GenerationTimeoutError,
    WorkflowNotFoundError,
)
from runtime.adapters.native_runtime_adapter import (  # noqa: E402
    NativeRuntimeAdapter,
    length_for,
    parse_resolution,
)
from runtime.adapters.runtime_adapter import (  # noqa: E402
    VideoGenerationRequest,
    validate_request,
)


def make_request(**overrides):
    request = {
        "study_id": "c2a_test_study",
        "reference_assets": [
            {"asset_id": "ref-1", "role": "first_frame",
             "path_or_ref": "01_Exterior_Hero.png", "sha256": "A" * 64},
        ],
        "workflow_id": "01_Exterior_Hero",
        "camera_motion": "slow_push",
        "generation_parameters": {
            "resolution": "1344x768", "fps": 24, "duration": 4.0,
            "quality": "diagnostic", "seed": 777888999,
        },
        "prompt_payload": {
            "mode": "I2VA",
            "prompt": "For the target video, at 0.00 seconds ...",
            "alignment": "alignment",
            "integrated_multimodal_description": "desc",
            "overall_soundscape": "ambient",
            "non_diegetic_music": "N/A",
            "prompt_hash": "B" * 64,
        },
        "output_spec": {"container": "mp4", "codec": "h264", "fps": 24,
                        "resolution": "1344x768", "report_format": "json"},
        "gates": {"reference_approved": True, "intent_confirmed": True,
                  "prompt_verified": True, "risk_reviewed": True},
    }
    request.update(overrides)
    return VideoGenerationRequest.from_dict(request)


def fake_history():
    return {
        "prompt_id": "fake-1",
        "status": {"status_str": "success", "completed": True},
        "outputs": {
            "15": {
                # realistic SaveVideo shape: animated image entry, not videos[]
                "images": [{"filename": "01_Exterior_Hero_C2A_777888999_00001_.mp4",
                            "subfolder": "video", "type": "output",
                            "animated": True}],
            }
        },
    }


class FakeClient:
    """In-memory ComfyUI client duck-type (no network, no GPU)."""

    def __init__(self, history=None, fail_status=None, offline=False,
                 timeout=False, output_root=None):
        self.history = history or fake_history()
        self.fail_status = fail_status
        self.offline = offline
        self.timeout = timeout
        self.submitted = []
        self.output_root = output_root or str(Path(__file__).parent)

    def submit_workflow(self, payload, client_id=None):
        if self.offline:
            raise ComfyUIOfflineError("offline in test")
        self.submitted.append(payload)
        return {"prompt_id": "fake-1"}

    def wait_completion(self, prompt_id, timeout_seconds=1500.0, poll_interval=5.0):
        if self.timeout:
            raise GenerationTimeoutError("timeout in test")
        if self.fail_status:
            return {"status": "ERROR", "prompt_id": prompt_id,
                    "messages": [["execution_error", {"node_type": "X"}]]}
        return {"status": "COMPLETED", "prompt_id": prompt_id}

    def get_history(self, prompt_id):
        return self.history

    def collect_output(self, history, job_id, workflow_id, metadata=None):
        return ComfyUIClient(output_root=self.output_root).collect_output(
            history, job_id, workflow_id, metadata)


class TestContractCompatibility(unittest.TestCase):
    def test_request_valid(self):
        self.assertEqual(validate_request(make_request().to_dict()), [])

    def test_prepare_payload_injection(self):
        adapter = NativeRuntimeAdapter(client=FakeClient())
        native = adapter.prepare(make_request())
        payload = native["translated_payload"]
        self.assertEqual(payload["1"]["inputs"]["image"], "01_Exterior_Hero.png")
        self.assertEqual(payload["6"]["inputs"]["width"], 1344)
        self.assertEqual(payload["6"]["inputs"]["height"], 768)
        self.assertEqual(payload["6"]["inputs"]["length"], 107)
        self.assertEqual(payload["9"]["inputs"]["noise_seed"], 777888999)
        self.assertEqual(payload["14"]["inputs"]["fps"], 24.0)
        self.assertIn("C2B", payload["15"]["inputs"]["filename_prefix"])
        self.assertEqual(payload["6"]["inputs"]["first_frame"], ["1", 0])
        self.assertEqual(payload["11"]["inputs"]["latent_image"], ["6", 1])

    def test_helpers(self):
        self.assertEqual(parse_resolution("1344x768"), (1344, 768))
        self.assertEqual(length_for(4.0, 24), 107)

    def test_all_production_workflows_supported(self):
        # PATCH2.7-C2-B expanded support to all five frozen workflows.
        adapter = NativeRuntimeAdapter(client=FakeClient())
        for workflow_id, camera in (
                ("01_Exterior_Hero", "slow_push"),
                ("02_Day_Night_Transition", "static"),
                ("03_Material_Detail", "static"),
                ("04_Drone_Aerial", "aerial_reveal"),
                ("05_Slow_Walkthrough", "walkthrough")):
            req = make_request()
            req.workflow_id = workflow_id
            req.camera_motion = camera
            refs = (["DAY.png", "NIGHT.png"]
                    if workflow_id == "02_Day_Night_Transition" else ["ref.png"])
            req.reference_assets = [
                {"asset_id": f"r{i}",
                 "role": "first_frame" if i == 0 else "last_frame",
                 "path_or_ref": n, "sha256": "A" * 64}
                for i, n in enumerate(refs)]
            native = adapter.prepare(req)
            self.assertEqual(native["workflow_id"], workflow_id)


class TestMockRuntimeCompatibility(unittest.TestCase):
    def test_generate_completes_with_fake_client(self):
        adapter = NativeRuntimeAdapter(client=FakeClient())
        job = adapter.generate(make_request())
        self.assertEqual(job["status"], "COMPLETED")
        self.assertEqual(job["existing_job_status"], "COMPLETED")
        self.assertTrue(job["has_output"])
        out = adapter.get_output(job["job_id"])
        self.assertEqual(out["job_id"], job["job_id"])
        self.assertTrue(out["video_path"].endswith(".mp4"))

    def test_interface_methods_present(self):
        adapter = NativeRuntimeAdapter(client=FakeClient())
        for method in ("generate", "status", "cancel", "prepare",
                       "submit", "poll", "collect", "get_output"):
            self.assertTrue(callable(getattr(adapter, method)), method)


class TestComfyUIClientIsolation(unittest.TestCase):
    def test_client_stdlib_only(self):
        source = (SYSTEM_ROOT / "runtime" / "adapters" / "comfyui_client.py") \
            .read_text(encoding="utf-8")
        import_lines = [l.strip() for l in source.splitlines()
                        if l.strip().startswith(("import ", "from "))]
        for forbidden in ("torch", "comfy", "safetensors", "cuda", "cv2", "numpy"):
            self.assertFalse(
                any(forbidden in l.lower() for l in import_lines),
                f"forbidden import token {forbidden!r} in {import_lines}",
            )

    def test_collect_output_contract(self):
        client = ComfyUIClient(output_root=r"C:\mock\output")
        out = client.collect_output(fake_history(), "job-x", "01_Exterior_Hero",
                                    metadata={"seed": 1})
        self.assertEqual(out["job_id"], "job-x")
        self.assertIn("video/01_Exterior_Hero_C2A", out["video_path"])
        self.assertTrue(out["video_path"].endswith(".mp4"))
        self.assertIn("preview_path", out)
        self.assertTrue(out["runtime_info"]["comfyui_invoked"])


class TestErrorMapping(unittest.TestCase):
    def test_offline_raises_runtime_error(self):
        adapter = NativeRuntimeAdapter(client=FakeClient(offline=True))
        with self.assertRaises(RuntimeError):
            adapter.generate(make_request())

    def test_timeout_maps_to_timout_error(self):
        adapter = NativeRuntimeAdapter(client=FakeClient(timeout=True))
        with self.assertRaises(GenerationTimeoutError):
            adapter.generate(make_request())

    def test_workflow_missing_maps_to_workflow_not_found(self):
        adapter = NativeRuntimeAdapter(client=FakeClient())
        # simulate registry missing the frozen asset entry (mapping layer defect)
        adapter.workflow_mapping["workflow_registry"] = {}
        with self.assertRaises(WorkflowNotFoundError):
            adapter.prepare(make_request())

    def test_workflow_not_found_maps_to_failed(self):
        adapter = NativeRuntimeAdapter(client=FakeClient())
        job_id = f"native-{'1' * 12}"
        adapter.jobs[job_id] = {
            "id": job_id, "adapter": "native", "status": "FAILED",
            "prompt_id": None, "stages": ["QUEUED", "PREPARING", "FAILED"],
            "failure_reason": "workflow not found", "error_code": "WORKFLOW_NOT_FOUND",
            "output": None, "created_at": 0.0, "request": {},
        }
        snap = adapter.status(job_id)
        self.assertEqual(snap["error_code"], "WORKFLOW_NOT_FOUND")
        self.assertEqual(snap["existing_job_status"], "FAILED")

    def test_execution_error_maps_to_gpu_failed(self):
        adapter = NativeRuntimeAdapter(client=FakeClient(fail_status="ERROR"))
        with self.assertRaises(ComfyUIExecutionError):
            adapter.generate(make_request())
        job_id = next(iter(adapter.jobs))
        snap = adapter.status(job_id)
        self.assertEqual(snap["status"], "FAILED")
        self.assertEqual(snap["existing_job_status"], "GPU_FAILED")
        self.assertIn("WORKFLOW_EXECUTION_ERROR", snap["error_code"])

    def test_no_auto_retry_after_cancel(self):
        adapter = NativeRuntimeAdapter(client=FakeClient())
        request = make_request()
        adapter.prepare(request)
        # simulate a running job then cancel
        job_id = f"native-{'0' * 12}"
        adapter.jobs[job_id] = {
            "id": job_id, "adapter": "native", "status": "EXECUTING",
            "prompt_id": "fake-1", "stages": ["QUEUED", "PREPARING", "EXECUTING"],
            "failure_reason": "", "error_code": "", "output": None,
            "created_at": 0.0, "request": {},
        }
        cancelled = adapter.cancel(job_id)
        self.assertEqual(cancelled["status"], "CANCELLED")
        self.assertEqual(cancelled["existing_job_status"], "GPU_FAILED")
        with self.assertRaises(ValueError):
            adapter.cancel(job_id)  # terminal -> no cancel / no retry


class TestOutputCollection(unittest.TestCase):
    def test_video_generation_output_fields(self):
        client = ComfyUIClient(output_root=r"C:\mock\output")
        out = client.collect_output(fake_history(), "job-1", "01_Exterior_Hero",
                                    metadata={"prompt_hash": "B" * 64})
        for field in ("job_id", "video_path", "preview_path", "metadata", "runtime_info"):
            self.assertIn(field, out)
        self.assertEqual(out["metadata"]["prompt_hash"], "B" * 64)

    def test_missing_video_output_rejected(self):
        client = ComfyUIClient(output_root=r"C:\mock\output")
        with self.assertRaises(ComfyUIExecutionError):
            client.collect_output({"outputs": {"15": {"images": []}}},
                                  "job-1", "01_Exterior_Hero")


if __name__ == "__main__":
    unittest.main()
