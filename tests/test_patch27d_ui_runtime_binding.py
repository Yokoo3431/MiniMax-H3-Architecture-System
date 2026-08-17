"""RC3.4 PATCH2.7-D - UI -> Runtime binding tests (NO real GPU).

Covers: API contract stability, VideoGenerationRequest construction, state
transitions (no auto retry), unified output package on real-run completion.
Uses a FakeRuntimeAdapter; no ComfyUI / GPU call.
"""

import base64
import json
import sys
import tempfile
import time
import unittest
import zlib
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from apps.architect_video_studio.mock_api.intent_api import IntentAPI  # noqa: E402
from apps.architect_video_studio.mock_api.job_api import JobAPI  # noqa: E402
from apps.architect_video_studio.mock_api.output_api import OutputAPI  # noqa: E402
from apps.architect_video_studio.mock_api.project_api import ProjectAPI  # noqa: E402
from apps.architect_video_studio.mock_api.prompt_api import PromptAPI  # noqa: E402
from apps.architect_video_studio.mock_api.reference_api import ReferenceAPI  # noqa: E402
from apps.architect_video_studio.mock_api.store import StudioStore  # noqa: E402
from runtime.adapters.runtime_adapter import validate_request  # noqa: E402


def tiny_png_b64() -> str:
    def chunk(tag: bytes, data: bytes) -> bytes:
        import struct
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    ihdr = b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", ihdr)
           + chunk(b"IDAT", zlib.compress(b"\x00\xff\xff\xff"))
           + chunk(b"IEND", b""))
    return base64.b64encode(png).decode()


class FakeRuntimeAdapter:
    """In-memory stand-in for the RuntimeAdapter (no GPU)."""

    def __init__(self, fail: bool = False, video_dir: Path | None = None) -> None:
        self.fail = fail
        self.video_dir = video_dir
        self.last_request = None
        self.job_id = "fake-rt-0001"

    def generate(self, request):
        self.last_request = request
        if self.fail:
            raise RuntimeError("fake runtime failure")
        return {"job_id": self.job_id, "status": "COMPLETED",
                "prompt_id": "fake-prompt"}

    def get_output(self, job_id):
        video = self.video_dir / "fake.mp4"
        video.write_bytes(b"FAKE-MP4-CONTAINER")
        return {
            "job_id": job_id,
            "video_path": str(video),
            "preview_path": str(self.video_dir / "preview.png"),
            "metadata": {"prompt_hash": "B" * 64},
            "runtime_info": {
                "adapter": "fake-native", "gpu_invoked": False,
                "comfyui_invoked": False, "native_runtime_invoked": True,
                "prompt_id": "fake-prompt",
            },
        }


class Harness:
    def __init__(self, adapter=None):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.store = StudioStore(root / "data")
        self.comfy_input = root / "comfy_input"
        self.comfy_input.mkdir(exist_ok=True)
        self.project_api = ProjectAPI(self.store)
        self.reference_api = ReferenceAPI(self.store)
        self.intent_api = IntentAPI(self.store)
        self.prompt_api = PromptAPI(self.store)
        self.output_api = OutputAPI(self.store)
        self.adapter = adapter or FakeRuntimeAdapter(video_dir=root)
        self.job_api = JobAPI(
            self.store, output_api=self.output_api,
            runtime_adapter=self.adapter,
            comfy_input_dir=str(self.comfy_input))

    def full_project(self, name="绑定测试") -> str:
        pid = self.project_api.create_project(name, "exterior", "方案")["id"]
        ref = self.reference_api.upload_reference(
            pid, "01_Exterior_Hero.png", role="first_frame",
            data_base64=tiny_png_b64())
        self.reference_api.approve_reference(pid, ref["id"])
        self.intent_api.analyze_intent(pid, "做一个建筑外观主视角展示视频")
        self.prompt_api.generate_prompt(pid)
        return pid

    def close(self):
        for thread in list(getattr(self.job_api, "_threads", {}).values()):
            thread.join(timeout=2)
        try:
            self.tmp.cleanup()
        except OSError:
            pass  # best-effort temp cleanup on Windows


class TestApiContract(unittest.TestCase):
    def test_submit_accepts_generation_params_and_camera(self):
        h = Harness()
        try:
            pid = h.full_project()
            job = h.job_api.submit_job(
                pid, seed=777888999, risk_reviewed=True,
                generation_parameters={"resolution": "1344x768", "fps": 24,
                                       "duration": 4.0, "quality": "diagnostic"},
                camera_motion="slow_push")
            for field in ("id", "project_id", "workflow", "state", "seed",
                          "prompt_hash", "stages", "runtime"):
                self.assertIn(field, job, field)
            self.assertEqual(job["workflow"], "01_Exterior_Hero")
            self.assertEqual(job["seed"], 777888999)
            self.assertEqual(job["camera_motion"], "slow_push")
            self.assertEqual(job["runtime"], "native")
            self.assertEqual(job["generation_parameters"]["resolution"], "1344x768")
        finally:
            h.close()

    def test_list_jobs_shape(self):
        h = Harness()
        try:
            pid = h.full_project()
            h.job_api.submit_job(pid, risk_reviewed=True)
            jobs = h.job_api.list_jobs(pid)
            self.assertEqual(len(jobs), 1)
            self.assertIn("state", jobs[0])
        finally:
            h.close()


