"""Local Study-flow acceptance contracts; no GPU or /prompt execution."""

from __future__ import annotations

import base64
import json
import sys
import tempfile
import threading
import unittest
import urllib.request
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from apps.architect_video_studio.mock_api.job_api import JobAPI  # noqa: E402
from apps.architect_video_studio.mock_api.output_api import OutputAPI  # noqa: E402
from apps.architect_video_studio.mock_api.project_api import ProjectAPI  # noqa: E402
from apps.architect_video_studio.mock_api.reference_api import ReferenceAPI  # noqa: E402
from apps.architect_video_studio.mock_api.server import make_server  # noqa: E402
from apps.architect_video_studio.mock_api.store import StudioStore  # noqa: E402
from apps.architect_video_studio.mock_api.study_state import build_study_state  # noqa: E402
from apps.architect_video_studio.mock_api.intent_api import IntentAPI  # noqa: E402
from apps.architect_video_studio.mock_api.prompt_api import PromptAPI  # noqa: E402


def tiny_png_b64() -> str:
    import struct

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = struct.pack(">I", len(data)) + tag + data
        return body + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
           + chunk(b"IDAT", zlib.compress(b"\x00\xff\xff\xff"))
           + chunk(b"IEND", b""))
    return base64.b64encode(png).decode()


class StudyHarness:
    def __init__(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = StudioStore(Path(self.tmp.name))
        self.projects = ProjectAPI(self.store)
        self.refs = ReferenceAPI(self.store)
        self.intent = IntentAPI(self.store)
        self.prompt = PromptAPI(self.store)
        self.jobs = JobAPI(self.store, output_api=OutputAPI(self.store))

    def close(self) -> None:
        self.tmp.cleanup()

    def ready_project(self) -> str:
        project = self.projects.create_project("Study flow test")
        ref = self.refs.upload_reference(
            project["id"], "中文 reference image.png", data_base64=tiny_png_b64())
        self.refs.approve_reference(project["id"], ref["id"])
        self.intent.analyze_intent(project["id"], "做一个入口缓慢推进的视频")
        self.prompt.generate_prompt(project["id"])
        return project["id"]


class TestStudyStateRecovery(unittest.TestCase):
    def test_historical_gpu_failure_is_not_current_study_failure(self):
        h = StudyHarness()
        try:
            pid = h.ready_project()
            old_job = h.jobs.submit_job(pid, risk_reviewed=True)
            h.jobs.fail_job(old_job["id"], "synthetic old GPU failure")

            state = build_study_state(h.store, pid)
            self.assertEqual(state["last_job_status"], "GPU_FAILED")
            self.assertEqual(state["current_state"], "READY_TO_GENERATE")
            self.assertTrue(state["reference_approved"])
            self.assertTrue(state["prompt_ready"])
            self.assertTrue(state["generate_allowed"])
            self.assertNotIn("GPU_FAILED", state["generation_status"])

            new_job = h.jobs.submit_job(pid, risk_reviewed=True)
            self.assertNotEqual(new_job["id"], old_job["id"])
            state = build_study_state(h.store, pid)
            self.assertEqual(state["current_state"], "GENERATING")
            self.assertEqual(state["active_job_id"], new_job["id"])
        finally:
            h.close()

    def test_normalized_state_does_not_expose_absolute_asset_path(self):
        h = StudyHarness()
        try:
            pid = h.ready_project()
            state = build_study_state(h.store, pid)
            encoded = json.dumps(state, ensure_ascii=False)
            self.assertNotIn(str(h.store.input_dir(pid)), encoded)
            self.assertRegex(state["reference_preview_url"], r"^/api/assets/ref-[A-Za-z0-9_-]+/content\?v=")

            h.intent.select_workflow(pid, "04_Drone_Aerial")
            changed = build_study_state(h.store, pid)
            self.assertEqual(changed["selected_workflow"], "04_Drone_Aerial")
            self.assertFalse(changed["prompt_ready"])
            self.assertIsNone(h.store.load_prompt(pid))
        finally:
            h.close()


class TestTrustedAssetEndpoint(unittest.TestCase):
    def test_png_asset_is_served_by_id_with_mime(self):
        h = StudyHarness()
        server = None
        thread = None
        try:
            pid = h.projects.create_project("Asset endpoint")['id']
            ref = h.refs.upload_reference(
                pid, "中文 name.png", data_base64=tiny_png_b64())
            self.assertNotIn("stored_path", ref)
            self.assertTrue(ref["preview_ready"])
            server = make_server(("127.0.0.1", 0), Path(h.tmp.name), runtime="mock")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            url = f"http://127.0.0.1:{server.server_address[1]}/api/assets/{ref['id']}/content"
            with urllib.request.urlopen(url, timeout=3) as response:
                body = response.read()
                self.assertEqual(response.headers.get_content_type(), "image/png")
                self.assertTrue(body.startswith(b"\x89PNG"))
        finally:
            if server is not None:
                server.shutdown()
                server.server_close()
            if thread is not None:
                thread.join(timeout=3)
            h.close()


if __name__ == "__main__":
    unittest.main()
