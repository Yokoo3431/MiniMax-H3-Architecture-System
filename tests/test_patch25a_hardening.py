"""RC3.3 PATCH2.5-A - Production Contract Hardening tests.

Covers the pre-UI hardening gate:
1. pinned Official Skill version gate (PIN, DO NOT FLOAT)
2. project_type != workflow task (video_task drives workflow selection)
3. natural-language classification confidence / ambiguity
4. explicit user workflow override
5. reference gate remains mandatory/advisory
6. extended motion-risk contract
7. dynamic FL2VA end-time (no hard-coded 4.46s)
8. legacy adapter hard-block (import scan)
9. prompt provenance metadata
10. five frozen prompt fixtures (deterministic)
11. workflow profile contract fields
"""

import json
import sys
import unittest
import importlib.util
from pathlib import Path
from unittest import mock

_HAS_CV2 = importlib.util.find_spec("cv2") is not None
if _HAS_CV2:
    import cv2
    import numpy as np
from runtime.yaml_compat import safe_load

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from runtime.prompt_bridge import skill_version as sv
from runtime.prompt_bridge.architect_h3_prompt_bridge import (
    H3PromptBridge,
    fl2va_end_time_seconds,
)
from runtime.prompt_bridge.official_skill_adapter import (
    ArchitectIntent,
    OfficialSkillAdapter,
    ReferenceMetadata,
)
if _HAS_CV2:
    from runtime.input_validator.reference_quality_assistant import ReferenceQualityAssistant
else:
    ReferenceQualityAssistant = None


FIXTURES = SYSTEM_ROOT / "tests" / "fixtures" / "official_skill_prompts"


class TestSkillVersionPolicy(unittest.TestCase):
    def test_installed_matches_pinned_allows_generation(self):
        gate = sv.check_skill_version()
        self.assertEqual(gate["status"], "GENERATION_ALLOWED")
        self.assertTrue(gate["installed_matches_pinned"])
        self.assertNotIn("INSTALLED_SKILL_MISMATCH_PINNED", gate["flags"])

    def test_upstream_mismatch_does_not_switch_production(self):
        fake_latest = {
            "SKILL.md": "A" * 64,
            "references/base-en.txt": "B" * 64,
        }
        gate = sv.check_skill_version(latest=fake_latest)
        # installed still == pinned -> generation stays allowed.
        self.assertEqual(gate["status"], "GENERATION_ALLOWED")
        self.assertFalse(gate["upstream_matches_pinned"])
        self.assertIn("OFFICIAL_SKILL_UPDATE_AVAILABLE", gate["flags"])

    def test_upstream_unknown_surfaces_check_required(self):
        gate = sv.check_skill_version(latest=None)
        self.assertEqual(gate["status"], "GENERATION_ALLOWED")
        self.assertIn("SKILL_UPSTREAM_CHECK_REQUIRED", gate["flags"])

    def test_installed_mismatch_blocks_generation(self):
        fake_pinned = {
            "label": "fake",
            "files": {"SKILL.md": "C" * 64, "references/base-en.txt": "D" * 64},
        }
        gate = sv.check_skill_version(pinned=fake_pinned)
        self.assertEqual(gate["status"], "BLOCKED")
        self.assertIn("INSTALLED_SKILL_MISMATCH_PINNED", gate["flags"])

    def test_require_generation_allowed_raises_on_mismatch(self):
        fake_pinned = {
            "label": "fake",
            "files": {"SKILL.md": "E" * 64, "references/base-en.txt": "F" * 64},
        }
        with mock.patch.object(sv, "PINNED_SKILL_REVISION", fake_pinned):
            with self.assertRaises(RuntimeError):
                sv.require_generation_allowed()


