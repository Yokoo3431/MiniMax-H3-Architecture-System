"""Focused transport/lost-ack tests; no ComfyUI process or GPU required."""

import json
import tempfile
import urllib.error
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from apps.architect_video_studio.mock_api.job_api import JobAPI
from apps.architect_video_studio.mock_api.store import StudioStore
from runtime.adapters.comfyui_client import (
    ComfyUIClient,
    ComfyUICommunicationTimeout,
    ComfyUIOfflineError,
    ComfyUISubmissionUnknown,
)
from runtime.a4_2_quality_acceptance import _mark_submission_boundary


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

    def test_offline_observation_reconnects_same_prompt_without_resubmission(self):
        client = ComfyUIClient()
        observed_prompts = []

        def get_status(prompt_id):
            observed_prompts.append(prompt_id)
            if len(observed_prompts) == 1:
                raise ComfyUIOfflineError("ComfyUI temporarily unavailable")
            return {"status": "COMPLETED", "prompt_id": prompt_id,
                    "event": {"type": "execution_success"}}

        with mock.patch.object(client, "get_status", side_effect=get_status), \
                mock.patch.object(client, "submit_workflow") as submit, \
                mock.patch("runtime.adapters.comfyui_client.time.sleep"):
            result = client.wait_completion(
                "persisted-prompt-1", timeout_seconds=5, poll_interval=0)

        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(result["prompt_id"], "persisted-prompt-1")
        self.assertEqual(observed_prompts, ["persisted-prompt-1"] * 2)
        submit.assert_not_called()


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

    def test_seed_match_cannot_shadow_correlated_running_ab_arm(self):
        client = ComfyUIClient()
        history = {"old-standard-prompt": {
            "prompt": {"noise": {"inputs": {"noise_seed": 42}}},
            "status": {"status_str": "success", "completed": True},
            "outputs": {},
        }}
        queue = {"queue_running": [[1, "current-high-prompt", {
            "extra_data": {"architect_video_studio": {
                "avs_job_id": "job-high",
                "execution_workflow_sha256": "sha-high",
            }},
            "prompt": {"noise": {"inputs": {"noise_seed": 42}}},
        }]], "queue_pending": []}
        with mock.patch.object(client, "list_history", return_value=history), \
                mock.patch.object(client, "get_queue", return_value=queue):
            result = client.reconcile_prompt(
                avs_job_id="job-high", execution_workflow_sha256="sha-high",
                legacy_seed=42)
        self.assertEqual(result["status"], "RUNNING")
        self.assertEqual(result["prompt_id"], "current-high-prompt")
        self.assertEqual(result["source"], "queue")

    def test_stale_prompt_id_cannot_override_stronger_job_correlation(self):
        client = ComfyUIClient()
        history = {"old-standard-prompt": {
            "prompt": {"extra_data": {"architect_video_studio": {
                "avs_job_id": "job-standard",
                "execution_workflow_sha256": "sha-standard",
            }}},
            "status": {"status_str": "success", "completed": True},
            "outputs": {},
        }}
        queue = {"queue_running": [[1, "current-high-prompt", {
            "extra_data": {"architect_video_studio": {
                "avs_job_id": "job-high",
                "execution_workflow_sha256": "sha-high",
            }},
        }]], "queue_pending": []}
        with mock.patch.object(client, "list_history", return_value=history), \
                mock.patch.object(client, "get_queue", return_value=queue):
            result = client.reconcile_prompt(
                prompt_id="old-standard-prompt", avs_job_id="job-high",
                execution_workflow_sha256="sha-high", legacy_seed=42)
        self.assertEqual(result["status"], "RUNNING")
        self.assertEqual(result["prompt_id"], "current-high-prompt")
        self.assertEqual(result["source"], "queue")

    def test_observer_permission_error_reconciles_exact_running_prompt(self):
        with tempfile.TemporaryDirectory() as temp:
            store = StudioStore(Path(temp))
            store.save_jobs("p", {"job-1": {
                "id": "job-1", "project_id": "p", "runtime": "native",
                "runtime_target": "experimental", "runtime_id": "experimental-h3-8190",
                "state": "FAILED", "lifecycle_state": "FAILED",
                "submission_state": "RECONCILING", "failure_code": "COMFYUI_ERROR",
                "prompt_id": "prompt-1", "execution_workflow_sha256": "sha-1",
                "stages": ["PREPARING"], "cancelled": False,
            }})

            class _Client:
                def __init__(self):
                    self.calls = 0

                def reconcile_prompt(self, **identity):
                    self.calls += 1
                    self.assert_identity = identity
                    return {"status": "RUNNING", "prompt_id": "prompt-1",
                            "source": "queue", "entry": {}}

            class _Runtime:
                def __init__(self):
                    self.client = _Client()
                    self.generate_calls = 0

                def poll(self, *_args, **_kwargs):
                    raise PermissionError(13, "observer persistence denied")

                def generate(self, *_args, **_kwargs):
                    self.generate_calls += 1
                    raise AssertionError("observer recovery must not submit generation")

            runtime = _Runtime()
            api = JobAPI(store, experimental_runtime_adapter=runtime)
            api._reattach_job("p", "job-1", "prompt-1")

            job = store.load_jobs("p")["job-1"]
            self.assertEqual(runtime.client.calls, 1)
            self.assertEqual(runtime.client.assert_identity["prompt_id"], "prompt-1")
            self.assertEqual(job["state"], "SAMPLING")
            self.assertEqual(job["submission_state"], "ACKNOWLEDGED")
            self.assertEqual(job["last_observation"]["status"], "RUNNING")
            self.assertEqual(job["execution_workflow_sha256"], "sha-1")
            self.assertEqual(runtime.generate_calls, 0)

    def test_terminal_reactivation_requires_same_prompt_and_workflow_identity(self):
        failed = {
            "state": "FAILED", "runtime": "native",
            "runtime_target": "experimental", "runtime_id": "experimental-h3-8190",
            "submission_state": "RECONCILING", "prompt_id": "prompt-1",
            "execution_workflow_sha256": "sha-1",
        }
        running = {
            **failed, "state": "SAMPLING", "submission_state": "ACKNOWLEDGED",
        }
        self.assertTrue(JobAPI._is_confirmed_reconciled_reactivation(failed, running))
        self.assertFalse(JobAPI._is_confirmed_reconciled_reactivation(
            failed, {**running, "prompt_id": "different-prompt"}))
        self.assertFalse(JobAPI._is_confirmed_reconciled_reactivation(
            failed, {**running, "execution_workflow_sha256": "different-sha"}))


