"""Tests for path-free runtime identity persisted with future Jobs."""

import json
import re
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from apps.architect_video_studio.mock_api.job_api import build_runtime_identity


class RuntimeIdentityTests(unittest.TestCase):
    def test_native_identity_records_deployment_and_opaque_fingerprints(self):
        client = SimpleNamespace(
            base_url="http://owner:secret@127.0.0.1:8190/private/path",
            output_root_fingerprint="a" * 64,
            comfyui_git_sha="ee71d5c4993f29086b27fde1629a945ae48425bf",
        )
        identity = build_runtime_identity(
            "experimental", SimpleNamespace(client=client),
            {"health": {"comfyui_version": "0.36.0"}},
        )

        self.assertEqual(identity["runtime_role"], "experimental")
        self.assertEqual(identity["target"], "experimental")
        self.assertEqual(identity["backend"], "comfyui")
        self.assertEqual(identity["execution_backend"], "native_comfyui")
        self.assertEqual(identity["port"], 8190)
        self.assertEqual(identity["comfyui_version"], "0.36.0")
        self.assertEqual(identity["comfyui_git_sha"],
                         "ee71d5c4993f29086b27fde1629a945ae48425bf")
        self.assertEqual(identity["output_root_fingerprint"], "a" * 64)
        self.assertEqual(identity["runtime_id"],
                         "experimental-h3-8190")
        self.assertRegex(identity["endpoint_fingerprint"], r"^[0-9a-f]{64}$")
        self.assertRegex(identity["runtime_config_fingerprint"], r"^[0-9a-f]{64}$")
        serialized = json.dumps(identity)
        self.assertNotIn("owner", serialized)
        self.assertNotIn("secret", serialized)
        self.assertNotIn("private/path", serialized)

    def test_missing_git_sha_stays_unknown_and_config_fingerprint_tracks_root(self):
        def build(root_fingerprint):
            return build_runtime_identity(
                "experimental",
                SimpleNamespace(client=SimpleNamespace(
                    base_url="http://127.0.0.1:8190",
                    output_root_fingerprint=root_fingerprint,
                )),
                {"health": {"system": {"comfyui_version": "0.36.0"}}},
            )

        first = build("a" * 64)
        second = build("b" * 64)
        self.assertIsNone(first["comfyui_git_sha"])
        self.assertNotEqual(first["runtime_config_fingerprint"],
                            second["runtime_config_fingerprint"])
        self.assertEqual(first["comfyui_version"], "0.36.0")

    def test_mock_identity_is_explicit(self):
        identity = build_runtime_identity("production", None)
        self.assertEqual(identity["runtime_role"], "production")
        self.assertEqual(identity["runtime_id"], "production-h3-8189")
        self.assertEqual(identity["backend"], "mock")
        self.assertEqual(identity["execution_backend"], "mock")
        self.assertEqual(identity["port"], 8189)
        self.assertIsNone(identity["comfyui_version"])
        self.assertIsNone(identity["comfyui_git_sha"])
        self.assertTrue(re.fullmatch(r"[0-9a-f]{64}",
                                     identity["runtime_config_fingerprint"]))


if __name__ == "__main__":
    unittest.main()
