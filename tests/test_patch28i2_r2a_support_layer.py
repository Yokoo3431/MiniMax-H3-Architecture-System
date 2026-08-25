"""PATCH2.8-I2-R2A support-layer provenance and capability contracts."""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from apps.architect_video_studio.mock_api.installer_service import InstallationService  # noqa: E402
from apps.architect_video_studio.mock_api.store import StudioStore  # noqa: E402
from apps.architect_video_studio.mock_api.yaml_compat import safe_load  # noqa: E402
from runtime.support_layer import (  # noqa: E402
    FROZEN_CORE_PACKAGES,
    FROZEN_NODE_NAMES,
    dependency_delta,
    load_support_manifest,
    validate_support_entry,
    validate_support_manifest,
)


class TestR2ASupportManifest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = load_support_manifest(SYSTEM_ROOT)

    def test_support_manifest_requires_immutable_commit(self):
        validate_support_manifest(self.manifest)
        for entry in self.manifest["support_layers"].values():
            self.assertRegex(entry["commit"], r"^[0-9a-f]{40}$")

    def test_main_latest_and_branch_only_pins_rejected(self):
        for layer_id, entry in self.manifest["support_layers"].items():
            candidate = copy.deepcopy(entry)
            candidate["commit"] = "main"
            with self.assertRaises(ValueError):
                validate_support_entry(layer_id, candidate)
            candidate = copy.deepcopy(entry)
            candidate["source_archive_url"] = candidate["source_archive_url"].replace(
                candidate["commit"], "main")
            with self.assertRaises(ValueError):
                validate_support_entry(layer_id, candidate)

    def test_exact_sources_and_licenses(self):
        h3 = self.manifest["support_layers"]["minimax_h3_nodes"]
        vhs = self.manifest["support_layers"]["video_helper_suite"]
        self.assertEqual(h3["repository"], "https://github.com/HM-RunningHub/ComfyUI_RH_MinMaxH3.git")
        self.assertEqual(h3["commit"], "d6c5f7b0d4e03936ac4a9834be63ecc6b5637dad")
        self.assertEqual(h3["license"], "Apache-2.0")
        self.assertEqual(vhs["repository"], "https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git")
        self.assertEqual(vhs["commit"], "4ee72c065db22c9d96c2427954dc69e7b908444b")
        self.assertEqual(vhs["license"], "GPL-3.0-only")

    def test_archive_size_and_sha_are_pinned(self):
        for entry in self.manifest["support_layers"].values():
            self.assertGreater(entry["archive_size"], 0)
            self.assertRegex(entry["archive_sha256"], r"^[0-9A-F]{64}$")

    def test_wrong_repository_is_rejected(self):
        candidate = copy.deepcopy(self.manifest["support_layers"]["minimax_h3_nodes"])
        candidate["repository"] = "https://github.com/example/fork.git"
        with self.assertRaises(ValueError):
            validate_support_entry("minimax_h3_nodes", candidate)

    def test_missing_frozen_node_is_rejected(self):
        candidate = copy.deepcopy(self.manifest["support_layers"]["minimax_h3_nodes"])
        candidate["required_nodes"].remove("RHMiniMaxH3ModelLoader")
        with self.assertRaises(ValueError):
            validate_support_entry("minimax_h3_nodes", candidate)

    def test_required_nodes_are_complete_and_exact(self):
        required = set(self.manifest["support_layers"]["minimax_h3_nodes"]["required_nodes"])
        required.add("VHS_VideoCombine")
        self.assertEqual(required, set(FROZEN_NODE_NAMES))

    def test_install_order_runtime_support_before_models(self):
        order = self.manifest["installation_order"]
        self.assertLess(order.index("comfyui_runtime"), order.index("minimax_h3_nodes"))
        self.assertLess(order.index("minimax_h3_nodes"), order.index("support_layer_dependencies"))
        self.assertLess(order.index("support_layer_dependencies"), order.index("models"))

    def test_torch_replacement_is_rejected(self):
        candidate = copy.deepcopy(self.manifest)
        candidate["dependency_policy"]["install_required"].append("torch==0.0.0")
        with self.assertRaises(ValueError):
            validate_support_manifest(candidate)
        self.assertIn("torch", FROZEN_CORE_PACKAGES)

    def test_dependency_delta_marks_transformers_conflict(self):
        delta = dependency_delta(
            {},
            {"transformers": "5.14.1", "torch": "2.13.0+cu130"},
            self.manifest,
        )
        rows = {row["package"]: row for row in delta}
        self.assertEqual(rows["transformers"]["action"], "VERSION_CONFLICT")

    def test_provenance_metadata_contains_production_patch(self):
        patch = self.manifest["support_layers"]["minimax_h3_nodes"]["production_snapshot"]["local_patch"]
        self.assertEqual(patch["applies_to"], self.manifest["support_layers"]["minimax_h3_nodes"]["commit"])
        self.assertRegex(patch["sha256"], r"^[0-9a-f]{64}$")

    def test_no_manual_manager_dependency_or_moving_pin(self):
        node_manifest = json.loads((SYSTEM_ROOT / "configs" / "node_manifest.json").read_text(encoding="utf-8"))
        manager = node_manifest["nodes"]["ComfyUI-Manager"]
        self.assertFalse(manager["required"])
        self.assertEqual(manager["recommended_commit"], None)
        for entry in node_manifest["nodes"].values():
            self.assertNotIn(str(entry.get("recommended_commit")).lower(), {"main", "master", "latest"})


