"""Focused transport/lost-ack tests; no ComfyUI process or GPU required."""

import json
import urllib.error
import unittest
from unittest import mock

from runtime.adapters.comfyui_client import (
    ComfyUIClient,
    ComfyUICommunicationTimeout,
    ComfyUISubmissionUnknown,
)


class _Response:
    status = 200

    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.payload


class TestTimeoutPolicies(unittest.TestCase):
    def test_prompt_timeout_is_submission_unknown(self):
        client = ComfyUIClient(submission_timeout=60)
        with mock.patch(
                "runtime.adapters.comfyui_client.urllib.request.urlopen",
                side_effect=urllib.error.URLError(
                    TimeoutError("timed out"))):
            with self.assertRaises(ComfyUISubmissionUnknown):
                client.submit_workflow({"1": {"class_type": "LoadImage"}})

    def test_metadata_timeout_is_not_engine_crash(self):
        client = ComfyUIClient(metadata_timeout=10)
        with mock.patch(
                "runtime.adapters.comfyui_client.urllib.request.urlopen",
                side_effect=urllib.error.URLError(
                    TimeoutError("timed out"))):
            with self.assertRaises(ComfyUICommunicationTimeout):
                client.get_queue()

    def test_observation_timeout_continues_and_completes(self):
        client = ComfyUIClient()
        states = [
            ComfyUICommunicationTimeout("history timeout"),
            {"status": "COMPLETED", "prompt_id": "p1",
             "event": {"type": "execution_success"}},
        ]
        with mock.patch.object(client, "get_status",
                               side_effect=states), \
                mock.patch("runtime.adapters.comfyui_client.time.sleep"):
            result = client.wait_completion("p1", timeout_seconds=5, poll_interval=0)
        self.assertEqual(result["status"], "COMPLETED")


class TestReconciliation(unittest.TestCase):
    def test_queue_correlation_recovers_running_prompt(self):
        client = ComfyUIClient()
        with mock.patch.object(client, "get_queue", return_value={
            "queue_running": [[1, "prompt-1234", {
                "extra_data": {"architect_video_studio": {
                    "avs_job_id": "job-1",
                    "execution_workflow_sha256": "sha-1",
                }},
            }]],
            "queue_pending": [],
        }), mock.patch.object(client, "list_history", return_value={}):
            result = client.reconcile_prompt(
                avs_job_id="job-1", execution_workflow_sha256="sha-1")
        self.assertEqual(result["status"], "RUNNING")
        self.assertEqual(result["prompt_id"], "prompt-1234")

    def test_completed_history_is_recovered(self):
        client = ComfyUIClient()
        history = {"prompt-2": {
            "prompt": {"extra_data": {"architect_video_studio": {
                "avs_job_id": "job-2", "execution_workflow_sha256": "sha-2"}}},
            "status": {"status_str": "success", "completed": True},
            "outputs": {},
        }}
        with mock.patch.object(client, "get_queue", return_value={
            "queue_running": [], "queue_pending": []}), \
                mock.patch.object(client, "list_history", return_value=history):
            result = client.reconcile_prompt(
                avs_job_id="job-2", execution_workflow_sha256="sha-2")
        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(result["prompt_id"], "prompt-2")


if __name__ == "__main__":
    unittest.main()