class TestA42SubmissionBoundary(unittest.TestCase):
    def test_post_boundary_exception_remains_unknown_and_is_not_retried(self):
        with tempfile.TemporaryDirectory() as temp:
            store = StudioStore(Path(temp))
            store.project_dir("p").mkdir(parents=True, exist_ok=True)
            store.save_jobs("p", {"job-1": {
                "id": "job-1", "project_id": "p", "runtime": "native",
                "state": "PREPARING", "stages": ["PREPARING"],
                "cancelled": False, "submission_state": "NOT_STARTED",
                "acceptance_submission_attempts": 0,
            }})

            class _FailingAdapter:
                client = None

                def __init__(self):
                    self.calls = 0

                def attach_job_identity(self, prepared, job_id):
                    return prepared

                def generate(self, request, prepared=None):
                    self.calls += 1
                    raise RuntimeError("lost acknowledgement after prompt submit")

            adapter = _FailingAdapter()
            api = JobAPI(store, runtime_adapter=adapter, allow_mock_jobs=False)
            api._stage_refs_to_comfy_input = lambda *_args: None
            api._build_workflow_snapshot = lambda *_args: {
                "snapshot_id": "snapshot-1", "workflow_hash": "workflow-hash",
                "execution_workflow_sha256": "execution-hash", "asset_hash": "asset-hash",
            }
            request = SimpleNamespace(reference_assets=[], workflow_id="04_Drone_Aerial")
            api._run_real_job(
                "p", "job-1", request,
                prepared={"translated_payload": {}},
                before_submit=lambda: _mark_submission_boundary(store, "p", "job-1"),
            )

            job = store.load_jobs("p")["job-1"]
            self.assertEqual(job["state"], "RECONCILING")
            self.assertEqual(job["submission_state"], "SUBMISSION_UNKNOWN")
            self.assertEqual(job["acceptance_submission_attempts"], 1)
            with self.assertRaisesRegex(ValueError, "不会重复提交"):
                api.retry_job("job-1")
            self.assertEqual(adapter.calls, 1)


if __name__ == "__main__":
    unittest.main()
