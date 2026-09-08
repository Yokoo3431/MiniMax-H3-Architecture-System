import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from apps.architect_video_studio.mock_api.job_api import JobAPI
from apps.architect_video_studio.mock_api.store import StudioStore
from runtime.adapters.comfyui_client import ComfyUIClient
from runtime.adapters.native_runtime_adapter import NativeRuntimeAdapter
from runtime.product_hardening import map_comfy_event


class FakeStore:
    def __init__(self, jobs=None):
        self.jobs = jobs or {}
    def timestamp(self):
        return "2026-08-31T00:00:00+08:00"
    def list_projects(self):
        return [{"id": "p"}]
    def load_jobs(self, project_id):
        return self.jobs.get(project_id, {})


class FakeClient:
    def __init__(self, queue=None):
        self.queue = queue or {"queue_running": [], "queue_pending": []}
        self.releases = 0
    def get_queue(self):
        return self.queue
    def free_memory(self):
        self.releases += 1
        return {}
    def health_check(self):
        return {"available": True}


class FakeAdapter:
    def __init__(self, client):
        self.client = client


class SubmitClient:
    def __init__(self):
        self.kwargs = None
    def submit_workflow(self, payload, **kwargs):
        self.kwargs = kwargs
        return {"prompt_id": "prompt-1"}


class RCTelemetryPolishTests(unittest.TestCase):
    def test_websocket_progress_is_strict_and_safe(self):
        event = ComfyUIClient.normalize_websocket_event(json.dumps({
            "type": "progress",
            "data": {"prompt_id": "p1", "value": 12, "max": 50, "node": "11"}
        }), "p1")
        self.assertEqual(event["step"], 12)
        self.assertEqual(event["total_steps"], 50)
        self.assertEqual(event["progress"], 0.24)
        self.assertIsNone(ComfyUIClient.normalize_websocket_event(
            {"type": "progress", "data": {"prompt_id": "other", "value": 1, "max": 2}}, "p1"))

    def test_progress_state_uses_running_node(self):
        event = ComfyUIClient.normalize_websocket_event({
            "type": "progress_state",
            "data": {"prompt_id": "p1", "nodes": {
                "11": {"state": "running", "value": 7, "max": 20, "display_node_id": "sampler"}
            }}
        }, "p1")
        self.assertEqual(event["node_id"], "sampler")
        self.assertEqual(event["step"], 7)

    def test_event_mapping_preserves_prompt_correlation_and_percentage(self):
        normalized = ComfyUIClient.normalize_websocket_event({
            "type": "progress",
            "data": {"prompt_id": "p1", "value": 12, "max": 50,
                     "node": "11"},
        }, "p1")
        mapped = map_comfy_event(normalized)
        self.assertEqual(mapped["prompt_id"], "p1")
        self.assertEqual(mapped["node_id"], "11")
        self.assertEqual(mapped["progress"], 24.0)
        self.assertIsNone(map_comfy_event({
            "type": "progress", "data": {"prompt_id": "p1", "progress": 0.5}
        })["progress"])

    def test_managed_client_reuses_one_service_client_id(self):
        client = ComfyUIClient()
        first = client.client_id
        self.assertTrue(first)
        self.assertEqual(client.client_id, first)
        self.assertIn(first, client._websocket_url(first))

    def test_websocket_disconnect_is_reported_as_telemetry_only(self):
        client = ComfyUIClient()
        events = []
        stop = threading.Event()
        with mock.patch.object(client, "_connect_websocket",
                               side_effect=ConnectionError("closed")):
            client.observe_websocket("prompt-1", client.client_id, events.append,
                                     stop, max_reconnects=0)
        self.assertEqual(events[0]["type"], "telemetry_degraded")
        self.assertEqual(events[0]["prompt_id"], "prompt-1")

    def test_native_submit_persists_one_client_id(self):
        client = SubmitClient()
        adapter = NativeRuntimeAdapter(client=client)
        request = {"translated_payload": {}, "avs_job_id": "job-1",
                   "execution_workflow_sha256": "sha"}
        self.assertEqual(adapter.submit(request), "prompt-1")
        self.assertEqual(request["client_id"], client.kwargs["client_id"])
        self.assertTrue(request["client_id"])

    def test_idle_release_requires_empty_queue_and_threshold(self):
        now = [100.0]
        client = FakeClient()
        api = JobAPI(FakeStore({"p": {}}), output_api=object(),
                     runtime_adapter=FakeAdapter(client), clock=lambda: now[0])
        self.assertFalse(api.maybe_release_idle_memory()["released"])
        now[0] = 700.0
        self.assertTrue(api.maybe_release_idle_memory()["released"])
        self.assertEqual(client.releases, 1)

    def test_idle_release_is_forbidden_with_active_job(self):
        client = FakeClient()
        api = JobAPI(FakeStore({"p": {"job": {"id": "job", "state": "RECONCILING"}}}),
                     output_api=object(), runtime_adapter=FakeAdapter(client),
                     clock=lambda: 100.0)
        result = api.maybe_release_idle_memory()
        self.assertEqual(result["reason"], "active_job")
        self.assertEqual(client.releases, 0)

    def test_frontend_retains_historical_eta_range(self):
        workspace = Path("apps/architect_video_studio/frontend/js/workspace.js").read_text(encoding="utf-8")
        jobs = Path("apps/architect_video_studio/frontend/js/jobs.js").read_text(encoding="utf-8")
        self.assertIn("formatEtaRange", workspace)
        self.assertIn("预计总耗时", workspace)
        self.assertIn("formatEtaRange", jobs)
        self.assertIn("预计总耗时", jobs)

    def test_history_terminal_truth_wins_over_stale_queue(self):
        client = ComfyUIClient()
        history = {"p1": {"status": {"status_str": "success", "completed": True}}}
        queue = {"queue_running": [[1, "p1", {}]], "queue_pending": []}
        with mock.patch.object(client, "list_history", return_value=history), \
                mock.patch.object(client, "get_queue", return_value=queue):
            result = client.reconcile_prompt(prompt_id="p1")
        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(result["source"], "history")

    def test_queue_is_active_fallback_after_history_miss(self):
        client = ComfyUIClient()
        with mock.patch.object(client, "list_history", return_value={}), \
                mock.patch.object(client, "get_queue", return_value={
                    "queue_running": [[1, "prompt-1", {}]], "queue_pending": []}):
            result = client.reconcile_prompt(prompt_id="prompt-1")
        self.assertEqual(result["status"], "RUNNING")
        self.assertEqual(result["source"], "queue")


