"""Unit test & score evaluation for 100-Point Architectural Visual Quality Validation (V0.7.8.4).
"""

import sys
import json
import unittest
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from runtime.critic.visual_quality_validator import VisualQualityValidator

SCORE_FILE = SYSTEM_ROOT / "configs" / "architect_quality_score.json"
OUTPUTS_MANIFEST = SYSTEM_ROOT / "tests" / "assets" / "architect_outputs" / "outputs_manifest.json"

class TestVisualQualityValidation(unittest.TestCase):
    def setUp(self):
        self.validator = VisualQualityValidator()

    def test_architect_quality_score_config_exists(self):
        self.assertTrue(SCORE_FILE.is_file(), "architect_quality_score.json must exist")
        with open(SCORE_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        self.assertEqual(cfg["production_threshold"], 85.0)
        self.assertEqual(cfg["weights"]["geometry_fidelity"], 30.0)

    def test_outputs_manifest_exists(self):
        self.assertTrue(OUTPUTS_MANIFEST.is_file(), "outputs_manifest.json must exist")
        with open(OUTPUTS_MANIFEST, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        self.assertEqual(manifest["total_outputs"], 5)

    def test_visual_quality_validator_100_point_scoring(self):
        prompt = "Architectural visualization of museum, slow push shot with 35mm architectural lens, twilight dusk illumination, 3500K warm interior glow, preserve building geometry, photorealistic architectural photography, 4k ultra detailed, fair-faced concrete"
        res = self.validator.validate_visual_quality("output.mp4", prompt, "3_night_transition")

        self.assertGreaterEqual(res["total_score"], 85.0)
        self.assertEqual(res["status"], "PASS")
        self.assertIn("breakdown", res)
        self.assertEqual(res["breakdown"]["geometry_fidelity"], 29.0)

if __name__ == "__main__":
    unittest.main()