class TestVideoTaskSeparation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.adapter = OfficialSkillAdapter()

    def test_video_task_selects_workflow_regardless_of_project_type(self):
        cases = [
            (ArchitectIntent(project_type="interior", video_task="day_night_transition"),
             "02_Day_Night_Transition"),
            (ArchitectIntent(project_type="exterior", video_task="material_detail"),
             "03_Material_Detail"),
            (ArchitectIntent(project_type="exterior", video_task="slow_walkthrough"),
             "05_Slow_Walkthrough"),
            (ArchitectIntent(project_type="landscape", video_task="drone_aerial"),
             "04_Drone_Aerial"),
            (ArchitectIntent(project_type="mixed", video_task="exterior_hero"),
             "01_Exterior_Hero"),
        ]
        for intent, expected in cases:
            self.assertEqual(self.adapter.select_workflow(intent), expected)

    def test_project_type_alone_is_advisory_not_authoritative(self):
        # project_type=exterior with video_task=material_detail must NOT select hero.
        self.assertEqual(
            self.adapter.select_workflow(
                ArchitectIntent(project_type="exterior", video_task="material_detail")),
            "03_Material_Detail",
        )

    def test_mixed_project_type_without_video_task_is_ambiguous(self):
        with self.assertRaises(ValueError):
            self.adapter.select_workflow(ArchitectIntent(project_type="mixed"))


