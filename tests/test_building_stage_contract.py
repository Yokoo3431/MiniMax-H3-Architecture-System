"""New Study building-stage contract tests; no network, media, or GPU."""

import tempfile
import unittest
from pathlib import Path

from apps.architect_video_studio.mock_api.project_api import ProjectAPI
from apps.architect_video_studio.mock_api.store import StudioStore


class TestBuildingStageContract(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.api = ProjectAPI(StudioStore(Path(self.tmp.name) / "data"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_owner_values_are_persisted_canonically(self):
        for stage in ("方案", "扩初", "报建", "展示"):
            project = self.api.create_project(f"Study {stage}", building_stage=stage)
            self.assertEqual(project["building_stage"], stage)

    def test_english_api_aliases_normalize_to_owner_values(self):
        expected = {
            "concept": "方案",
            "schematic": "扩初",
            "construction": "报建",
            "presentation": "展示",
        }
        for alias, canonical in expected.items():
            project = self.api.create_project(f"Alias {alias}", building_stage=alias)
            self.assertEqual(project["building_stage"], canonical)

    def test_invalid_or_blank_stage_is_rejected_without_internal_enum_detail(self):
        for value in (None, "", " ", " 方案", "方案 ", "invalid"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "请选择有效的建筑阶段") as ctx:
                    self.api.create_project("Invalid stage", building_stage=value)
                self.assertNotIn("ALLOWED_BUILDING_STAGES", str(ctx.exception))

    def test_update_also_keeps_the_persisted_contract_valid(self):
        project = self.api.create_project("Update stage")
        updated = self.api.update_project(project["id"], {"building_stage": "schematic"})
        self.assertEqual(updated["building_stage"], "扩初")
        with self.assertRaisesRegex(ValueError, "请选择有效的 Study 类型"):
            self.api.update_project(project["id"], {"project_type": "not-a-type"})

    def test_frontend_stage_options_have_explicit_canonical_values(self):
        root = Path(__file__).resolve().parents[1]
        html = (root / "apps/architect_video_studio/frontend/index.html").read_text(encoding="utf-8")
        for stage in ("方案", "扩初", "报建", "展示"):
            self.assertIn(f'<sl-option value="{stage}">{stage}</sl-option>', html)
        self.assertIn('<sl-select id="task-stage" value="方案">', html)


if __name__ == "__main__":
    unittest.main()
