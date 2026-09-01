"""Non-GPU tests for the owner-assisted acceptance harness."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.owner_acceptance import (  # noqa: E402
    ApiClient,
    build_parser,
    job_evidence,
    redact_prompt_record,
    redact_provider_catalog,
    safe_path,
)


class OwnerAcceptanceHarnessTests(unittest.TestCase):
    def test_safe_path_keeps_name_but_not_absolute_value(self):
        value = safe_path(r"D:\Owner\Private\renders")
        self.assertEqual(value["name"], "renders")
        self.assertNotIn("Owner", value)
        self.assertEqual(len(value["path_sha256"]), 64)

    def test_prompt_redaction_removes_content(self):
        value = redact_prompt_record({
            "provider": "OFFLINE_COMPILER",
            "optimized_prompt": "private prompt content",
            "original_intent": "private user intent",
            "input_fingerprint": "abc",
            "validator_result": {"pass": True},
        })
        self.assertNotIn("private prompt content", str(value))
        self.assertNotIn("private user intent", str(value))
        self.assertEqual(value["provider"], "OFFLINE_COMPILER")

    def test_provider_catalog_redacts_executable_path(self):
        value = redact_provider_catalog([{
            "id": "CLI_BRIDGE",
            "available": True,
            "configured": True,
            "executable": r"D:\Private\agy.exe",
        }])
        self.assertEqual(value[0]["executable_name"], "agy.exe")
        self.assertNotIn("Private", str(value))
        self.assertEqual(len(value[0]["executable_sha256"]), 64)

    def test_job_evidence_is_bounded_to_control_plane_fields(self):
        value = job_evidence({"id": "job-1", "prompt": "secret", "image": b"secret",
                              "execution_workflow_sha256": "abc", "state": "RUNNING"})
        self.assertEqual(value["id"], "job-1")
        self.assertNotIn("secret", str(value))
        self.assertNotIn("prompt", value)

    def test_capture_accepts_project_id_after_subcommand(self):
        args = build_parser().parse_args(["capture", "--session-id", "s", "--gate", "d",
                                           "--project-id", "proj-1"])
        self.assertEqual(args.project_id, "proj-1")
        self.assertEqual(args.gate, "d")

    def test_api_client_keeps_transport_failures_nonterminal(self):
        value = ApiClient("http://127.0.0.1:1", timeout=0.01).request("GET", "/health")
        self.assertFalse(value["ok"])
        self.assertIn(value["error"], {"ConnectionRefusedError", "URLError", "TimeoutError", "OSError"})


if __name__ == "__main__":
    unittest.main()