class TestIntentClassification(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.adapter = OfficialSkillAdapter()

    def test_vague_intent_requires_confirmation(self):
        result = self.adapter.classify_intent("帮我把这个建筑做一个高级一点的视频")
        self.assertTrue(result["requires_user_confirmation"])
        self.assertIsNone(result["selected_workflow"])
        self.assertEqual(result["confidence"], 0.0)
        self.assertGreaterEqual(len(result["candidate_workflows"]), 2)

    def test_clear_intent_high_confidence(self):
        result = self.adapter.classify_intent("用这张入口透视图做一个非常慢的向前漫游")
        self.assertFalse(result["requires_user_confirmation"])
        self.assertEqual(result["selected_workflow"], "05_Slow_Walkthrough")
        self.assertEqual(result["selected_video_task"], "slow_walkthrough")
        self.assertGreaterEqual(result["confidence"], 0.8)

    def test_ambiguous_keyword_overlap_requires_confirmation(self):
        # "夜景漫游" ties day-night vs walkthrough - no silent guess.
        result = self.adapter.classify_intent("夜景漫游")
        self.assertTrue(result["requires_user_confirmation"])

    def test_explicit_workflow_override_in_text(self):
        result = self.adapter.classify_intent("用 03 材质细节工作流生成")
        self.assertEqual(result["selected_workflow"], "03_Material_Detail")
        self.assertFalse(result["requires_user_confirmation"])

    def test_explicit_workflow_override_param(self):
        ref = ReferenceMetadata(input_images=["x.png"], user_approved=True)
        out = self.adapter.build_prompt(
            ArchitectIntent(project_type="exterior", requires_user_confirmation=True),
            workflow="01_Exterior_Hero",
            reference=ref,
        )
        self.assertEqual(out["workflow"], "01_Exterior_Hero")

    def test_ambiguous_intent_blocks_build_without_override(self):
        ref = ReferenceMetadata(input_images=["x.png"], user_approved=True)
        with self.assertRaises(ValueError):
            self.adapter.build_prompt(
                ArchitectIntent(project_type="exterior", requires_user_confirmation=True),
                reference=ref,
            )


class TestLegacyAdapterHardBlock(unittest.TestCase):
    _LEGACY = "official_h3_prompt_adapter"

    def test_package_init_does_not_export_legacy(self):
        init_text = (SYSTEM_ROOT / "runtime" / "prompt_bridge" / "__init__.py").read_text(encoding="utf-8")
        self.assertNotIn(f"from .{self._LEGACY}", init_text)
        self.assertNotIn(f"import {self._LEGACY}", init_text)
        self.assertNotIn("OfficialH3PromptAdapter", init_text)

    def test_production_sources_never_import_legacy(self):
        import re

        production_roots = [
            SYSTEM_ROOT / "runtime",
            SYSTEM_ROOT / "scripts",
            SYSTEM_ROOT / "launcher",
        ]
        import_pattern = re.compile(
            r"^\s*(?:from\s+.*\bofficial_h3_prompt_adapter\b|import\s+\bofficial_h3_prompt_adapter\b)",
            re.MULTILINE,
        )
        # Only flag actual instantiation/calls, not docstring mentions of the name.
        use_pattern = re.compile(r"\bOfficialH3PromptAdapter\s*\(")
        offenders = []
        for root in production_roots:
            if not root.is_dir():
                continue
            for py in root.rglob("*.py"):
                if py.name == "official_h3_prompt_adapter.py":
                    continue
                text = py.read_text(encoding="utf-8", errors="ignore")
                if import_pattern.search(text) or use_pattern.search(text):
                    offenders.append(str(py))
        self.assertEqual(offenders, [])

    def test_legacy_module_has_deprecation_marker(self):
        legacy = SYSTEM_ROOT / "runtime" / "prompt_bridge" / "official_h3_prompt_adapter.py"
        self.assertTrue(legacy.is_file())
        text = legacy.read_text(encoding="utf-8")
        self.assertIn("DEPRECATED", text.upper())


class TestDynamicFl2vaTiming(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bridge = H3PromptBridge()

    def test_end_time_helper(self):
        self.assertAlmostEqual(fl2va_end_time_seconds(107, 24.0), 107.0 / 24.0)
        self.assertAlmostEqual(fl2va_end_time_seconds(124, 24.0), 124.0 / 24.0)
        with self.assertRaises(ValueError):
            fl2va_end_time_seconds(0)
        with self.assertRaises(ValueError):
            fl2va_end_time_seconds(107, 0)

    def test_validated_107_frame_baseline(self):
        result = self.bridge.build_fl2va_prompt(
            "static shot, lighting transition, keep geometry",
            "02_Day_Night_Transition",
            duration_seconds=4.0,
            input_images=["day.png", "night.png"],
            frame_count=107,
        )
        self.assertEqual(result["end_time_seconds"], 107.0 / 24.0)
        self.assertIn("4.46-second mark", result["alignment_instruction"])

    def test_alternate_frame_grid(self):
        result = self.bridge.build_fl2va_prompt(
            "static shot, lighting transition, keep geometry",
            "02_Day_Night_Transition",
            duration_seconds=5.0,
            input_images=["day.png", "night.png"],
            frame_count=124,
        )
        self.assertEqual(result["end_time_seconds"], 124.0 / 24.0)
        self.assertIn("5.17-second mark", result["alignment_instruction"])

    def test_adapter_passes_frame_grid_into_alignment(self):
        out = OfficialSkillAdapter().build_prompt(
            ArchitectIntent(project_type="lighting", video_task="day_night_transition",
                            camera_motion="static", priority="lighting"),
            reference=ReferenceMetadata(input_images=["d.png", "n.png"], user_approved=True),
            frame_count=124,
        )
        self.assertIn("5.17-second mark", out["alignment"])
        self.assertEqual(out["provenance"]["frame_count"], 124)


class TestProvenance(unittest.TestCase):
    def test_provenance_metadata_present(self):
        out = OfficialSkillAdapter().build_prompt(
            ArchitectIntent(project_type="material", video_task="material_detail",
                            scene="concrete seam", camera_motion="static", priority="material"),
            reference=ReferenceMetadata(input_images=["mat.png"], user_approved=True),
        )
        prov = out["provenance"]
        for key in ("official_skill_revision", "official_skill_hash", "installed_skill_hash",
                    "bridge_revision", "adapter_revision", "workflow_profile_revision",
                    "workflow_id", "video_task", "generation_mode", "raw_architect_intent",
                    "user_reference_hashes", "user_reference_approved", "generated_prompt_hash"):
            self.assertIn(key, prov, key)
        self.assertTrue(prov["user_reference_approved"])
        self.assertEqual(prov["workflow_id"], "03_Material_Detail")
        self.assertEqual(prov["generation_mode"], "I2VA")
        import hashlib
        self.assertEqual(
            prov["generated_prompt_hash"],
            hashlib.sha256(out["prompt"].encode("utf-8")).hexdigest().upper(),
        )

    def test_provenance_stored_in_report_json(self):
        import shutil
        import tempfile

        bridge = H3PromptBridge(projects_root=Path(tempfile.mkdtemp()))
        out = OfficialSkillAdapter(bridge=bridge).build_prompt(
            ArchitectIntent(project_type="exterior", video_task="exterior_hero",
                            scene="villa facade", camera_motion="slow_push", priority="geometry"),
            reference=ReferenceMetadata(input_images=["villa.png"], user_approved=True),
        )
        root = bridge.write_output_package("__provenance_report__", out)
        report = json.loads((root / "reports" / "report.json").read_text(encoding="utf-8"))
        self.assertIn("provenance", report)
        self.assertEqual(report["provenance"]["workflow_id"], "01_Exterior_Hero")
        self.assertTrue(report["provenance"]["user_reference_approved"])
        shutil.rmtree(root.parent)


class TestWorkflowProfileContract(unittest.TestCase):
    _REQUIRED_FIELDS = (
        "workflow_id",
        "video_task",
        "required_reference_count",
        "allowed_reference_roles",
        "preferred_camera",
        "maximum_motion_class",
        "preservation_priority",
        "prohibited_transformations",
        "known_limitations",
        "user_confirmation_rules",
    )

    def test_all_profiles_have_contract_fields(self):
        profiles = OfficialSkillAdapter().profiles["workflow_profiles"]
        self.assertEqual(len(profiles), 5)
        for name, profile in profiles.items():
            for field in self._REQUIRED_FIELDS:
                self.assertIn(field, profile, f"{name} missing {field}")
            self.assertEqual(profile["workflow_id"], name)
            self.assertEqual(
                profile["official_skill_mode"],
                "FL2VA" if name == "02_Day_Night_Transition" else "I2VA",
            )


class TestMotionRiskExtension(unittest.TestCase):
    @unittest.skipUnless(_HAS_CV2, "optional dependency cv2/numpy is not installed")
    def test_extended_risk_contract(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            img = np.random.default_rng(3).integers(0, 256, (1080, 1920, 3), dtype=np.uint8)
            path = Path(tmp) / "src.png"
            cv2.imwrite(str(path), img)
            report = ReferenceQualityAssistant().assess(str(path), intended_motion="orbit 360 rotation")
            self.assertEqual(report["reference_quality"]["motion_risk"], "HIGH")
            names = [d["risk"] for d in report["reference_quality"]["motion_risk_details"]]
            self.assertIn("aerial_180_360", names)
            self.assertIn("recommended_alternative", report["reference_quality"]["motion_risk_details"][0])

    def test_assistant_remains_advisory(self):
        # The assistant must not alter the approval gate: user_approved=False still blocks.
        with self.assertRaises(ValueError):
            OfficialSkillAdapter().build_prompt(
                ArchitectIntent(project_type="exterior", video_task="exterior_hero"),
                reference=ReferenceMetadata(input_images=["x.png"], user_approved=False),
            )


class TestFrozenFixtures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.adapter = OfficialSkillAdapter()

    def test_five_fixtures_exist(self):
        names = sorted(p.stem for p in FIXTURES.glob("*.json"))
        self.assertEqual(names, [
            "01_Exterior_Hero",
            "02_Day_Night_Transition",
            "03_Material_Detail",
            "04_Drone_Aerial",
            "05_Slow_Walkthrough",
        ])

    def test_fixture_determinism_and_structure(self):
        for fixture_path in sorted(FIXTURES.glob("*.json")):
            fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
            intent = ArchitectIntent(**fixture["architect_intent"])
            ref = ReferenceMetadata(
                input_images=list(fixture["reference_metadata"]["input_images"]),
                user_approved=bool(fixture["reference_metadata"]["user_approved"]),
            )
            kwargs = {
                "duration_seconds": fixture.get("duration_seconds", 4.0),
            }
            if fixture.get("frame_count") is not None:
                kwargs["frame_count"] = fixture["frame_count"]
                kwargs["fps"] = fixture.get("fps", 24.0)
            first = self.adapter.build_prompt(intent, reference=ref, **kwargs)
            second = self.adapter.build_prompt(intent, reference=ref, **kwargs)
            self.assertEqual(first["prompt"], second["prompt"], fixture_path.name)
            self.assertEqual(first["mode"], fixture["mode"])
            self.assertEqual(first["workflow"], fixture["workflow"])
            self.assertEqual(first["non_diegetic_music"], "N/A")
            self.assertTrue(first["verified"]["pass"])
            self.assertEqual(first["provenance"]["video_task"], fixture["video_task"])
            self.assertTrue(first["prompt"].startswith(fixture["expected_structure"]["alignment_prefix"]))


if not _HAS_CV2:
    for _value in list(globals().values()):
        if isinstance(_value, type) and issubclass(_value, unittest.TestCase):
            _value.__unittest_skip__ = True
            _value.__unittest_skip_why__ = "optional dependency cv2/numpy is not installed"
    del _value

if __name__ == "__main__":
    unittest.main()
