"""Non-GPU tests for the owner-assisted acceptance harness."""

import sys
import unittest
import json
import io
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.owner_acceptance import (  # noqa: E402
    ApiClient,
    build_parser,
    capture_gate,
    job_evidence,
    redact_prompt_record,
    redact_provider_catalog,
    safe_evidence_file,
    safe_path,
)


class OwnerAcceptanceHarnessTests(unittest.TestCase):
    def test_safe_path_keeps_name_but_not_absolute_value(self):
        value = safe_path(r"D:\Owner\Private\renders")
        self.assertEqual(value["name"], "renders")
        self.assertNotIn("Owner", value)
        self.assertEqual(len(value["path_sha256"]), 64)

    def test_evidence_file_identity_never_contains_the_path(self):
        path = r"D:\Users\Owner\Private\synthetic-screen.png"
        value = safe_evidence_file(path)
        self.assertEqual(value["provided"], True)
        self.assertNotIn(path, str(value))
        self.assertNotIn("Owner", str(value))
        self.assertEqual(len(value["path_sha256"]), 64)

    def test_evidence_file_absence_stays_absent(self):
        self.assertIsNone(safe_evidence_file(None))

    def test_capture_gate_redacts_evidence_path_in_persisted_report(self):
        with tempfile.TemporaryDirectory() as temp:
            report_root = Path(temp)
            report_dir = report_root / "synthetic-session"
            report_dir.mkdir()
            (report_dir / "session.json").write_text("{}", encoding="utf-8")
            owner_path = str(report_root / "Owner Data" / "screen.png")
            args = build_parser().parse_args([
                "--report-dir", str(report_root), "capture",
                "--session-id", "synthetic-session", "--gate", "e",
                "--evidence-file", owner_path,
            ])
            with redirect_stdout(io.StringIO()):
                self.assertEqual(capture_gate(args), 0)
            record = json.loads((report_dir / "gate_e.json").read_text(encoding="utf-8"))
            self.assertNotIn(owner_path, json.dumps(record))
            self.assertNotIn("Owner Data", json.dumps(record))
            self.assertEqual(
                len(record["evidence"]["owner_evidence_file"]["path_sha256"]), 64)

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