class TestRuntimeRequest(unittest.TestCase):
    def test_builds_valid_video_generation_request(self):
        h = Harness()
        try:
            pid = h.full_project()
            h.job_api.submit_job(
                pid, seed=42, risk_reviewed=True,
                generation_parameters={"resolution": "1344x768", "fps": 24,
                                       "duration": 4.0, "quality": "diagnostic"},
                camera_motion="slow_push")
            deadline = time.time() + 5
            while h.adapter.last_request is None and time.time() < deadline:
                time.sleep(0.05)
            request = h.adapter.last_request
            self.assertIsNotNone(request)
            data = request.to_dict()
            self.assertEqual(validate_request(data), [])
            self.assertEqual(data["workflow_id"], "01_Exterior_Hero")
            self.assertEqual(data["camera_motion"], "slow_push")
            self.assertEqual(data["generation_parameters"]["seed"], 42)
            self.assertTrue(data["gates"]["reference_approved"])
            self.assertTrue(data["gates"]["risk_reviewed"])
            # UI must not build a ComfyUI payload: no node class_type anywhere.
            dumped = json.dumps(data)
            self.assertNotIn("class_type", dumped)
            self.assertNotIn("translated_payload", dumped)
        finally:
            h.close()


class TestStateTransitions(unittest.TestCase):
    def test_real_job_completes(self):
        h = Harness()
        try:
            pid = h.full_project()
            job = h.job_api.submit_job(pid, risk_reviewed=True)
            self.assertEqual(job["state"], "PREPARING")
            deadline = time.time() + 8
            final = None
            while time.time() < deadline:
                final = h.job_api.get_job(job["id"])
                if final["state"] == "COMPLETED":
                    break
                time.sleep(0.1)
            self.assertEqual(final["state"], "COMPLETED")
            self.assertTrue(final["package_built"])
            self.assertIn("COMPLETED", final["stages"])
        finally:
            h.close()

    def test_failure_no_auto_retry(self):
        h = Harness(adapter=FakeRuntimeAdapter(fail=True))
        try:
            pid = h.full_project()
            job = h.job_api.submit_job(pid, risk_reviewed=True)
            deadline = time.time() + 8
            final = None
            while time.time() < deadline:
                final = h.job_api.get_job(job["id"])
                if final["state"] == "GPU_FAILED":
                    break
                time.sleep(0.1)
            self.assertEqual(final["state"], "GPU_FAILED")
            self.assertIn("fake runtime failure", final["failure_reason"])
            # no auto retry: still terminal after waiting
            time.sleep(0.5)
            self.assertEqual(h.job_api.get_job(job["id"])["state"], "GPU_FAILED")
        finally:
            h.close()

    def test_cancel_terminal_no_retry(self):
        h = Harness()
        try:
            pid = h.full_project()
            job = h.job_api.submit_job(pid, risk_reviewed=True)
            # cancel before the fast fake completes
            h.job_api.cancel(job["id"])
            self.assertEqual(h.job_api.get_job(job["id"])["state"], "CANCELLED")
            with self.assertRaises(ValueError):
                h.job_api.cancel(job["id"])
        finally:
            h.close()


class TestOutputPackage(unittest.TestCase):
    def test_unified_package_on_completion(self):
        h = Harness()
        try:
            pid = h.full_project()
            job = h.job_api.submit_job(pid, seed=777888999, risk_reviewed=True)
            deadline = time.time() + 8
            while time.time() < deadline:
                if h.job_api.get_job(job["id"])["state"] == "COMPLETED":
                    break
                time.sleep(0.1)
            pkg = h.store.package_dir(pid)
            for sub in ("input", "workflow", "prompt", "output", "report"):
                self.assertTrue((pkg / sub).is_dir(), sub)
            self.assertTrue((pkg / "output" / "video.mp4").is_file())
            self.assertTrue((pkg / "report" / "runtime_info.json").is_file())
            self.assertTrue((pkg / "report" / "provenance.json").is_file())
            self.assertTrue((pkg / "report" / "generation_report.json").is_file())
            self.assertTrue((pkg / "prompt" / "prompt.json").is_file())
            self.assertTrue(any((pkg / "workflow").glob("*.json")))
            runtime = json.loads((pkg / "report" / "runtime_info.json")
                                 .read_text(encoding="utf-8"))
            self.assertTrue(runtime["native_runtime_invoked"])
            manifest = h.output_api.manifest(pid, h.store.load_jobs(pid)[job["id"]])
            self.assertIn("video.mp4", manifest["structure"]["output"])
        finally:
            h.close()


if __name__ == "__main__":
    unittest.main()
