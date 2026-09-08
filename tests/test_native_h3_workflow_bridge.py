"""Contract tests for the Native ComfyUI H3 workflow handoff."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from apps.architect_video_studio.mock_api.workflow_handoff import (
    WorkflowHandoffError,
    build_ui_workflow,
)


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
        self.assertIn("app.loadGraphData(data.ui_workflow, true, true, workflow", bridge)
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

    def test_desktop_shell_does_not_execute_graph_handoff(self):
        shell = (ROOT / "launcher" / "DesktopShell.cs").read_text(encoding="utf-8")
        self.assertIn("Comfy handoff delegated to the Comfy-side H3 Bridge", shell)
        self.assertIn("return;", shell)


if __name__ == "__main__":
    unittest.main()