class TestR2AInstallerIntegrationContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = load_support_manifest(SYSTEM_ROOT)

    def test_production_target_is_forbidden_in_manifest(self):
        data = safe_load((SYSTEM_ROOT / "configs" / "installation_manifest.yaml").read_text(encoding="utf-8"))
        self.assertEqual(data["support_layers"]["production_runtime_target"], "forbidden")
        self.assertEqual(data["support_layers"]["production_models_target"], "forbidden")

    def test_isolated_target_is_not_production_path(self):
        text = (SYSTEM_ROOT / "apps/architect_video_studio/mock_api/installer_service.py").read_text(encoding="utf-8")
        self.assertIn("SUPPORT_LAYER_TARGET_EXISTS", text)
        self.assertIn("production_runtime_target", (SYSTEM_ROOT / "configs/installation_manifest.yaml").read_text(encoding="utf-8"))

    def test_pread_contract_remains_present(self):
        text = (SYSTEM_ROOT / "runtime/native_shim/windows_safe_load.py").read_text(encoding="utf-8")
        self.assertIn("H3_WINDOWS_SAFE_LOAD", text)
        self.assertIn("pread", text)

    def test_installer_plan_exposes_pinned_support_layers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = StudioStore(root / "store")
            service = InstallationService(store, repo_root=SYSTEM_ROOT, job_root=root / "jobs", cache_root=root / "cache")
            plan = service.build_install_plan(native_root=str(root / "native"), models_root=str(root / "models"), verify_existing=False)
            ids = [item["component_id"] for item in plan["components"]]
            self.assertIn("minimax_h3_nodes", ids)
            self.assertIn("video_helper_suite", ids)
            self.assertIn("support_layer_dependencies", ids)
            self.assertLess(ids.index("minimax_h3_nodes"), ids.index("dit"))
            self.assertLess(ids.index("video_helper_suite"), ids.index("dit"))

    def test_frozen_workflows_remain_unchanged_and_use_exact_contract(self):
        names = set()
        for path in (SYSTEM_ROOT / "workflows").glob("*.json"):
            data = json.loads(path.read_text(encoding="utf-8"))
            for node in data.get("nodes", []):
                if node.get("type") in FROZEN_NODE_NAMES:
                    names.add(node["type"])
        self.assertTrue({"RHMiniMaxH3ModelLoader", "VHS_VideoCombine"}.issubset(names))
        self.assertNotIn("RHMiniMaxH3DirectModelLoader", names)

    def test_model_download_is_not_part_of_support_source(self):
        for entry in self.manifest["support_layers"].values():
            self.assertNotIn(".safetensors", str(entry.get("source_archive_url")))

    def test_five_native_workflow_assets_exist_and_are_unchanged_json(self):
        registry = json.loads((SYSTEM_ROOT / "configs/rc34_patch27c2b_workflow_registry_validation.json").read_text(encoding="utf-8"))
        for item in registry["workflows"].values():
            path = SYSTEM_ROOT / item["native_asset"]
            self.assertTrue(path.is_file())
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(data.get("nodes"))

    def test_no_developer_absolute_path_in_support_manifest(self):
        text = (SYSTEM_ROOT / "configs/support_layer_manifest.yaml").read_text(encoding="utf-8")
        self.assertNotIn("D:\\\\ProgramFilesNormal", text)
        self.assertNotIn("C:\\\\Users", text)

    def test_third_party_notice_covers_both_layers(self):
        text = (SYSTEM_ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
        self.assertIn("d6c5f7b0d4e03936ac4a9834be63ecc6b5637dad", text)
        self.assertIn("4ee72c065db22c9d96c2427954dc69e7b908444b", text)


if __name__ == "__main__":
    unittest.main()
