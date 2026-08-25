"""RC3.4 PATCH2.7-C1 - Native Runtime Adapter contract tests.

Contract-only tests for runtime/contracts/native_runtime_contract.yaml:
1. contract schema valid
2. request mapping valid
3. event format valid
4. error mapping valid
5. output contract compatible with PATCH2.7-A VideoGenerationOutput
6. no import: ComfyUI / CUDA / torch / model
"""

import sys
import unittest
from pathlib import Path

from runtime.yaml_compat import safe_load

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

CONTRACT = SYSTEM_ROOT / "runtime" / "contracts" / "native_runtime_contract.yaml"
PATCH27A_CONTRACT = SYSTEM_ROOT / "runtime" / "contracts" / "video_generation_request.yaml"


def load_contract(path: Path = CONTRACT):
    return safe_load(path.read_text(encoding="utf-8"))


def validate_event(event: dict, contract: dict) -> list:
    """Contract rule: runtime_event format (normalized, not node-bound)."""
    errors = []
    for key in ("job_id", "stage", "progress", "message", "timestamp"):
        if key not in event:
            errors.append(f"event missing {key}")
    allowed = contract["runtime_event"]["stage"]["allowed"]
    if event.get("stage") not in allowed:
        errors.append(f"invalid stage {event.get('stage')!r}")
    progress = event.get("progress")
    if not (isinstance(progress, (int, float)) and 0 <= progress <= 100):
        errors.append(f"progress out of range: {progress!r}")
    return errors


class TestContractSchema(unittest.TestCase):
    def test_contract_loads_with_required_sections(self):
        contract = load_contract()
        for section in ("meta", "native_runtime_request", "native_runtime_response",
                        "runtime_event", "runtime_error", "error_mapping",
                        "native_output", "rules"):
            self.assertIn(section, contract, section)

    def test_meta_dependencies(self):
        contract = load_contract()
        deps = contract["meta"]["depends_on"]
        self.assertTrue(any("PATCH2.7-A" in d for d in deps))
        self.assertTrue(any("PATCH2.7-B" in d for d in deps))


class TestRequestMapping(unittest.TestCase):
    def test_native_runtime_request_fields(self):
        req = load_contract()["native_runtime_request"]
        for key in ("job_id", "study_id", "workflow_asset", "translated_payload", "control"):
            self.assertIn(key, req, key)
        payload = req["translated_payload"]
        for key in ("inputs", "video", "generation", "camera", "workflow", "output", "gates"):
            self.assertIn(key, payload, key)
        self.assertIn("prompt", payload["inputs"])
        self.assertIn("references", payload["inputs"])
        for key in ("submit_timeout_seconds", "poll_interval_seconds", "history_timeout_seconds"):
            self.assertIn(key, req["control"], key)

    def test_prompt_is_reference_not_authoring(self):
        payload = load_contract()["native_runtime_request"]["translated_payload"]
        self.assertIn("prompt", payload["inputs"])
        rules = " ".join(load_contract()["rules"])
        self.assertIn("never be bypassed", rules.lower())


class TestEventFormat(unittest.TestCase):
    def test_valid_event_passes(self):
        contract = load_contract()
        event = {
            "job_id": "job-1",
            "stage": "SAMPLING",
            "progress": 42,
            "message": "sampling",
            "timestamp": "2026-08-15T12:00:00Z",
        }
        self.assertEqual(validate_event(event, contract), [])

    def test_invalid_stage_rejected(self):
        contract = load_contract()
        event = {
            "job_id": "job-1", "stage": "MELTING", "progress": 50,
            "message": "x", "timestamp": "t",
        }
        self.assertTrue(any("invalid stage" in e for e in validate_event(event, contract)))

    def test_progress_out_of_range_rejected(self):
        contract = load_contract()
        event = {
            "job_id": "job-1", "stage": "QUEUED", "progress": 150,
            "message": "x", "timestamp": "t",
        }
        self.assertTrue(any("progress" in e for e in validate_event(event, contract)))

    def test_stage_enum_matches_runtime_contract(self):
        stages = set(load_contract()["runtime_event"]["stage"]["allowed"])
        self.assertEqual(stages, {"QUEUED", "PREPARING", "LOADING_MODEL", "SAMPLING",
                                  "ENCODING", "EXPORTING", "COMPLETED", "FAILED",
                                  "CANCELLED"})


class TestErrorMapping(unittest.TestCase):
    def test_refined_error_codes(self):
        err = load_contract()["runtime_error"]
        codes = set(err["error_code"]["allowed"])
        self.assertEqual(codes, {"MODEL_LOAD_ERROR", "WORKFLOW_EXECUTION_ERROR",
                                 "RESOURCE_ERROR", "TIMEOUT_ERROR", "OUTPUT_ERROR",
                                 "CANCELLED"})

    def test_error_mapping_to_existing_job_status(self):
        mapping = load_contract()["error_mapping"]
        expected = {
            "MODEL_LOAD_ERROR": "GPU_FAILED",
            "WORKFLOW_EXECUTION_ERROR": "GPU_FAILED",
            "RESOURCE_ERROR": "GPU_FAILED",
            "TIMEOUT_ERROR": "FAILED",
            "OUTPUT_ERROR": "FAILED",
            "CANCELLED": "GPU_FAILED",
        }
        for code, status in expected.items():
            self.assertEqual(mapping[code], status, code)
        for target in mapping.values():
            self.assertIn(target, {"FAILED", "GPU_FAILED"})


class TestOutputCompatibility(unittest.TestCase):
    def test_output_keeps_patch27a_fields(self):
        native = load_contract()["native_output"]
        for field in ("job_id", "video_path", "preview_path", "metadata", "runtime_info"):
            self.assertIn(field, native, field)
        self.assertIn("provenance", native)

    def test_metadata_aligns_with_patch27a(self):
        native_meta = set(load_contract()["native_output"]["metadata"])
        patch27a = safe_load(PATCH27A_CONTRACT.read_text(encoding="utf-8"))
        request_fields = set(patch27a["video_generation_request"]["generation_parameters"]
                             .get("fields", {}))
        # seed/prompt_hash etc. must be present in native metadata
        for key in ("study_id", "workflow_id", "camera_motion", "resolution",
                    "fps", "duration", "quality", "seed", "prompt_hash"):
            self.assertIn(key, native_meta, key)


class TestNoForbiddenImports(unittest.TestCase):
    def test_test_module_no_forbidden_imports(self):
        source = Path(__file__).read_text(encoding="utf-8")
        import_lines = [l.strip() for l in source.splitlines()
                        if l.strip().startswith(("import ", "from "))]
        for forbidden in ("comfy", "torch", "cuda", "safetensors", "cv2", "model"):
            self.assertFalse(
                any(forbidden in l.lower() for l in import_lines),
                f"forbidden import token {forbidden!r} in {import_lines}",
            )

    def test_contract_has_no_runtime_imports(self):
        text = CONTRACT.read_text(encoding="utf-8")
        self.assertNotIn("import ", text)
        self.assertNotIn("torch", text.lower())
        self.assertNotIn("cuda", text.lower())


if __name__ == "__main__":
    unittest.main()
