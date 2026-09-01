import json
import tempfile
import threading
import unittest
from pathlib import Path

from apps.architect_video_studio.mock_api.job_api import JobAPI
from runtime.adapters.comfyui_client import ComfyUIClient
from runtime.adapters.native_runtime_adapter import NativeRuntimeAdapter


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


if __name__ == "__main__":
    unittest.main()
