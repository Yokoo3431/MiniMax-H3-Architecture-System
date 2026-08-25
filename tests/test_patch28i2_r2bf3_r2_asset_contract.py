"""PATCH2.8-I2-R2B-F3-R2 H3 asset contract tests.

CPU/static only: temporary metadata fixtures are used; no model, Runtime,
ComfyUI, /prompt, download, or CUDA operation is performed.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from apps.architect_video_studio.mock_api.environment_service import EnvironmentService
from apps.architect_video_studio.mock_api.installer_service import InstallationService
from apps.architect_video_studio.mock_api.store import StudioStore
from runtime.h3_asset_contract import (
    evaluate_h3_asset_contract,
    load_h3_asset_contract,
)
from runtime.h3_sidecar import load_h3_sidecar_manifest


ROOT = Path(__file__).resolve().parents[1]


class H3AssetContractFixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = load_h3_asset_contract(ROOT)

    def _fixture(self, omit: str | None = None) -> Path:
        temp = Path(tempfile.mkdtemp())
        for item in self.contract["required"]:
            if item["logical_component"] == omit:
                continue
            Path(temp / item["accepted_paths"][0]).parent.mkdir(parents=True, exist_ok=True)
            (temp / item["accepted_paths"][0]).write_bytes(b"fixture")
        return temp

    def test_missing_tokenizer_json_blocks_runtime(self):
        root = self._fixture("tokenizer_json")
        state = evaluate_h3_asset_contract(root, ROOT)
        self.assertFalse(state["ready"])
        self.assertEqual(state["status"], "INCOMPATIBLE_RUNTIME")
        self.assertIn("tokenizer_json", state["missing"])
        self.assertEqual(state["groups"]["tokenizer"]["status"], "MISSING")

    def test_tokenizer_json_present_reaches_asset_ready(self):
        root = self._fixture()
        with mock.patch("runtime.h3_asset_contract._manifest_file_index", return_value={}):
            state = evaluate_h3_asset_contract(root, ROOT)
        self.assertTrue(state["ready"])
        self.assertEqual(state["status"], "READY")
        self.assertEqual(state["groups"]["tokenizer"]["status"], "PASS")

    def test_tokenizer_hash_mismatch_blocks_runtime(self):
        root = self._fixture()
        tokenizer = next(item for item in self.contract["required"]
                         if item["logical_component"] == "tokenizer_json")
        path = root / tokenizer["accepted_paths"][0]
        path.write_bytes(b"tampered-tokenizer")
        fake_manifest = {
            "FL2VA/processor/tokenizer.json": {
                "logical_component": "tokenizer_json",
                "expected_size": len(b"expected-tokenizer"),
                "sha256": "B" * 64,
            }
        }
        with mock.patch("runtime.h3_asset_contract._manifest_file_index",
                        return_value=fake_manifest):
            state = evaluate_h3_asset_contract(root, ROOT)
        self.assertFalse(state["ready"])
        self.assertEqual(state["status"], "INCOMPATIBLE_RUNTIME")
        self.assertIn("tokenizer_json", state["mismatched"])
        self.assertEqual(state["groups"]["tokenizer"]["status"], "MISSING")

    def test_manifest_and_installation_contract_use_same_required_list(self):
        manifest = load_h3_sidecar_manifest(ROOT)
        required = {item["logical_component"] for item in self.contract["required"]}
        self.assertIn("tokenizer_json", required)
        self.assertTrue(all(item["required"] is True for item in self.contract["required"]))
        install_text = (ROOT / "configs" / "installation_manifest.yaml").read_text(encoding="utf-8")
        self.assertIn("h3_runtime_asset_contract: configs/h3_sidecar_manifest.yaml#runtime_asset_contract", install_text)
        self.assertIn("MiniMax-H3/FL2VA/text_encoder/tokenizer.json", install_text)
        self.assertIn("runtime_asset_contract", manifest)

    def test_environment_report_exposes_missing_asset_and_not_ready(self):
        root = self._fixture("tokenizer_json")
        with tempfile.TemporaryDirectory() as temp:
            service = EnvironmentService(StudioStore(Path(temp) / "data"))
            report = service._h3_model_status(str(root), str(root))
        self.assertFalse(report["ready"])
        self.assertEqual(report["code"], "INCOMPATIBLE_RUNTIME")
        self.assertIn("tokenizer_json", report["asset_contract"]["missing"])

    def test_installer_does_not_adopt_missing_tokenizer_layout(self):
        root = self._fixture("tokenizer_json")
        with tempfile.TemporaryDirectory() as temp:
            service = InstallationService(
                StudioStore(Path(temp) / "data"), repo_root=ROOT,
                job_root=Path(temp) / "jobs", cache_root=Path(temp) / "cache",
            )
            state = service._h3_sidecar_state(root, verify=True)
        self.assertEqual(state["status"], "FAILED")
        self.assertEqual(state["code"], "INCOMPATIBLE_RUNTIME")
        self.assertIn("tokenizer_json", state["missing"])


if __name__ == "__main__":
    unittest.main()
