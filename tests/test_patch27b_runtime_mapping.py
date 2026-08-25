"""RC3.4 PATCH2.7-B - Runtime Workflow Mapping contract tests.

Contract-only tests for runtime/contracts/workflow_mapping.yaml:
1. workflow registry loads
2. 01-05 workflows all exist
3. display_name mapping correct
4. camera support relations correct
5. unknown workflow rejected
6. no GPU / CUDA / ComfyUI / model imports
"""

import sys
import unittest
from pathlib import Path

from runtime.yaml_compat import safe_load

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

CONTRACT = SYSTEM_ROOT / "runtime" / "contracts" / "workflow_mapping.yaml"

FROZEN_WORKFLOWS = [
    "01_Exterior_Hero",
    "02_Day_Night_Transition",
    "03_Material_Detail",
    "04_Drone_Aerial",
    "05_Slow_Walkthrough",
]

EXPECTED_DISPLAY_NAMES = {
    "01_Exterior_Hero": "Architecture Presentation",
    "02_Day_Night_Transition": "Day Night",
    "03_Material_Detail": "Material Detail",
    "04_Drone_Aerial": "Drone Reveal",
    "05_Slow_Walkthrough": "Slow Walkthrough",
}


def load_registry():
    return safe_load(CONTRACT.read_text(encoding="utf-8"))


def lookup(registry, workflow_id):
    """Contract rule: unknown workflow_id must be rejected."""
    if workflow_id not in registry["workflow_registry"]:
        raise KeyError(f"unknown workflow_id: {workflow_id}")
    return registry["workflow_registry"][workflow_id]


class TestWorkflowRegistry(unittest.TestCase):
    def test_registry_loads(self):
        registry = load_registry()
        for section in ("meta", "workflow_registry", "allowed_camera_motions",
                        "parameter_mapping", "error_mapping", "rules"):
            self.assertIn(section, registry, section)

    def test_all_01_05_workflows_exist(self):
        registry = load_registry()
        for wf in FROZEN_WORKFLOWS:
            self.assertIn(wf, registry["workflow_registry"], wf)
        self.assertEqual(
            set(registry["workflow_registry"]), set(FROZEN_WORKFLOWS))

    def test_display_name_mapping_correct(self):
        registry = load_registry()
        for wf, name in EXPECTED_DISPLAY_NAMES.items():
            self.assertEqual(registry["workflow_registry"][wf]["display_name"], name)

    def test_required_registry_fields(self):
        registry = load_registry()
        for wf in FROZEN_WORKFLOWS:
            entry = registry["workflow_registry"][wf]
            for field in ("display_name", "native_asset", "input_mode",
                          "supported_input", "supported_camera", "output_contract"):
                self.assertIn(field, entry, f"{wf} missing {field}")

    def test_native_asset_references_exist(self):
        registry = load_registry()
        for wf in FROZEN_WORKFLOWS:
            asset = registry["workflow_registry"][wf]["native_asset"]
            path = SYSTEM_ROOT / asset
            self.assertTrue(path.is_file(), f"{wf} native asset missing: {asset}")


class TestCameraSupport(unittest.TestCase):
    def test_camera_support_relations(self):
        registry = load_registry()
        reg = registry["workflow_registry"]
        self.assertIn("slow_push", reg["01_Exterior_Hero"]["supported_camera"])
        self.assertIn("static", reg["02_Day_Night_Transition"]["supported_camera"])
        self.assertIn("static", reg["03_Material_Detail"]["supported_camera"])
        self.assertIn("aerial_reveal", reg["04_Drone_Aerial"]["supported_camera"])
        self.assertIn("walkthrough", reg["05_Slow_Walkthrough"]["supported_camera"])

    def test_supported_cameras_within_allowed_enum(self):
        registry = load_registry()
        allowed = set(registry["allowed_camera_motions"])
        for wf in FROZEN_WORKFLOWS:
            for cam in registry["workflow_registry"][wf]["supported_camera"]:
                self.assertIn(cam, allowed, f"{wf} camera {cam}")

    def test_input_mode_and_roles(self):
        registry = load_registry()
        reg = registry["workflow_registry"]
        self.assertEqual(reg["02_Day_Night_Transition"]["input_mode"], "FL2VA")
        self.assertEqual(reg["02_Day_Night_Transition"]["supported_input"],
                         ["first_frame", "last_frame"])
        for wf in ("01_Exterior_Hero", "03_Material_Detail",
                   "04_Drone_Aerial", "05_Slow_Walkthrough"):
            self.assertEqual(reg[wf]["input_mode"], "I2VA")


class TestUnknownWorkflow(unittest.TestCase):
    def test_unknown_workflow_rejected(self):
        registry = load_registry()
        self.assertNotIn("99_Unknown", registry["workflow_registry"])
        with self.assertRaises(KeyError):
            lookup(registry, "99_Unknown")

    def test_lookup_known_workflow(self):
        registry = load_registry()
        entry = lookup(registry, "05_Slow_Walkthrough")
        self.assertEqual(entry["display_name"], "Slow Walkthrough")


class TestParameterAndErrorMapping(unittest.TestCase):
    def test_parameter_mapping_contract(self):
        registry = load_registry()
        pm = registry["parameter_mapping"]
        self.assertEqual(pm["camera_motion"], "payload.camera.motion")
        self.assertEqual(pm["workflow_id"], "payload.workflow.id")
        for field in ("resolution", "fps", "duration", "seed", "quality"):
            self.assertIn(field, pm["generation_parameters"], field)

    def test_error_mapping_statuses(self):
        registry = load_registry()
        em = registry["error_mapping"]
        self.assertEqual(em["WORKFLOW_NOT_FOUND"], "FAILED")
        self.assertEqual(em["NODE_EXECUTION_FAILED"], "GPU_FAILED")
        self.assertEqual(em["OUT_OF_MEMORY"], "GPU_FAILED")
        self.assertEqual(em["TIMEOUT"], "FAILED")
        self.assertEqual(em["CANCELLED"], "GPU_FAILED")
        self.assertEqual(em["COMPLETED_OK"], "COMPLETED")
        for target in em.values():
            self.assertIn(target, {"FAILED", "GPU_FAILED", "COMPLETED"})


class TestNoForbiddenImports(unittest.TestCase):
    def test_test_module_imports_are_stdlib_only(self):
        source = Path(__file__).read_text(encoding="utf-8")
        import_lines = [l.strip() for l in source.splitlines()
                        if l.strip().startswith(("import ", "from "))]
        for forbidden in ("torch", "comfy", "safetensors", "cuda", "cv2", "numpy"):
            self.assertFalse(
                any(forbidden in l.lower() for l in import_lines),
                f"forbidden import token {forbidden!r} in {import_lines}",
            )

    def test_contract_has_no_gpu_cuda_imports(self):
        text = CONTRACT.read_text(encoding="utf-8")
        self.assertNotIn("import ", text)
        self.assertNotIn("torch", text.lower())
        self.assertNotIn("cuda", text.lower())


if __name__ == "__main__":
    unittest.main()
