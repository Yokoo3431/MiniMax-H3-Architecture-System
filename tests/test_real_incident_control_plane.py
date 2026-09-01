"""Regression coverage for the owner-observed control-plane incidents."""

import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from apps.architect_video_studio.mock_api.job_api import JobAPI
from apps.architect_video_studio.mock_api.store import StudioStore
from runtime.adapters.comfyui_client import (
    ComfyUIClient,
    ComfyUICommunicationTimeout,
    ComfyProtocolError,
)


class TestControlPlaneObservation(unittest.TestCase):
    def test_queue_timeout_still_checks_history(self):
        client = ComfyUIClient()
        history = {"prompt-1": {
            "prompt": {"extra_data": {"architect_video_studio": {
                "avs_job_id": "job-1", "execution_workflow_sha256": "sha-1"}}},
            "status": {"status_str": "success", "completed": True},
        }}
        with mock.patch.object(client, "get_queue",
                               side_effect=ComfyUICommunicationTimeout("/queue")), \
                mock.patch.object(client, "list_history", return_value=history):
            result = client.reconcile_prompt(
                avs_job_id="job-1", execution_workflow_sha256="sha-1")
        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(result["prompt_id"], "prompt-1")

    def test_non_json_metadata_is_protocol_error(self):
        class Response:
            status = 200
            headers = {"Content-Type": "text/html"}
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def read(self): return b"not-json"

        client = ComfyUIClient()
        with mock.patch("runtime.adapters.comfyui_client.urllib.request.urlopen",
                        return_value=Response()):
            with self.assertRaises(ComfyProtocolError):
                client.get_queue()

    def test_atomic_job_snapshot_survives_concurrent_writes(self):
        with tempfile.TemporaryDirectory() as temp:
            store = StudioStore(Path(temp))
            path = store.projects_root / "p" / "jobs.json"
            def writer(index):
                store.save_json(path, {"job": {"index": index, "prompt_id": "prompt-%d" % index}})
            threads = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
            for thread in threads: thread.start()
            for thread in threads: thread.join()
            payload = store.load_json(path)
            self.assertIn(payload["job"]["index"], range(8))
            self.assertTrue(payload["job"]["prompt_id"].startswith("prompt-"))

    def test_progress_stage_does_not_regress_after_sampling(self):
        with tempfile.TemporaryDirectory() as temp:
            store = StudioStore(Path(temp))
            project_dir = store.project_dir("p")
            project_dir.mkdir(parents=True, exist_ok=True)
            store.save_jobs("p", {"j": {
                "id": "j", "project_id": "p", "state": "PREPARING", "current_stage": "准备参考图",
                "stages": ["PREPARING"], "elapsed": 0,
                "started_at": 0, "prompt_id": "prompt-1",
            }})
            api = JobAPI(store, clock=lambda: 10)
            api._record_progress("p", "j", {"stage": "视频采样", "step": 10, "total_steps": 50})
            api._record_progress("p", "j", {"stage": "加载 H3 模型"})
            job = store.load_jobs("p")["j"]
            self.assertEqual(job["state"], "SAMPLING")
            self.assertEqual(job["current_stage"], "视频采样")

    def test_legacy_timeout_failure_is_reconnectable(self):
        with tempfile.TemporaryDirectory() as temp:
            store = StudioStore(Path(temp))
            api = JobAPI(store, runtime_adapter=SimpleNamespace(client=None))
            job = {
                "runtime": "native", "state": "FAILED", "cancelled": False,
                "failure_code": "COMFYUI_ERROR", "error_category": "COMFYUI_ERROR",
                "technical_details": "GenerationTimeoutError: generation timeout after 1800s",
            }
            self.assertTrue(api._should_reconcile(job))


if __name__ == "__main__":
    unittest.main()
