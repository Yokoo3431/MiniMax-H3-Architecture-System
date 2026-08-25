"""RC3.3 PATCH2.5 - Official H3 Skill production pipeline tests.

Covers: skill rule loading, intent mapping, prompt schema, workflow profile
consistency, reference gate, and the reference quality assistant.
"""

import sys
import tempfile
import unittest
import importlib.util
from pathlib import Path

_HAS_CV2 = importlib.util.find_spec("cv2") is not None
if _HAS_CV2:
    import cv2
    import numpy as np
from runtime.yaml_compat import safe_load

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from runtime.prompt_bridge.architect_h3_prompt_bridge import H3PromptBridge
from runtime.prompt_bridge.official_skill_adapter import (
    ArchitectIntent,
    OfficialSkillAdapter,
    ReferenceMetadata,
)
if _HAS_CV2:
    from runtime.input_validator.reference_quality_assistant import ReferenceQualityAssistant
else:
    ReferenceQualityAssistant = None


class TestOfficialSkillPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.adapter = OfficialSkillAdapter()
        cls.bridge = H3PromptBridge()

    def test_skill_rule_loading(self):
        rules = self.bridge.rules
        self.assertIn("categories", rules)
        self.assertIn("soundscape_default", rules)
        self.assertIn("music_default", rules)
        self.assertEqual(
            rules["meta"]["source"],
            "MiniMax-AI/MiniMax-H3 skills/h3-prompt-writing (official) + references/base-en.txt",
        )
        skill_dir = SYSTEM_ROOT / "references" / "known_good_h3" / "comfy_official" / "skill_check"
        self.assertTrue((skill_dir / "SKILL.md").is_file())
        self.assertTrue((skill_dir / "base-en.txt").is_file())

    def test_intent_mapping(self):
        self.assertEqual(
            self.adapter.select_workflow(ArchitectIntent(project_type="material")),
            "03_Material_Detail",
        )
        self.assertEqual(
            self.adapter.select_workflow(ArchitectIntent(project_type="exterior")),
            "01_Exterior_Hero",
        )
        self.assertEqual(
            self.adapter.select_workflow(ArchitectIntent(project_type="lighting")),
            "02_Day_Night_Transition",
        )

    def _material_ref(self):
        return ReferenceMetadata(
            input_images=["material_reference.jpg"],
            user_approved=True,
        )

    def test_prompt_schema_i2va(self):
        out = self.adapter.build_prompt(
            ArchitectIntent(
                project_type="material",
                scene="fair-faced concrete facade",
                camera_motion="static",
                priority="material",
                constraints=["geometry", "material"],
            ),
            reference=self._material_ref(),
        )
        self.assertEqual(out["mode"], "I2VA")
        self.assertEqual(out["workflow"], "03_Material_Detail")
        for field in ("alignment", "integrated_multimodal_description",
                      "overall_soundscape", "non_diegetic_music"):
            self.assertIn(field, out)
        self.assertEqual(out["non_diegetic_music"], "N/A")
        self.assertTrue(out["verified"]["pass"])
        self.assertTrue(out["prompt"].startswith(
            "For the target video, at 0.00 seconds into the target video, "
            "<Picture 1> (from [Shot 1]) is fully referenced."
        ))

    def test_prompt_schema_fl2va(self):
        ref = ReferenceMetadata(
            input_images=["day.png", "night.png"],
            user_approved=True,
        )
        out = self.adapter.build_prompt(
            ArchitectIntent(
                project_type="lighting",
                video_task="day_night_transition",
                camera_motion="static",
                priority="lighting",
                constraints=["geometry"],
            ),
            reference=ref,
            frame_count=107,
        )
        self.assertEqual(out["mode"], "FL2VA")
        self.assertEqual(out["workflow"], "02_Day_Night_Transition")
        self.assertIn("Picture 1", out["alignment"])
        self.assertIn("Picture 2", out["alignment"])
        self.assertIn("4.46-second", out["alignment"])
        self.assertEqual(out["provenance"]["frame_count"], 107)
        self.assertTrue(out["verified"]["pass"])
        self.assertIn("transition", out["integrated_multimodal_description"].lower())

    def test_workflow_profile_consistency(self):
        profiles = self.adapter.profiles["workflow_profiles"]
        self.assertEqual(set(profiles.keys()), {
            "01_Exterior_Hero", "02_Day_Night_Transition",
            "03_Material_Detail", "04_Drone_Aerial", "05_Slow_Walkthrough",
        })
        for name, profile in profiles.items():
            self.assertIn(profile["official_skill_mode"], ("I2VA", "FL2VA"))
            self.assertIn("input_requirement", profile)
        self.assertEqual(profiles["02_Day_Night_Transition"]["official_skill_mode"], "FL2VA")
        catalog = self.adapter.catalog["workflows"]
        for name in profiles:
            entry = catalog[name]
            for field in ("workflow", "official_skill_mode", "recommended_motion",
                          "input_requirement", "known_limitations"):
                self.assertIn(field, entry, f"{name} missing catalog field {field}")

    def test_reference_gate(self):
        with self.assertRaises(ValueError):
            self.adapter.build_prompt(
                ArchitectIntent(project_type="exterior"),
                reference=ReferenceMetadata(input_images=["a.png"], user_approved=False),
            )
        with self.assertRaises(ValueError):
            self.adapter.build_prompt(
                ArchitectIntent(project_type="lighting"),
                reference=ReferenceMetadata(input_images=["day.png"], user_approved=True),
            )

    @unittest.skipUnless(_HAS_CV2, "optional dependency cv2/numpy is not installed")
    def test_input_validator(self):
        with tempfile.TemporaryDirectory() as tmp:
            img = np.random.default_rng(7).integers(0, 256, (1080, 1920, 3), dtype=np.uint8)
            # add strong straight-line structure for geometry evidence
            cv2.line(img, (0, 300), (1919, 300), (255, 255, 255), 3)
            cv2.line(img, (400, 0), (400, 1079), (255, 255, 255), 3)
            cv2.line(img, (0, 600), (1200, 0), (255, 255, 255), 3)
            path = Path(tmp) / "synthetic_render.png"
            cv2.imwrite(str(path), img)
            report = ReferenceQualityAssistant().assess(str(path), intended_motion="slow_push")
            self.assertIn("reference_quality", report)
            self.assertIn("recommended_workflow", report)
            self.assertIn(report["reference_quality"]["resolution"], ("PASS", "PASS (high)", "MARGINAL", "FAIL (below 768px short edge)"))
            self.assertIn("guidance", report)

    def test_known_limitations_recorded(self):
        profile05 = self.adapter.profiles["workflow_profiles"]["05_Slow_Walkthrough"]
        self.assertEqual(profile05["known_limitation"]["id"], "SINGLE_FRAME_DEEP_WALKTHROUGH_LIMITATION")
        catalog05 = self.adapter.catalog["workflows"]["05_Slow_Walkthrough"]
        self.assertIn("SINGLE_FRAME_DEEP_WALKTHROUGH_LIMITATION", catalog05["known_limitations"])


if not _HAS_CV2:
    for _value in list(globals().values()):
        if isinstance(_value, type) and issubclass(_value, unittest.TestCase):
            _value.__unittest_skip__ = True
            _value.__unittest_skip_why__ = "optional dependency cv2/numpy is not installed"
    del _value

if __name__ == "__main__":
    unittest.main()
