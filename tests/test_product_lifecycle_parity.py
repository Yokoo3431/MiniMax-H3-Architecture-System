"""CPU-only lifecycle, capability, estimate, and output-contract coverage."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from apps.architect_video_studio.mock_api.output_api import OutputAPI
from apps.architect_video_studio.mock_api.project_api import ProjectAPI
from apps.architect_video_studio.mock_api.store import StudioStore
from runtime.generation_capabilities import (
    WORKFLOW_CAPABILITIES,
    capability_matrix,
    estimate_generation_range,
    lifecycle_state,
    validate_workflow_parameters,
    weighted_progress,
)


class TestFiveWorkflowCapabilityParity(unittest.TestCase):
    def test_all_five_share_value_only_capability_contract(self):
        matrix = capability_matrix()
        self.assertEqual(set(matrix), set(WORKFLOW_CAPABILITIES))
        for workflow, item in matrix.items():
            params = validate_workflow_parameters(workflow, {
                "duration": 4, "fps": 24, "resolution": "1024x576",
                "steps": 20, "sampler_mode": "euler", "quality": "standard",
            })
            self.assertEqual(item["mode"], "FL2VA" if workflow.startswith("02_") else "I2VA")
            self.assertEqual(params["fps"], 24)
            self.assertIn("resolutions", item)

    def test_unsupported_fps_rejected_before_job_creation(self):
        with self.assertRaisesRegex(ValueError, "24 fps"):
            validate_workflow_parameters("05_Slow_Walkthrough", {"fps": 30})

    def test_shared_lifecycle_and_weighted_sampling_progress(self):
        self.assertEqual(lifecycle_state("视频采样"), "RUNNING")
        self.assertEqual(lifecycle_state("视频解码"), "DECODING")
        self.assertEqual(lifecycle_state("保存视频"), "FINALIZING")
        self.assertEqual(weighted_progress("RUNNING", 12, 50), 36.8)
        self.assertIsNone(weighted_progress("RUNNING"))

    def test_estimate_changes_with_real_parameters(self):
        history = [{"workflow": "05_Slow_Walkthrough", "state": "COMPLETED", "elapsed": 600}]
        short = estimate_generation_range(history, workflow_id="05_Slow_Walkthrough",
                                          duration=4, fps=24, resolution="1024x576", steps=50)
        long = estimate_generation_range(history, workflow_id="05_Slow_Walkthrough",
                                         duration=8, fps=24, resolution="1344x768", steps=50)
        self.assertLess(short["max_seconds"], long["min_seconds"])


class TestStudyOutputContract(unittest.TestCase):
    def test_output_copy_is_verified_and_persistable(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            store = StudioStore(root / "data")
            projects = ProjectAPI(store)
            project = projects.create_project("Output Test")
            destination = root / "chosen-output"
            projects.update_project(project["id"], {"output_directory": str(destination)})
            source = root / "runtime-video.mp4"
            source.write_bytes(b"valid test video bytes")
            job = {"id": "job-test", "workflow": "05_Slow_Walkthrough"}
            final = OutputAPI(store).copy_to_study_output(project["id"], job, source)
            self.assertTrue(final.is_file())
            self.assertEqual(final.read_bytes(), source.read_bytes())
            self.assertTrue(str(final).startswith(str(destination)))


if __name__ == "__main__":
    unittest.main()
