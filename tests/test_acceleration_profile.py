"""Unit test for VRAM Profiles & Timestep Schedule Optimization.
"""

import sys
import unittest
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from runtime.acceleration.vram_optimizer import VRAMOptimizer
from runtime.acceleration.timestep_optimizer import TimestepOptimizer

class TestAccelerationProfile(unittest.TestCase):
    def setUp(self):
        self.vram_opt = VRAMOptimizer()
        self.timestep_opt = TimestepOptimizer()

    def test_h3_low_profile(self):
        profile = self.vram_opt.get_profile("H3_LOW")
        self.assertEqual(profile.profile_key, "H3_LOW")
        self.assertEqual(profile.resolution, "1024x576")
        self.assertTrue(profile.offload)

    def test_h3_pro_profile(self):
        profile = self.vram_opt.get_profile("H3_PRO")
        self.assertEqual(profile.profile_key, "H3_PRO")
        self.assertEqual(profile.frames, 96)
        self.assertFalse(profile.offload)

    def test_timestep_optimization(self):
        profile = self.vram_opt.get_profile("H3_STANDARD")
        opt_profile = self.timestep_opt.optimize_schedule(profile, task_type="analysis")
        self.assertEqual(opt_profile.video_shift, 10.0)

if __name__ == "__main__":
    unittest.main()
