"""Synthetic demo seeding must not ingest owner media or use shared app data."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from apps.architect_video_studio.mock_api import seed_demo as seed_demo_module  # noqa: E402
from apps.architect_video_studio.mock_api.store import StudioStore  # noqa: E402


class TestSyntheticDemoSeed(unittest.TestCase):
    def test_data_directory_must_be_explicit(self):
        with self.assertRaises(TypeError):
            seed_demo_module.seed_demo()  # type: ignore[call-arg]

    def test_only_tracked_synthetic_samples_are_read(self):
        samples = ROOT / "samples"
        self.assertEqual(
            seed_demo_module._read_image("01_Exterior_Hero.png"),
            (samples / "01_Exterior_Hero.png").read_bytes(),
        )
        self.assertEqual(
            seed_demo_module._read_image("05_Slow_Walkthrough.png"),
            (samples / "05_Slow_Walkthrough.png").read_bytes(),
        )
        # Unknown names use the deterministic in-memory placeholder rather
        # than probing any sibling/owner reference directory.
        self.assertTrue(
            seed_demo_module._read_image("03_Material_Detail.jpg").startswith(
                b"\x89PNG\r\n\x1a\n"
            )
        )

    def test_demo_projects_and_media_stay_under_explicit_temp_root(self):
        with tempfile.TemporaryDirectory(prefix="avs-demo-seed-test-") as temp:
            root = Path(temp).resolve()
            ids = seed_demo_module.seed_demo(root)
            store = StudioStore(root)

            self.assertEqual(set(ids), {
                "project_a", "job_a", "project_b", "project_c", "project_d",
            })
            for project_id in (
                ids["project_a"], ids["project_b"], ids["project_c"],
                ids["project_d"],
            ):
                project = store.load_project(project_id)
                self.assertEqual(
                    project["output_directory"],
                    "仅用于本地演示（不写入用户目录）",
                )
                self.assertFalse(Path(project["output_directory"]).is_absolute())
                for reference in store.load_references(project_id).values():
                    stored_path = Path(reference["stored_path"]).resolve()
                    self.assertTrue(stored_path.is_relative_to(root))
                    self.assertTrue(stored_path.is_file())


if __name__ == "__main__":
    unittest.main()
