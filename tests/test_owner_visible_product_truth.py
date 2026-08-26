"""Owner-visible Study deletion, prompt provenance, picker and ETA contracts."""

from __future__ import annotations

import os
import tempfile
import unittest
import inspect
from pathlib import Path

from apps.architect_video_studio.mock_api.project_api import ProjectAPI
from apps.architect_video_studio.mock_api.prompt_api import PromptAPI
from apps.architect_video_studio.mock_api.store import StudioStore
from apps.architect_video_studio.mock_api.system_api import SystemAPI
from runtime.generation_capabilities import estimate_generation_range
from runtime.prompt_bridge.official_skill_adapter import (
    ArchitectIntent, OfficialSkillAdapter, ReferenceMetadata,
)


class _FailingSkill:
    def build_prompt(self, *args, **kwargs):
        raise RuntimeError("skill unavailable")


class OwnerVisibleProductTruthTests(unittest.TestCase):
    def test_completed_outputs_do_not_block_delete_and_keep_or_remove_is_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = StudioStore(Path(tmp) / "data")
            api = ProjectAPI(store)
            keep = api.create_project("Keep Output")
            keep_file = Path(tmp) / "keep" / "result.mp4"
            keep_file.parent.mkdir()
            keep_file.write_bytes(b"video")
            store.save_jobs(keep["id"], {"job-keep": {
                "id": "job-keep", "state": "COMPLETED",
                "final_output_path": str(keep_file)}})
            result = api.delete_project(keep["id"], confirm=True, delete_outputs=False)
            self.assertTrue(result["deleted"])
            self.assertTrue(keep_file.is_file())

            remove = api.create_project("Delete Output")
            remove_file = Path(tmp) / "remove" / "result.mp4"
            remove_file.parent.mkdir()
            remove_file.write_bytes(b"video")
            store.save_jobs(remove["id"], {"job-remove": {
                "id": "job-remove", "state": "COMPLETED",
                "final_output_path": str(remove_file)}})
            api.delete_project(remove["id"], confirm=True, delete_outputs=True)
            self.assertFalse(remove_file.exists())

    def test_running_job_requires_explicit_cancel_before_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = StudioStore(Path(tmp) / "data")
            api = ProjectAPI(store)
            project = api.create_project("Active")
            store.save_jobs(project["id"], {"job-active": {
                "id": "job-active", "state": "RUNNING"}})
            with self.assertRaisesRegex(ValueError, "仍有正在执行"):
                api.delete_project(project["id"], confirm=True)

    def test_official_prompt_is_input_sensitive_and_records_provenance(self):
        adapter = OfficialSkillAdapter()
        with tempfile.TemporaryDirectory() as tmp:
            ref = Path(tmp) / "reference.png"
            ref.write_bytes(b"reference")
            first = adapter.build_prompt(
                ArchitectIntent(project_type="interior", video_task="slow_walkthrough",
                                scene="slowly walk from the courtyard ramp to the pool edge and stop"),
                workflow="05_Slow_Walkthrough",
                reference=ReferenceMetadata(input_images=[str(ref)], user_approved=True),
            )
            second = adapter.build_prompt(
                ArchitectIntent(project_type="aerial", video_task="drone_aerial",
                                scene="drone rises outside the building to reveal the roof and site boundary"),
                workflow="04_Drone_Aerial",
                reference=ReferenceMetadata(input_images=[str(ref)], user_approved=True),
            )
            day = adapter.build_prompt(
                ArchitectIntent(project_type="lighting", video_task="day_night_transition",
                                scene="daylight fades into blue hour and warm interior lights appear"),
                workflow="02_Day_Night_Transition",
                reference=ReferenceMetadata(input_images=[str(ref), str(ref)], user_approved=True),
                frame_count=107,
            )
        self.assertNotEqual(first["prompt"], second["prompt"])
        self.assertNotEqual(first["prompt"], day["prompt"])
        self.assertIn("pool edge", first["prompt"])
        self.assertIn("roof", second["prompt"])
        self.assertIn("blue hour", day["prompt"])
        self.assertIn("MiniMax-AI/MiniMax-H3", first["skill_source"])

    def test_fallback_cannot_claim_official_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = StudioStore(Path(tmp) / "data")
            project = ProjectAPI(store).create_project("Fallback")
            ref_id = "ref-current"
            store.save_references(project["id"], {ref_id: {
                "id": ref_id, "state": "APPROVED", "role": "first_frame",
                "filename": "ref.png", "stored_path": None, "sha256": "HASH"}})
            project["current_reference_asset_id"] = ref_id
            store.save_project(project)
            store.save_intent(project["id"], {
                "natural_language": "slow walkthrough to the pool",
                "selected_workflow": "05_Slow_Walkthrough",
                "selected_video_task": "slow_walkthrough",
                "requires_user_confirmation": False,
            })
            result = PromptAPI(store, adapter=_FailingSkill()).generate_prompt(
                project["id"], workflow="05_Slow_Walkthrough")
            self.assertFalse(result["skill_invoked"])
            self.assertEqual(result["status"], "FALLBACK")
            self.assertIn("基础模板", result["official_skill_status"])

    def test_native_picker_override_and_eta_bootstrap(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = StudioStore(Path(tmp) / "data")
            system = SystemAPI(store)
            old = os.environ.get("ARCHITECT_VIDEO_STUDIO_PICK_FOLDER")
            os.environ["ARCHITECT_VIDEO_STUDIO_PICK_FOLDER"] = str(Path(tmp) / "chosen")
            try:
                picked = system.pick_folder()
            finally:
                if old is None:
                    os.environ.pop("ARCHITECT_VIDEO_STUDIO_PICK_FOLDER", None)
                else:
                    os.environ["ARCHITECT_VIDEO_STUDIO_PICK_FOLDER"] = old
            self.assertEqual(picked["path"], str(Path(tmp) / "chosen"))
            low = estimate_generation_range([], workflow_id="05_Slow_Walkthrough",
                                            duration=4, fps=24, resolution="1024x576", steps=25)
            high = estimate_generation_range([], workflow_id="05_Slow_Walkthrough",
                                             duration=5, fps=24, resolution="1344x768", steps=50)
            self.assertIsNotNone(low["min_seconds"])
            self.assertGreater(high["min_seconds"], low["min_seconds"])
            self.assertGreater(high["evidence_count"], 0)
            for workflow in ("01_Exterior_Hero", "02_Day_Night_Transition",
                             "03_Material_Detail", "04_Drone_Aerial",
                             "05_Slow_Walkthrough"):
                estimate = estimate_generation_range(
                    [], workflow_id=workflow, duration=4, fps=24,
                    resolution="1024x576", steps=50)
                self.assertIsNotNone(estimate["min_seconds"], workflow)

    def test_picker_bridge_and_frontend_cancel_are_null_safe(self):
        source = inspect.getsource(SystemAPI.pick_folder)
        frontend = (Path(__file__).resolve().parents[1] /
                    "apps" / "architect_video_studio" / "frontend" /
                    "js" / "workspace.js").read_text(encoding="utf-8")
        self.assertIn("FolderBrowserDialog", source)
        self.assertIn("!picked || picked.cancelled", frontend)


if __name__ == "__main__":
    unittest.main()
