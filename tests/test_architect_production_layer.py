"""Architect Production Layer validation (V0.8.0 RC3.3).

Validates (unit-level, no GPU/ComfyUI required):
1. workspace creation (userdata/projects)
2. workflow catalog (5 workflows, required fields)
3. skill registry (official MiniMax H3 skill rules)
4. prompt bridge (official FL2VA structure)
5. output package (input/workflow/prompt/output/report)
"""

import json
import shutil
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from runtime.prompt_bridge.architect_h3_prompt_bridge import H3PromptBridge  # noqa: E402

CATALOG = REPO_ROOT / "configs" / "workflow_catalog.json"
RULES = REPO_ROOT / "runtime" / "prompt_bridge" / "skill_registry" / "minimax_h3_skill_rules.json"
PROJECTS = REPO_ROOT / "userdata" / "projects"


class TestArchitectProductionLayer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bridge = H3PromptBridge()
        cls.tmp_project = PROJECTS / "__test_architect_layer__"

    def test_01_workflow_catalog(self):
        data = json.loads(CATALOG.read_text(encoding="utf-8"))
        self.assertEqual(data["total_workflows"], 5)
        names = list(data["workflows"])
        self.assertEqual(names, [
            "01_Exterior_Hero", "02_Day_Night_Transition", "03_Material_Detail",
            "04_Drone_Aerial", "05_Slow_Walkthrough",
        ])
        for w in data["workflows"].values():
            for key in ("name", "purpose", "input_type", "camera_style", "recommended_prompt", "output_type"):
                self.assertIn(key, w, f"{w['name']} missing {key}")
                self.assertTrue(str(w[key]).strip(), f"{w['name']} empty {key}")

    def test_02_skill_registry(self):
        data = json.loads(RULES.read_text(encoding="utf-8"))
        for cat in ("camera", "motion", "lighting", "geometry", "material", "atmosphere"):
            self.assertIn(cat, data["categories"])
        fl = data["fl2va"]
        self.assertEqual(fl["core_fields_order"],
                         ["integrated_multimodal_description", "overall_soundscape", "non_diegetic_music"])
        self.assertTrue(fl["alignment_instruction"].startswith("How the reference pictures align"))

    def test_03_prompt_bridge_official_structure(self):
        result = self.bridge.build_fl2va_prompt(
            intent="保持建筑体量，黄昏光线，无人机缓慢环绕，突出混凝土和玻璃材质",
            workflow_name="04_Drone_Aerial", duration_seconds=5.0,
            input_images=["input_images/dummy.png"],
        )
        prompt = result["prompt"]
        self.assertTrue(prompt.startswith("How the reference pictures align with the target video"))
        idx_desc = prompt.index("integrated_multimodal_description:")
        idx_sound = prompt.index("overall_soundscape:")
        idx_music = prompt.index("non_diegetic_music:")
        self.assertLess(idx_desc, idx_sound)
        self.assertLess(idx_sound, idx_music)
        self.assertIn("[Shot 1]", result["integrated_multimodal_description"])
        self.assertIn("No text, subtitles, logos, or watermarks", result["integrated_multimodal_description"])
        self.assertTrue(result["overall_soundscape"].strip())
        self.assertTrue(result["non_diegetic_music"].strip())
        self.assertIn("concrete", result["intent_fields"]["material"]["phrase"].lower())
        self.assertEqual(result["workflow"], "04_Drone_Aerial")

    def test_04_output_package(self):
        result = self.bridge.build_fl2va_prompt(
            intent="无人机缓慢环绕，黄昏光线", workflow_name="04_Drone_Aerial",
        )
        root = self.bridge.write_output_package("__test_architect_layer__", result)
        for sub in ("input_images", "selected_workflow", "prompts", "outputs", "reports"):
            self.assertTrue((root / sub).is_dir(), sub)
        self.assertTrue((root / "prompts" / "prompt.txt").is_file())
        self.assertTrue((root / "prompts" / "prompt.json").is_file())
        self.assertTrue((root / "reports" / "report.json").is_file())
        report = json.loads((root / "reports" / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["workflow"], "04_Drone_Aerial")
        self.assertEqual(report["output_mp4_expected"], str(root / "outputs" / "output.mp4"))

    def test_05_workspace_creation(self):
        self.bridge.write_output_package("__test_architect_layer__",
            self.bridge.build_fl2va_prompt("黄昏光线", "01_Exterior_Hero"))
        self.assertTrue(self.tmp_project.is_dir())


    def test_06_i2va_official_compliance(self):
        result = self.bridge.build_i2va_prompt(
            intent="subtle aerial reveal, Arc Shot small amplitude slow speed, keep original lighting, preserve building massing",
            workflow_name="04_Drone_Aerial", duration_seconds=4.0)
        prompt = result["prompt"]
        self.assertTrue(prompt.startswith("For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced."))
        self.assertLess(prompt.index("integrated_multimodal_description:"), prompt.index("overall_soundscape:"))
        self.assertLess(prompt.index("overall_soundscape:"), prompt.index("non_diegetic_music:"))
        check = self.bridge.verify_official_structure(result)
        self.assertTrue(check["pass"], check["checks"])

    def tearDown(self):
        if self.tmp_project.exists():
            shutil.rmtree(self.tmp_project)


if __name__ == "__main__":
    unittest.main()