from apps.architect_video_studio.mock_api.job_state import (
    is_job_active,
    is_job_recoverable,
    is_job_terminal,
    normalize_terminal_record,
    terminal_elapsed_seconds,
)


class TestCanonicalJobStateMatrix(unittest.TestCase):
    def test_six_state_matrix_has_one_active_truth(self):
        states = {
            "COMPLETED": {"terminal": True, "active": False, "recoverable": False},
            "FAILED": {"terminal": True, "active": False, "recoverable": False},
            "CANCELLED": {"terminal": True, "active": False, "recoverable": False},
            "SUBMISSION_LOST": {"terminal": True, "active": False, "recoverable": False},
            "RUNNING": {"terminal": False, "active": True, "recoverable": True},
            "RECONCILING": {"terminal": False, "active": True, "recoverable": True},
        }
        for state, expected in states.items():
            job = {"id": f"job-{state.lower()}", "state": state}
            if state == "RECONCILING":
                job["created_at"] = 100.0
                self.assertFalse(is_job_recoverable(
                    {**job, "created_at": -1000.0}, now=100.0))
            self.assertEqual(is_job_terminal(job), expected["terminal"], state)
            self.assertEqual(is_job_active(job, now=100.0), expected["active"], state)
            self.assertEqual(
                is_job_recoverable(job, now=100.0), expected["recoverable"], state)

    def test_terminal_elapsed_is_frozen_and_missing_finished_at_is_normalized(self):
        completed = {
            "id": "job-completed",
            "state": "COMPLETED",
            "started_at": 100.0,
            "finished_at": 145.0,
        }
        self.assertEqual(terminal_elapsed_seconds(completed), 45.0)
        self.assertFalse(is_job_active(completed))

        failed = {
            "id": "job-failed",
            "state": "FAILED",
            "started_at": 100.0,
        }
        changed = normalize_terminal_record(failed, "2026-08-31T00:00:02+00:00")
        self.assertTrue(changed)
        self.assertTrue(failed["finished_at"])
        self.assertFalse(failed["active"])
        self.assertFalse(failed["is_active"])
        self.assertEqual(failed["elapsed"], terminal_elapsed_seconds(failed))
        self.assertFalse(is_job_active(failed))

    def test_terminal_states_are_delete_eligible_and_active_states_are_blocked(self):
        from apps.architect_video_studio.mock_api.project_api import ProjectAPI
        from apps.architect_video_studio.mock_api.store import StudioStore

        with tempfile.TemporaryDirectory() as tmp:
            store = StudioStore(Path(tmp) / "data")
            api = ProjectAPI(store)
            for state in ("COMPLETED", "FAILED", "CANCELLED", "SUBMISSION_LOST"):
                project = api.create_project(f"Delete {state}")
                store.save_jobs(project["id"], {
                    "job": {"id": "job", "state": state}
                })
                result = api.delete_project(
                    project["id"], confirm=True, delete_outputs=False)
                self.assertTrue(result["deleted"], state)

            active = api.create_project("Delete RUNNING")
            store.save_jobs(active["id"], {
                "job": {"id": "job", "state": "RUNNING"}
            })
            with self.assertRaises(ValueError):
                api.delete_project(active["id"], confirm=True)

    def test_frontend_consumes_backend_state_flags_instead_of_local_lists(self):
        workspace = Path(
            "apps/architect_video_studio/frontend/js/workspace.js"
        ).read_text(encoding="utf-8")
        jobs = Path(
            "apps/architect_video_studio/frontend/js/jobs.js"
        ).read_text(encoding="utf-8")
        for source in (workspace, jobs):
            self.assertIn("jobIsActive", source)
            self.assertIn("jobIsTerminal", source)
            self.assertNotIn("const TERMINAL_JOB_STATES", source)
            self.assertNotIn("const ACTIVE_JOB_STATES", source)

    def test_late_observer_events_cannot_resurrect_terminal_jobs(self):
        with tempfile.TemporaryDirectory() as temp:
            store = StudioStore(Path(temp))
            store.project_dir("p").mkdir(parents=True, exist_ok=True)
            for terminal in ("COMPLETED", "FAILED"):
                store.save_jobs("p", {"j": {
                    "id": "j", "project_id": "p", "state": terminal,
                    "prompt_id": "p1", "progress": 100.0 if terminal == "COMPLETED" else 42.0,
                    "current_stage": "保存视频" if terminal == "COMPLETED" else "生成失败",
                    "started_at": 0, "finished_at": "2026-08-31T00:00:00+08:00",
                    "lifecycle_state": "SUCCEEDED" if terminal == "COMPLETED" else "FAILED",
                }})
                api = JobAPI(store, clock=lambda: 10)
                api._record_progress("p", "j", {
                    "type": "executing", "prompt_id": "p1",
                    "stage": "视频采样", "step": 1, "total_steps": 50,
                })
                job = store.load_jobs("p")["j"]
                self.assertEqual(job["state"], terminal)
                self.assertEqual(job["progress"], 100.0 if terminal == "COMPLETED" else 42.0)

    def test_telemetry_disconnect_only_records_observation(self):
        with tempfile.TemporaryDirectory() as temp:
            store = StudioStore(Path(temp))
            store.project_dir("p").mkdir(parents=True, exist_ok=True)
            store.save_jobs("p", {"j": {
                "id": "j", "project_id": "p", "state": "SAMPLING",
                "prompt_id": "p1", "progress": 36.8,
                "current_stage": "视频采样", "started_at": 0,
            }})
            api = JobAPI(store, clock=lambda: 10)
            api._record_progress("p", "j", {
                "type": "telemetry_degraded", "prompt_id": "p1",
                "message": "websocket unavailable",
            })
            job = store.load_jobs("p")["j"]
            self.assertEqual(job["state"], "SAMPLING")
            self.assertEqual(job["progress"], 36.8)
            self.assertEqual(job["observation_trace"][-1]["event_type"], "telemetry_degraded")


if __name__ == "__main__":
    unittest.main()
