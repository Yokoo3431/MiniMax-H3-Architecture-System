"""CPU-only tests for the single Environment Center state contract."""

from __future__ import annotations

import sys
import tempfile
import unittest
import json
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from apps.architect_video_studio.mock_api.environment_service import EnvironmentService  # noqa: E402
from apps.architect_video_studio.mock_api.store import StudioStore  # noqa: E402


class TestEnvironmentStateUnification(unittest.TestCase):
    def test_pages_receive_one_normalized_state_with_provenance_sources(self):
        with tempfile.TemporaryDirectory() as temp:
            service = EnvironmentService(StudioStore(Path(temp) / "studio"))
            native = Path(temp) / "runtime"
            models = Path(temp) / "models"
            active = SimpleNamespace(native_root=native, models_root=models,
                                     validation_native=None, validation_models=None,
                                     source="configured")
            probe = {
                "probe_status": "READY", "last_probe_finished": "now",
                "gpu_detected": True, "driver_detected": True,
                "torch_cuda_available": True, "gpu_name": "RTX 5070",
            }
            system = {
                "environment_probe": probe, "gpu_ready": True,
                "free_commit": 60, "disk_free_gb": 100,
            }
            runtime = {"present": True, "pread": True, "version": "0.33.1",
                       "frontend": "1.48.7"}
            support = {
                "h3": {"ready": True, "status": "READY", "provenance": {
                    "expected_fingerprint": "release", "actual_fingerprint": "release",
                    "lock_file": "shared-lock.json",
                }},
                "video": {"ready": True, "status": "READY", "provenance": {}},
                "dependencies": {"ready": True, "status": "READY"},
            }
            models_report = {"ready": 4, "count": 4,
                             "items": [{"status": "READY"}] * 4,
                             "h3_model_root": {"ready": True},
                             "h3_asset_status": {"ready": True},
                             "status": "READY"}
            skill = {"status": "READY", "generation_allowed": True}
            workflows = {"ready": 5, "count": 5, "items": []}
            gates = {
                "native_root_configured": True, "comfyui_present": True,
                "pread_present": True, "gpu_ready": True,
                "models_4of4": True, "h3_model_root_ready": True,
                "h3_assets_ready": True, "h3_support_ready": True,
                "video_support_ready": True, "support_dependencies_ready": True,
                "skill_pinned_ready": True, "workflows_5of5": True,
                "free_commit_ok": True, "contract_valid": True,
            }
            with mock.patch.object(service, "_active_environment", return_value=active), \
                    mock.patch.object(service, "_adopt_if_needed"), \
                    mock.patch.object(service, "_system_status", return_value=system), \
                    mock.patch.object(service, "_runtime_status", return_value=runtime), \
                    mock.patch.object(service, "_support_status", return_value=support), \
                    mock.patch.object(service, "_models_status", return_value=models_report), \
                    mock.patch.object(service, "_h3_model_status", return_value={"ready": True, "asset_contract": {"ready": True}}), \
                    mock.patch.object(service, "_skill_status", return_value=skill), \
                    mock.patch.object(service, "_workflow_status", return_value=workflows), \
                    mock.patch.object(service, "_contract_valid", return_value=True), \
                    mock.patch.object(service, "_overall", return_value="READY"):
                result = service.environment()
            state = result["environment_state"]
            self.assertIs(state["system"], result["system"])
            self.assertEqual(state["paths"]["native_root"], str(native))
            self.assertEqual(state["support"]["h3"]["provenance"]["lock_file"], "shared-lock.json")
            self.assertEqual(state["provenance"]["h3"]["actual_fingerprint"], "release")
            self.assertEqual(state["probe"]["probe_status"], "READY")
            self.assertEqual(state["gates"], result["gates"])

    def test_runtime_state_does_not_block_on_experimental_policy(self):
        service = object.__new__(EnvironmentService)
        system = {"gpu_ready": True, "free_commit": 60}
        runtime = {"present": True, "pread": True, "version": "0.33.1", "frontend": "1.48.7"}
        models = {"ready": 4, "count": 4}
        support = {"h3": {"ready": True}, "video": {"ready": True}, "dependencies": {"ready": True}}
        skill = {"generation_allowed": True, "status": "READY"}
        gates = {"native_root_configured": True, "comfyui_present": True,
                 "models_4of4": True, "pread_present": True,
                 "h3_model_root_ready": True, "h3_assets_ready": True,
                 "h3_support_ready": True, "video_support_ready": True,
                 "support_dependencies_ready": True, "workflows_5of5": True,
                 "contract_valid": True}
        self.assertEqual(service._overall(system, runtime, models, support, skill, gates), "READY")
        self.assertEqual(service._free_commit_policy(19.8, "COMPATIBILITY")["status"], "WARNING")

        manifest = json.loads((ROOT / "configs" / "release_runtime_manifest.json").read_text(encoding="utf-8"))
        h3 = manifest["h3"]
        self.assertEqual(h3["upstream_commit"], "d6c5f7b0d4e03936ac4a9834be63ecc6b5637dad")
        self.assertEqual(h3["managed_runtime_fingerprint"],
                         "22167e28e6fb11c016397c9fdbb545a9f0a386fe4cef48d235942d6c3af80f9d")
        stale_prefix = "54" + "c1d5d8"
        self.assertNotIn(stale_prefix, (ROOT / "configs" / "release_runtime_manifest.json").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
