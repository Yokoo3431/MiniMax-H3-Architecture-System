"""Unit test & UAT validation for 5 Architect Acceptance Test Cases (V0.7.8.3).
"""

import sys
import json
import unittest
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from runtime.h3_orchestrator import H3Orchestrator
from runtime.interface.architect_request import ArchitectRequest
from runtime.critic.architect_acceptance import ArchitectIntentAuditor
from runtime.critic.architecture_fidelity_checker import ArchitecturalFidelityChecker

MANIFEST_FILE = SYSTEM_ROOT / "tests" / "assets" / "architect_cases" / "cases_manifest.json"

class TestArchitectAcceptance(unittest.TestCase):
    def setUp(self):
        self.orchestrator = H3Orchestrator()
        self.intent_auditor = ArchitectIntentAuditor()
        self.fidelity_checker = ArchitecturalFidelityChecker()

    def test_architect_acceptance_manifest_exists(self):
        self.assertTrue(MANIFEST_FILE.is_file(), "cases_manifest.json must exist")
        with open(MANIFEST_FILE, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        self.assertEqual(manifest["total_cases"], 5)

    def test_case_01_exterior_hero(self):
        req = ArchitectRequest(
            images=["museum_exterior.jpg"],
            task_description="Create architectural promotional walkthrough video",
            video_style="exterior_hero"
        )
        res = self.orchestrator.generate_from_architect_request(req)
        self.assertEqual(res["status"], "completed")

        intent_res = self.intent_auditor.audit_architect_intent(
            req.task_description,
            res["generated_prompt"],
            res["selected_workflow"]
        )
        self.assertEqual(intent_res["status"], "PASS")

        fidelity_res = self.fidelity_checker.check_fidelity(
            res["video_path"],
            res["generated_prompt"],
            res["critic_score"]
        )
        self.assertEqual(fidelity_res["status"], "PASS")

    def test_case_02_day_night_transition(self):
        req = ArchitectRequest(
            images=["day_rendering.jpg"],
            task_description="Convert into evening architectural animation",
            video_style="day_night_transition"
        )
        res = self.orchestrator.generate_from_architect_request(req)
        self.assertEqual(res["status"], "completed")

    def test_case_03_material_detail(self):
        req = ArchitectRequest(
            images=["material_close_up.jpg"],
            task_description="Generate architectural material showcase",
            video_style="material_detail"
        )
        res = self.orchestrator.generate_from_architect_request(req)
        self.assertEqual(res["status"], "completed")

    def test_case_04_drone_aerial(self):
        req = ArchitectRequest(
            images=["aerial_building.jpg"],
            task_description="High altitude drone orbit sweeping masterplan",
            video_style="drone_aerial"
        )
        res = self.orchestrator.generate_from_architect_request(req)
        self.assertEqual(res["status"], "completed")

    def test_case_05_slow_walkthrough(self):
        req = ArchitectRequest(
            images=["interior_architectural.jpg"],
            task_description="Interior architectural walkthrough through atrium",
            video_style="slow_walkthrough"
        )
        res = self.orchestrator.generate_from_architect_request(req)
        self.assertEqual(res["status"], "completed")

if __name__ == "__main__":
    unittest.main()
