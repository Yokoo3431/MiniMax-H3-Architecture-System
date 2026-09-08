"""Contract tests for the Native ComfyUI H3 workflow handoff."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from apps.architect_video_studio.mock_api.workflow_handoff import (
    WorkflowHandoffError,
    build_ui_workflow,
)
from apps.architect_video_studio.mock_api.environment_service import _workflow_identity_diff
from runtime.adapters.production_workflow_binding import workflow_identity_projection


ROOT = Path(__file__).resolve().parent.parent


class TestNativeH3WorkflowBridge(unittest.TestCase):
    def test_api_snapshot_is_bound_to_native_ui_topology(self):
        api = json.loads(
            (ROOT / "production_workflows" / "golden" / "04_Drone_Aerial.json")
            .read_text(encoding="utf-8"))
        ui = build_ui_workflow(
            "04_Drone_Aerial", api, job_id="job-1", snapshot_id="snap-1",
            workflow_hash="a" * 64)

        self.assertEqual(len(ui["nodes"]), 15)
        self.assertEqual(ui["extra"]["architect_video_studio_h3"]["snapshot_id"], "snap-1")
        self.assertEqual(ui["nodes"][5]["widgets_values"][0], "__OFFICIAL_H3_PROMPT__")
        self.assertEqual(ui["nodes"][5]["widgets_values"][1:4], [1344, 768, 107])
        self.assertEqual([item["link"] for item in ui["nodes"][5]["inputs"]], [1, 2, 3])
        self.assertEqual([item["link"] for item in ui["nodes"][9]["inputs"]], [5, 6])
        self.assertEqual([item["link"] for item in ui["nodes"][11]["inputs"]], [12, 17])
        self.assertEqual([item["link"] for item in ui["nodes"][12]["inputs"]], [13, 18])
        self.assertEqual(len(ui["links"]), 18)
        self.assertEqual(ui["nodes"][14]["widgets_values"][0], "video/04_Drone_Aerial")

    def test_bridge_owns_binding_and_verification(self):
        bridge = (ROOT / "runtime" / "native_shim" /
                  "architect_video_studio_h3_bridge" / "web" /
                  "architect_video_studio_h3_bridge.js").read_text(encoding="utf-8")
        self.assertIn("app.registerExtension", bridge)
        self.assertIn("async function bindExactWorkflow", bridge)
        self.assertIn("module.A || module.useWorkflowStore", bridge)
        self.assertNotIn("module.useWorkflowStore || module.nt", bridge)
        self.assertIn("async function waitForComfyReady", bridge)
        self.assertIn("setTimeout(() =>", bridge)
        self.assertNotIn("return window.__avsH3BridgePromise", bridge)
        self.assertIn("service.openWorkflow", bridge)
        self.assertIn("service.openWorkflow(workflow, { force: true })", bridge)
        self.assertNotIn("app.loadGraphData(data.ui_workflow", bridge)
        self.assertIn("stale persisted H3 graph; rebinding", bridge)
        self.assertIn("app.graphToPrompt", bridge)
        self.assertIn("/api/system/verify-workflow", bridge)
        self.assertNotIn("localStorage.clear", bridge)

    def test_invalid_api_link_is_rejected(self):
        api = json.loads(
            (ROOT / "production_workflows" / "golden" / "04_Drone_Aerial.json")
            .read_text(encoding="utf-8"))
        api["12"]["inputs"]["vae"] = ["missing-node", 0]
        with self.assertRaises(WorkflowHandoffError):
            build_ui_workflow("04_Drone_Aerial", api)

    def test_identity_diff_is_bounded_and_does_not_expose_string_values(self):
        expected = {"1": {"inputs": {"prompt": "secret prompt"}}}
        actual = {"1": {"inputs": {}}}
        diff = _workflow_identity_diff(expected, actual)
        self.assertEqual(diff["inputs"][0]["actual"], {"kind": "missing"})
        self.assertNotIn("secret prompt", json.dumps(diff))

    def test_identity_diff_normalizes_node_keys_and_fingerprints_arrays(self):
        expected = {1: {"inputs": {"value": ["alpha", "beta"]}}}
        actual = {"1": {"inputs": {"value": ["alpha", "beta"]}}}
        diff = _workflow_identity_diff(expected, actual)
        self.assertEqual(diff["inputs"], [])
        expected[1]["inputs"]["link"] = ["4", 0]
        actual["1"]["inputs"]["link"] = ["other", "slot"]
        diff = _workflow_identity_diff(expected, actual)
        self.assertEqual(diff["inputs"][0]["expected"]["kind"], "link")
        self.assertEqual(diff["inputs"][0]["actual"]["kind"], "list")

    def test_identity_projection_matches_comfy_defaults_and_js_numbers(self):
        expected = {
            "2": {"class_type": "CLIPLoader", "inputs": {
                "clip_name": "clip.safetensors", "type": "minimax",
            }},
            "8": {"class_type": "BasicScheduler", "inputs": {"denoise": 1.0}},
            "14": {"class_type": "CreateVideo", "inputs": {"fps": 24.0}},
        }
        actual = {
            2: {"class_type": "CLIPLoader", "inputs": {
                "clip_name": "clip.safetensors", "type": "minimax", "device": "default",
            }, "_meta": {"title": "CLIP Loader"}},
            8: {"class_type": "BasicScheduler", "inputs": {"denoise": 1}},
            14: {"class_type": "CreateVideo", "inputs": {"fps": 24, "bit_depth": 8}},
        }
        self.assertEqual(workflow_identity_projection(expected),
                         workflow_identity_projection(actual))

    def test_identity_projection_does_not_mask_linked_optional_inputs(self):
        expected = {
            "2": {"class_type": "CLIPLoader", "inputs": {
                "device": ["9", 0],
            }},
            "14": {"class_type": "CreateVideo", "inputs": {
                "bit_depth": ["10", 0],
            }},
        }
        actual = {
            "2": {"class_type": "CLIPLoader", "inputs": {}},
            "14": {"class_type": "CreateVideo", "inputs": {}},
        }
        projected_expected = workflow_identity_projection(expected)
        projected_actual = workflow_identity_projection(actual)
        self.assertNotEqual(projected_expected, projected_actual)
        self.assertEqual(expected["2"]["inputs"]["device"], ["9", 0])
        self.assertEqual(expected["14"]["inputs"]["bit_depth"], ["10", 0])

    def test_desktop_shell_does_not_execute_graph_handoff(self):
        shell = (ROOT / "launcher" / "DesktopShell.cs").read_text(encoding="utf-8")
        self.assertIn("Comfy handoff delegated to the Comfy-side H3 Bridge", shell)
        self.assertIn("return;", shell)


if __name__ == "__main__":
    unittest.main()
