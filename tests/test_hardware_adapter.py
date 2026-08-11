"""Unit test for Hardware Abstraction Layer (HAL) profiles (H3_LOW, H3_STANDARD, H3_PRO).
"""

import sys
import unittest
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from hardware.detect_gpu import match_hardware_profile

class TestHardwareAdapter(unittest.TestCase):
    def test_hal_profile_matching_rules(self):
        profiles_data = {
            "profiles": {
                "H3_LOW": {"name": "H3_LOW", "resolution": [768, 432]},
                "H3_STANDARD": {"name": "H3_STANDARD", "resolution": [1280, 720]},
                "H3_PRO": {"name": "H3_PRO", "resolution": [1920, 1080]}
            }
        }

        # Test 8GB GPU -> H3_LOW
        key_low, prof_low = match_hardware_profile({"vram_gb": 8.0}, profiles_data)
        self.assertEqual(key_low, "H3_LOW")
        self.assertEqual(prof_low["resolution"], [768, 432])

        # Test 12GB GPU -> H3_STANDARD
        key_std, prof_std = match_hardware_profile({"vram_gb": 12.0}, profiles_data)
        self.assertEqual(key_std, "H3_STANDARD")
        self.assertEqual(prof_std["resolution"], [1280, 720])

        # Test 24GB GPU -> H3_PRO
        key_pro, prof_pro = match_hardware_profile({"vram_gb": 24.0}, profiles_data)
        self.assertEqual(key_pro, "H3_PRO")
        self.assertEqual(prof_pro["resolution"], [1920, 1080])

if __name__ == "__main__":
    unittest.main()
