"""RC3.3 PATCH2.6-B - Architect Video Studio local UI prototype tests.

Covers the 8 required items plus state machine guards:
1. Project creation
2. Reference approval
3. Intent classification display
4. Prompt preview readonly
5. Invalid state transition blocked
6. Generate disabled without approval
7. Provenance generation
8. Output package structure

No GPU / ComfyUI / model interaction. Prompt generation reuses the frozen
OfficialSkillAdapter read-only.
"""

import base64
import json
import sys
import tempfile
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
from apps.architect_video_studio.state_machine.machine import (  # noqa: E402
    IllegalTransitionError,
    JobStateMachine,
    ProjectStateMachine,
)


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


class FakeClock:
    def __init__(self, value: float = 0.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


class PrototypeHarness:
    """Builds a fully wired prototype environment over a temp data root."""

    def __init__(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = StudioStore(Path(self.tmp.name))
        self.project_api = ProjectAPI(self.store)
        self.reference_api = ReferenceAPI(self.store)
        self.intent_api = IntentAPI(self.store)
        self.prompt_api = PromptAPI(self.store)
        self.clock = FakeClock(0.0)
        self.output_api = OutputAPI(self.store)
        self.job_api = JobAPI(self.store, output_api=self.output_api, clock=self.clock)

    def close(self) -> None:
        self.tmp.cleanup()

    def full_project(self, name: str = "测试项目") -> str:
        project = self.project_api.create_project(name, "exterior", "方案")
        ref = self.reference_api.upload_reference(
            project["id"], "ref.png", role="first_frame",
            data_base64=tiny_png_b64())
        self.reference_api.approve_reference(project["id"], ref["id"])
        self.intent_api.analyze_intent(project["id"], "做一个入口缓慢推进的视频，突出建筑尺度感")
        self.prompt_api.generate_prompt(project["id"])
        return project["id"]


class TestProjectCreation(unittest.TestCase):
    def test_create_and_get_project(self):
        h = PrototypeHarness()
        try:
            p = h.project_api.create_project("杭州办公园区方案", "exterior", "方案")
            self.assertEqual(p["state"], "CREATED")
            self.assertEqual(p["name"], "杭州办公园区方案")
            got = h.project_api.get_project(p["id"])
            self.assertEqual(got["id"], p["id"])
            self.assertIn(p["id"], [x["id"] for x in h.project_api.list_projects()])
            audit = h.store.load_audit(p["id"])
            self.assertTrue(any(a["event"] == "create_project" for a in audit))
        finally:
            h.close()

    def test_create_requires_name(self):
        h = PrototypeHarness()
        try:
            with self.assertRaises(ValueError):
                h.project_api.create_project("   ")
        finally:
            h.close()


class TestReferenceApproval(unittest.TestCase):
    def test_approve_and_reject_flow(self):
        h = PrototypeHarness()
        try:
            pid = h.project_api.create_project("A")["id"]
            ref = h.reference_api.upload_reference(pid, "a.png", data_base64=tiny_png_b64())
            ref2 = h.reference_api.upload_reference(pid, "b.png", data_base64=tiny_png_b64())
            self.assertEqual(ref["state"], "PENDING")
            self.assertEqual(h.project_api.get_project(pid)["state"], "REFERENCE_PENDING")

            approved = h.reference_api.approve_reference(pid, ref["id"])
            self.assertEqual(approved["state"], "APPROVED")
            self.assertEqual(h.project_api.get_project(pid)["state"], "REFERENCE_APPROVED")

            rejected = h.reference_api.reject_reference(pid, ref2["id"], reason="not representative")
            self.assertEqual(rejected["state"], "REJECTED")
            self.assertEqual(h.project_api.get_project(pid)["state"], "REFERENCE_APPROVED")
        finally:
            h.close()

    def test_approve_twice_rejected(self):
        h = PrototypeHarness()
        try:
            pid = h.project_api.create_project("A")["id"]
            ref = h.reference_api.upload_reference(pid, "a.png", data_base64=tiny_png_b64())
            h.reference_api.approve_reference(pid, ref["id"])
            with self.assertRaises(ValueError):
                h.reference_api.approve_reference(pid, ref["id"])
        finally:
            h.close()


class TestIntentClassificationDisplay(unittest.TestCase):
    def test_intent_card_fields(self):
        h = PrototypeHarness()
        try:
            pid = h.full_project()
            intent = h.store.load_intent(pid)
            self.assertEqual(intent["selected_workflow"], "05_Slow_Walkthrough")
            self.assertGreaterEqual(intent["confidence"], 0.6)
            self.assertFalse(intent["requires_user_confirmation"])
            for key in ("natural_language", "reason", "candidate_workflows"):
                self.assertIn(key, intent)
        finally:
            h.close()

    def test_ambiguous_intent_requires_confirmation(self):
        h = PrototypeHarness()
        try:
            pid = h.project_api.create_project("B")["id"]
            ref = h.reference_api.upload_reference(pid, "a.png", data_base64=tiny_png_b64())
            h.reference_api.approve_reference(pid, ref["id"])
            intent = h.intent_api.analyze_intent(pid, "夜景漫游")
            self.assertTrue(intent["requires_user_confirmation"])
            self.assertEqual(h.project_api.get_project(pid)["state"], "PROMPT_NEEDS_CONFIRMATION")
            candidates = intent["candidate_workflows"]
            self.assertGreaterEqual(len(candidates), 2)
            h.intent_api.confirm_workflow(pid, candidates[0])
            self.assertEqual(h.project_api.get_project(pid)["state"], "PROMPT_REVIEW")
        finally:
            h.close()


class TestPromptPreviewReadOnly(unittest.TestCase):
    def test_prompt_official_structure_and_readonly(self):
        h = PrototypeHarness()
        try:
            pid = h.full_project()
            record = h.prompt_api.get_prompt(pid)
            self.assertTrue(record["verified"]["pass"])
            self.assertEqual(record["non_diegetic_music"], "N/A")
            self.assertIn("provenance", record)
            self.assertTrue(record["prompt"].startswith(
                "For the target video, at 0.00 seconds into the target video"))

            # Read-only: mutating the returned dict must not touch the store,
            # and no update endpoint exists on the API.
            record["prompt"] = "HACKED"
            again = h.prompt_api.get_prompt(pid)
            self.assertNotEqual(again["prompt"], "HACKED")
            self.assertFalse(hasattr(h.prompt_api, "update_prompt"))
            self.assertFalse(hasattr(h.prompt_api, "edit_prompt"))
        finally:
            h.close()


class TestStateMachineGuards(unittest.TestCase):
    def test_allowed_reference_pending_to_approved(self):
        m = ProjectStateMachine("REFERENCE_PENDING")
        m.transition("approve", actor="architect")
        self.assertEqual(m.state, "REFERENCE_APPROVED")

    def test_blocked_reference_pending_to_gpu_running(self):
        m = ProjectStateMachine("REFERENCE_PENDING")
        with self.assertRaises(IllegalTransitionError):
            m.transition("confirm_generate")

    def test_blocked_created_to_gpu_running(self):
        m = ProjectStateMachine("CREATED")
        with self.assertRaises(IllegalTransitionError):
            m.transition("confirm_generate")

    def test_project_machine_full_path(self):
        m = ProjectStateMachine()
        path = [
            ("upload_reference", "REFERENCE_PENDING"),
            ("approve", "REFERENCE_APPROVED"),
            ("analyze_intent", "INTENT_ANALYSIS"),
            ("intent_high_confidence", "PROMPT_REVIEW"),
            ("show_generation_panel", "USER_CONFIRM"),
            ("confirm_generate", "GPU_RUNNING"),
            ("succeeded", "QUALITY_CHECK"),
            ("quality_pass", "COMPLETED"),
        ]
        for event, target in path:
            self.assertEqual(m.transition(event, actor="test"), target)

    def test_job_machine_no_auto_retry_from_failed(self):
        m = JobStateMachine("GPU_FAILED")
        self.assertEqual(m.ALLOWED.get("GPU_FAILED"), {})
        with self.assertRaises(IllegalTransitionError):
            m.transition("progress")

    def test_api_rejects_intent_without_approval(self):
        h = PrototypeHarness()
        try:
            pid = h.project_api.create_project("A")["id"]
            with self.assertRaises(ValueError):
                h.intent_api.analyze_intent(pid, "做一个入口缓慢推进的视频")
        finally:
            h.close()


class TestGenerateGateWithoutApproval(unittest.TestCase):
    def test_submit_blocked_when_no_approved_reference(self):
        h = PrototypeHarness()
        try:
            pid = h.full_project()
            # Revoke approval at store level (simulates a bypass attempt).
            refs = h.store.load_references(pid)
            for ref in refs.values():
                ref["state"] = "PENDING"
            h.store.save_references(pid, refs)
            with self.assertRaises(ValueError) as ctx:
                h.job_api.submit_job(pid, risk_reviewed=True)
            self.assertIn("REFERENCE_CONFIGURATION_ERROR", str(ctx.exception))
        finally:
            h.close()

    def test_submit_blocked_without_risk_review(self):
        h = PrototypeHarness()
        try:
            pid = h.full_project()
            with self.assertRaises(ValueError) as ctx:
                h.job_api.submit_job(pid, risk_reviewed=False)
            self.assertIn("Risk Review Gate", str(ctx.exception))
        finally:
            h.close()

    def test_prompt_blocked_without_approved_reference(self):
        h = PrototypeHarness()
        try:
            pid = h.project_api.create_project("A")["id"]
            ref = h.reference_api.upload_reference(pid, "a.png", data_base64=tiny_png_b64())
            h.reference_api.approve_reference(pid, ref["id"])
            h.intent_api.analyze_intent(pid, "做一个入口缓慢推进的视频，突出建筑尺度感")
            refs = h.store.load_references(pid)
            refs[ref["id"]]["state"] = "PENDING"
            h.store.save_references(pid, refs)
            with self.assertRaises(ValueError) as ctx:
                h.prompt_api.generate_prompt(pid)
            self.assertIn("no approved reference", str(ctx.exception))
        finally:
            h.close()


class TestProvenanceAndAudit(unittest.TestCase):
    def test_provenance_generation(self):
        h = PrototypeHarness()
        try:
            pid = h.full_project()
            job = h.job_api.submit_job(pid, seed=7, risk_reviewed=True)
            h.clock.value = 999.0
            job = h.job_api.get_job(job["id"])
            self.assertEqual(job["state"], "COMPLETED")
            prov_path = h.store.package_dir(pid) / "report" / "provenance.json"
            self.assertTrue(prov_path.is_file())
            prov = json.loads(prov_path.read_text(encoding="utf-8"))
            for key in ("workflow_id", "raw_architect_intent", "user_reference_hashes",
                        "user_reference_approved", "generated_prompt_hash",
                        "official_skill_revision"):
                self.assertIn(key, prov, key)
            self.assertTrue(prov["user_reference_approved"])
            prompt = h.prompt_api.get_prompt(pid)
            self.assertEqual(prov["generated_prompt_hash"], prompt["prompt_hash"])
            self.assertNotIn("password", json.dumps(prov).lower())
        finally:
            h.close()

    def test_audit_log_traceability(self):
        h = PrototypeHarness()
        try:
            pid = h.full_project()
            job = h.job_api.submit_job(pid, risk_reviewed=True)
            h.clock.value = 999.0
            h.job_api.get_job(job["id"])
            audit = h.store.load_audit(pid)
            events = [a["event"] for a in audit]
            for expected in ("create_project", "upload_reference", "approve_reference",
                             "analyze_intent", "generate_prompt", "confirm_generate",
                             "job_completed"):
                self.assertIn(expected, events, expected)
            for a in audit:
                self.assertIn("at", a)
                self.assertIn("from", a)
                self.assertIn("to", a)
        finally:
            h.close()


class TestOutputPackageStructure(unittest.TestCase):
    def test_package_layout_and_files(self):
        h = PrototypeHarness()
        try:
            pid = h.full_project()
            job = h.job_api.submit_job(pid, risk_reviewed=True)
            h.clock.value = 999.0
            job = h.job_api.get_job(job["id"])
            self.assertEqual(job["state"], "COMPLETED")

            pkg = h.store.package_dir(pid)
            for sub in ("input", "workflow", "prompt", "output", "report"):
                self.assertTrue((pkg / sub).is_dir(), sub)
            self.assertTrue((pkg / "input" / "references.json").is_file())
            self.assertTrue((pkg / "prompt" / "prompt.json").is_file())
            self.assertTrue((pkg / "output" / "output.mp4").is_file())
            self.assertTrue((pkg / "report" / "provenance.json").is_file())
            self.assertTrue((pkg / "report" / "runtime_info.json").is_file())
            self.assertTrue((pkg / "report" / "report.json").is_file())
            workflow_files = list((pkg / "workflow").iterdir())
            self.assertTrue(any(f.suffix == ".json" for f in workflow_files),
                            "frozen workflow JSON should be copied")

            result = h.output_api.get_result(job["id"])
            self.assertEqual(result["workflow"], "05_Slow_Walkthrough")
            self.assertIn("output.mp4", result["structure"]["output"])
            runtime = json.loads((pkg / "report" / "runtime_info.json").read_text(encoding="utf-8"))
            self.assertFalse(runtime["comfyui_invoked"])
            self.assertIn("MOCK_PROTOTYPE", runtime["runtime"])
        finally:
            h.close()

    def test_result_unavailable_until_completed(self):
        h = PrototypeHarness()
        try:
            pid = h.full_project()
            job = h.job_api.submit_job(pid, risk_reviewed=True)
            with self.assertRaises(ValueError):
                h.output_api.get_result(job["id"])
        finally:
            h.close()


if __name__ == "__main__":
    unittest.main()
