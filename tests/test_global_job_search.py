"""Regression tests for safe cross-project Job discovery."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from apps.architect_video_studio.mock_api.job_api import JobAPI  # noqa: E402
from apps.architect_video_studio.mock_api.server import _make_handler  # noqa: E402


class SearchStore:
    def __init__(self):
        self.projects = [
            {"id": "p-old", "name": "Test 4"},
            {"id": "p-new", "name": "A5 validation"},
        ]
        self.jobs = {
            "p-old": {
                "job-legacy-42": {
                    "id": "job-legacy-42", "workflow": "04_Drone_Aerial",
                    "state": "COMPLETED", "seed": 42,
                    "created_at": "2026-09-30T17:21:55+08:00",
                    "runtime_target": "experimental", "runtime": "native",
                    "execution_trace": {"runtime_identity": {
                        "runtime_id": "experimental-h3-8190",
                        "runtime_role": "experimental"}},
                    "prompt": "MUST_NOT_BE_RETURNED",
                    "output_path": "MUST_NOT_BE_RETURNED.mp4",
                    "prompt_id": "private-prompt-id",
                },
            },
            "p-new": {
                "job-recent-43": {
                    "id": "job-recent-43", "workflow": "01_Exterior_Hero",
                    "state": "FAILED", "seed": 43,
                    "created_at": "2026-10-03T10:00:00+08:00",
                    "runtime_target": "production", "runtime": "native",
                },
            },
        }

    def list_projects(self):
        return list(self.projects)

    def load_jobs(self, project_id):
        return dict(self.jobs.get(project_id, {}))


class TestGlobalJobSearch(unittest.TestCase):
    def setUp(self):
        self.store = SearchStore()
        self.api = JobAPI.__new__(JobAPI)
        self.api.store = self.store

    def test_cross_project_search_returns_safe_allowlisted_rows(self):
        result = self.api.search_jobs(query="job-legacy-42")
        self.assertEqual(result["total"], 1)
        item = result["items"][0]
        self.assertEqual(item["project_id"], "p-old")
        self.assertEqual(item["project_name"], "Test 4")
        self.assertEqual(item["runtime_role"], "experimental")
        self.assertNotIn("prompt", item)
        self.assertNotIn("prompt_id", item)
        self.assertNotIn("output_path", item)

    def test_state_project_runtime_date_and_pagination_filters(self):
        result = self.api.search_jobs(
            project_id="p-old", state="completed", runtime_role="experimental",
            created_from="2026-09-30", created_to="2026-09-30", limit=1, offset=0)
        self.assertEqual([item["id"] for item in result["items"]], ["job-legacy-42"])
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["limit"], 1)
        self.assertEqual(result["offset"], 0)

    def test_active_filter_covers_native_lifecycle_states(self):
        result = self.api.search_jobs(state="ACTIVE")
        self.assertEqual(result["total"], 0)
        self.store.jobs["p-new"]["job-running"] = {
            "id": "job-running", "workflow": "04_Drone_Aerial",
            "state": "SAMPLING", "created_at": "2026-10-04T10:00:00+08:00",
            "runtime_target": "production", "runtime": "native",
        }
        result = self.api.search_jobs(state="ACTIVE")
        self.assertEqual([item["id"] for item in result["items"]], ["job-running"])

    def test_search_does_not_enter_memory_release_or_runtime_paths(self):
        self.api.maybe_release_idle_memory = lambda: self.fail("unexpected runtime side effect")
        result = self.api.search_jobs(limit=1)
        self.assertEqual(result["total"], 2)
        self.assertEqual(len(result["items"]), 1)

    def test_invalid_date_and_unknown_project_fail_closed(self):
        with self.assertRaises(ValueError):
            self.api.search_jobs(created_from="2026-02-31")
        with self.assertRaises(KeyError):
            self.api.search_jobs(project_id="missing")

    def test_http_route_parses_filters_and_returns_search_envelope(self):
        class RouteAPI:
            def search_jobs(self, **kwargs):
                return {"items": [], "total": 0, "limit": 50, "offset": 0,
                        "received": kwargs}

        handler_type = _make_handler(object(), {"job": RouteAPI()})
        handler = handler_type.__new__(handler_type)
        captured = []
        handler._ok = lambda data: captured.append(data)
        handler._route_api(
            "GET", "/api/jobs/search", {},
            "q=job-1&runtime_role=experimental&limit=20&offset=40")
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0]["received"]["query"], "job-1")
        self.assertEqual(captured[0]["received"]["runtime_role"], "experimental")
        self.assertEqual(captured[0]["received"]["limit"], "20")
        self.assertEqual(captured[0]["received"]["offset"], "40")


class TestDiscoveryUiContract(unittest.TestCase):
    def test_jobs_page_defaults_to_cross_project_search_and_a9_has_own_section(self):
        frontend = ROOT / "apps/architect_video_studio/frontend"
        jobs_html = (frontend / "jobs.html").read_text(encoding="utf-8")
        jobs_js = (frontend / "js/jobs.js").read_text(encoding="utf-8")
        output_html = (frontend / "output.html").read_text(encoding="utf-8")
        output_js = (frontend / "js/output.js").read_text(encoding="utf-8")
        self.assertIn("/api/jobs/search?", jobs_js)
        self.assertIn("searchJobsFromProjectApis(params)", jobs_js)
        self.assertIn("unknown api route", jobs_js)
        self.assertIn("job not found: search", jobs_js)
        self.assertIn("const identity = job.execution_trace?.runtime_identity || {}", jobs_js)
        self.assertIn('id="job-search"', jobs_html)
        self.assertIn("全部项目", jobs_js)
        self.assertIn("function updateProjectHint()", jobs_js)
        self.assertIn("当前范围：", jobs_js)
        self.assertIn("按当前范围搜索", jobs_html)
        self.assertNotIn("默认跨项目显示最近任务", jobs_js)
        self.assertIn('id="long-form-results"', output_html)
        self.assertIn("assembly-results-items", output_js)
        self.assertIn("sequence_id: queue.director_sequence_id", output_js)
        self.assertIn("Sequence ${esc(item.sequence_id", output_js)
        self.assertIn("非 AI 超分", output_html)
        self.assertIn("非 AI 超分", output_js)


if __name__ == "__main__":
    unittest.main()
