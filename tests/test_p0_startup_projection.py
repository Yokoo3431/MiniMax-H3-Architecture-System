import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from apps.architect_video_studio.mock_api.store import StudioStore
from apps.architect_video_studio.mock_api.study_state import (
    build_study_state,
    converge_stale_reconciliation,
)
from runtime.h3_prompt_engine import discover_providers


from apps.architect_video_studio.mock_api.job_api import _decorate_job

class TestP0StartupProjection(unittest.TestCase):
    def test_submission_lost_is_terminal_and_not_presented_as_running(self):
        decorated = _decorate_job({
            "id": "job-lost", "state": "SUBMISSION_LOST",
            "progress": 0.0, "current_stage": "准备参考图",
            "failure_code": "COMFY_COMMUNICATION_TIMEOUT",
            "user_message": "任务提交未被 ComfyUI 确认，可重新生成",
        })
        self.assertEqual(decorated["status_label"], "提交未确认")
        self.assertEqual(decorated["state"], "SUBMISSION_LOST")
        self.assertNotEqual(decorated["status_label"], "生成中")

    def test_old_unknown_submission_converges_and_does_not_stay_active(self):
        with tempfile.TemporaryDirectory() as directory:
            store = StudioStore(Path(directory))
            project_id = "proj-p0"
            store.save_project({"id": project_id, "state": "USER_CONFIRM"})
            old = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
            store.save_jobs(project_id, {"job-p0": {
                "id": "job-p0", "state": "RECONCILING", "created_at": old,
                "prompt_id": None, "stages": ["RECONCILING"],
            }})
            state = build_study_state(store, project_id)
            self.assertEqual(state["active_job_id"], None)
            self.assertEqual(store.load_jobs(project_id)["job-p0"]["state"], "SUBMISSION_LOST")

    def test_fresh_unknown_submission_remains_reconciling(self):
        with tempfile.TemporaryDirectory() as directory:
            store = StudioStore(Path(directory))
            project_id = "proj-p0-fresh"
            store.save_project({"id": project_id, "state": "USER_CONFIRM"})
            store.save_jobs(project_id, {"job-p0": {
                "id": "job-p0", "state": "RECONCILING",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "prompt_id": None, "stages": ["RECONCILING"],
            }})
            self.assertTrue(converge_stale_reconciliation(store, project_id) is False)
            self.assertEqual(store.load_jobs(project_id)["job-p0"]["state"], "RECONCILING")

    def test_agy_is_discovered_from_localappdata(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "agy" / "bin" / "agy.exe"
            executable.parent.mkdir(parents=True)
            executable.write_bytes(b"test")
            with mock.patch.dict("os.environ", {"LOCALAPPDATA": directory}, clear=False), \
                    mock.patch("runtime.h3_prompt_engine.shutil.which", return_value=None):
                found = [item for item in discover_providers()
                         if item.get("provider") == "ANTIGRAVITY"]
            self.assertEqual(found[0]["executable"], str(executable))


if __name__ == "__main__":
    unittest.main()
