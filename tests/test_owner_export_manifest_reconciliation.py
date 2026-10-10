"""CPU-only contracts for additive Owner Export manifest reconciliation."""

from __future__ import annotations

import hashlib
from unittest.mock import patch
import tempfile
import unittest
from pathlib import Path
from urllib.request import Request


def _temporary_directory() -> tempfile.TemporaryDirectory:
    return tempfile.TemporaryDirectory()


from scripts.reconcile_owner_export_manifest import (
    MAX_LIVE_API_BYTES,
    _LoopbackNoRedirect,
    _fetch_live_data,
    ManifestReconciliationError,
    _new_output,
    _sanitize,
    _write_new_file,
    build_reconciled_manifest,
)


def _fixture(root: Path) -> tuple[dict, dict, bytes]:
    content = b"synthetic-sequence-assembly"
    media_path = root / "A9" / "assembly.mp4"
    media_path.parent.mkdir(parents=True)
    media_path.write_bytes(content)
    assembly_sha = hashlib.sha256(content).hexdigest()
    shot_rows = []
    for ordinal in range(5):
        shot_id = f"shot-{ordinal + 1:04d}"
        job_id = f"job-{ordinal + 1:04d}"
        shot_rows.append({
            "shot_id": shot_id,
            "ordinal": ordinal,
            "job_id": job_id,
            "job_state": "COMPLETED",
            "result_media_endpoint": f"/api/jobs/{job_id}/media",
            "size_bytes": 100 + ordinal,
            "range": "206",
        })
    manifest = {
        "schema": "avs-owner-export-manifest/v1",
        "export_created_at": "2026-10-10T12:00:00+08:00",
        "artifact_count": 1,
        "total_bytes": len(content),
        "acceptance_summary": {
            "studio_path": r"D:\Private\internal\video.mp4",
            "prompt": "synthetic private prompt",
            "result": "verified",
        },
        "artifacts": [{
            "stage": "A9 long-form Sequence / Assembly",
            "kind": "assembly",
            "job_or_assembly_id": "assembly-0001",
            "project_id": "project-0001",
            "study_id": "project-0001",
            "queue_id": "queue-0001",
            "sequence_id": "sequence-0001",
            "shot_count": 5,
            "studio_path": r"D:\Private\internal\assembly.mp4",
            "media": {
                "relative_path": "A9/assembly.mp4",
                "size_bytes": len(content),
                "sha256": assembly_sha,
                "width": 1344,
                "height": 768,
                "fps": 24,
                "duration_seconds": 22.3,
                "source_media_endpoint": "/api/projects/project-0001/long-form/queue-0001/media",
            },
        }],
        "A9_sequence_lineage": {
            "project_id": "project-0001",
            "study_id": "project-0001",
            "queue_id": "queue-0001",
            "sequence_id": "sequence-0001",
            "assembly_id": "assembly-0001",
            "status": "READY",
            "shot_count": 5,
            "shot_jobs": shot_rows,
        },
    }
    shots = []
    for ordinal in range(5):
        shot_id = f"shot-{ordinal + 1:04d}"
        job_id = f"job-{ordinal + 1:04d}"
        shots.append({
            "shot_id": shot_id,
            "ordinal": ordinal,
            "state": "RESULT_READY",
            "job_identity": {
                "job_id": job_id,
                "prompt_id": f"prompt-{ordinal + 1:04d}",
                "workflow_sha256": "a" * 64,
                "runtime_id": "production-h3-test",
            },
            "result_identity": {
                "result_id": f"result:{job_id}",
                "media_sha256": hashlib.sha256(job_id.encode()).hexdigest(),
                "width": 1344,
                "height": 768,
                "fps": 24,
                "duration_seconds": 4.46,
                "audio_stream": True,
            },
        })
    live = {"queues": [{
        "project_id": "project-0001",
        "queue_id": "queue-0001",
        "director_sequence_id": "sequence-0001",
        "status": "READY",
        "shots": shots,
        "assembly": {
            "assembly_id": "assembly-0001",
            "status": "READY",
            "output_sha256": assembly_sha,
            "size_bytes": len(content),
        },
    }]}
    return manifest, live, content


class OwnerExportManifestReconciliationTests(unittest.TestCase):
    def test_reconciles_all_five_a9_result_identities_and_relative_media(self):
        with _temporary_directory() as temporary:
            root = Path(temporary)
            manifest, live, _ = _fixture(root)
            result = build_reconciled_manifest(
                manifest, root, live, parent_sha256="b" * 64,
                reconciled_at_utc="2026-10-10T04:00:00Z")

        self.assertEqual(result["schema"], "avs-owner-export-manifest/v2")
        self.assertEqual(result["total_bytes"], len(b"synthetic-sequence-assembly"))
        self.assertEqual(result["A9_sequence_lineage"]["shot_count"], 5)
        self.assertEqual(
            [item["result_id"] for item in result["A9_sequence_lineage"]["shot_jobs"]],
            [f"result:job-{index:04d}" for index in range(1, 6)],
        )
        self.assertTrue(all(len(item["media_sha256"]) == 64
                            for item in result["A9_sequence_lineage"]["shot_jobs"]))
        self.assertEqual(result["artifacts"][0]["media"]["relative_path"],
                         "A9/assembly.mp4")
        self.assertNotIn("studio_path", str(result))
        self.assertNotIn("synthetic private prompt", str(result))
        self.assertEqual(len(result["manifest_sha256"]), 64)

    def test_rejects_media_hash_mismatch(self):
        with _temporary_directory() as temporary:
            root = Path(temporary)
            manifest, live, _ = _fixture(root)
            manifest["artifacts"][0]["media"]["sha256"] = "c" * 64
            with self.assertRaisesRegex(ManifestReconciliationError, "MEDIA_SHA_MISMATCH"):
                build_reconciled_manifest(manifest, root, live,
                                          parent_sha256="b" * 64)

    def test_rejects_absolute_and_parent_traversal_media_paths(self):
        with _temporary_directory() as temporary:
            root = Path(temporary)
            manifest, live, _ = _fixture(root)
            for value in (r"D:\Owner\A9\assembly.mp4", "../outside.mp4"):
                manifest["artifacts"][0]["media"]["relative_path"] = value
                with self.subTest(path_kind="absolute" if ":" in value else "traversal"):
                    with self.assertRaises(ManifestReconciliationError):
                        build_reconciled_manifest(manifest, root, live,
                                                  parent_sha256="b" * 64)

    def test_rejects_missing_or_mismatched_a9_result_identity(self):
        with _temporary_directory() as temporary:
            root = Path(temporary)
            manifest, live, _ = _fixture(root)
            live["queues"][0]["shots"][2]["result_identity"]["media_sha256"] = "bad"
            with self.assertRaisesRegex(
                    ManifestReconciliationError, "A9_SHOT_RESULT_IDENTITY_INCOMPLETE"):
                build_reconciled_manifest(manifest, root, live,
                                          parent_sha256="b" * 64)

    def test_rejects_wrong_assembly_identity(self):
        with _temporary_directory() as temporary:
            root = Path(temporary)
            manifest, live, _ = _fixture(root)
            live["queues"][0]["assembly"]["assembly_id"] = "assembly-other"
            with self.assertRaisesRegex(ManifestReconciliationError,
                                        "A9_QUEUE_NOT_UNIQUE|A9_IDENTITY_MISMATCH"):
                build_reconciled_manifest(manifest, root, live,
                                          parent_sha256="b" * 64)

    def test_new_output_is_confined_and_never_overwrites(self):
        with _temporary_directory() as temporary:
            root = Path(temporary)
            existing = root / "manifest.json"
            existing.write_text("old", encoding="utf-8")
            self.assertEqual(_new_output(root, Path("manifest.reconciled.v2.json")),
                             root / "manifest.reconciled.v2.json")
            with self.assertRaisesRegex(ManifestReconciliationError,
                                        "SOURCE_MANIFEST_IMMUTABLE"):
                _new_output(root, Path("manifest.json"))
            (root / "already-created.json").write_text("existing", encoding="utf-8")
            with self.assertRaisesRegex(ManifestReconciliationError,
                                        "OUTPUT_ALREADY_EXISTS"):
                _new_output(root, Path("already-created.json"))
            with self.assertRaisesRegex(ManifestReconciliationError,
                                        "OUTPUT_PATH_OUTSIDE_EXPORT_ROOT"):
                _new_output(root, root.parent / "outside.json")
            output = root / "new.json"
            _write_new_file(output, {"version": 2})
            with self.assertRaisesRegex(ManifestReconciliationError,
                                        "OUTPUT_ALREADY_EXISTS"):
                _write_new_file(output, {"version": 3})
            self.assertEqual(existing.read_text(encoding="utf-8"), "old")
            self.assertIn('"version": 2', output.read_text(encoding="utf-8"))

    def test_rejects_exported_a9_shot_with_mismatched_live_result_hash(self):
        with _temporary_directory() as temporary:
            root = Path(temporary)
            manifest, live, _ = _fixture(root)
            shot_media = root / "A9" / "shot-1.mp4"
            shot_media.write_bytes(b"job-0001")
            manifest["artifacts"].append({
                "stage": "A9 shot",
                "kind": "native",
                "job_or_assembly_id": "job-0001",
                "result_id": "result:job-0001",
                "media": {
                    "relative_path": "A9/shot-1.mp4",
                    "size_bytes": shot_media.stat().st_size,
                    "sha256": hashlib.sha256(b"job-0001").hexdigest(),
                },
            })
            manifest["total_bytes"] += shot_media.stat().st_size
            live["queues"][0]["shots"][0]["result_identity"]["media_sha256"] = "c" * 64
            with self.assertRaisesRegex(ManifestReconciliationError,
                                        "A9_EXPORTED_SHOT_MEDIA_MISMATCH"):
                build_reconciled_manifest(manifest, root, live,
                                          parent_sha256="b" * 64)

    def test_sanitizes_embedded_absolute_paths_and_endpoint_query_strings(self):
        result = _sanitize({
            "note": r"Recovered from C:\Users\Owner\Private Export\clip.mp4",
            "endpoint": "/api/jobs/job-0001/media?access_token=synthetic-secret",
        })
        self.assertEqual(result["note"], "[local path omitted]")
        self.assertEqual(result["endpoint"], "/api/jobs/job-0001/media")
        self.assertNotIn("Owner", str(result))
        self.assertNotIn("synthetic-secret", str(result))

    def test_loopback_http_redirects_are_refused(self):
        request = Request("http://127.0.0.1/api/projects/project-0001/long-form")
        handler = _LoopbackNoRedirect()
        self.assertIsNone(handler.redirect_request(
            request, None, 302, "Found", {}, "https://example.invalid/collect"))

    def test_live_api_response_is_bounded(self):
        class OversizedResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, size):
                return b"x" * size

        class FakeOpener:
            def open(self, request, timeout):
                return OversizedResponse()

        with patch("scripts.reconcile_owner_export_manifest.build_opener",
                   return_value=FakeOpener()):
            with self.assertRaisesRegex(
                    ManifestReconciliationError, "A9_LIVE_API_RESPONSE_TOO_LARGE"):
                _fetch_live_data("http://127.0.0.1:8788", "project-0001")
        self.assertEqual(MAX_LIVE_API_BYTES, 2 * 1024 * 1024)

    def test_live_shots_are_returned_in_explicit_ordinal_order(self):
        with _temporary_directory() as temporary:
            root = Path(temporary)
            manifest, live, _ = _fixture(root)
            live["queues"][0]["shots"].reverse()
            result = build_reconciled_manifest(
                manifest, root, live, parent_sha256="b" * 64,
                reconciled_at_utc="2026-10-10T04:00:00Z")
        self.assertEqual(
            [item["job_id"] for item in result["A9_sequence_lineage"]["shot_jobs"]],
            [f"job-{index:04d}" for index in range(1, 6)],
        )

    def test_rejects_duplicate_or_invalid_shot_ordinal_and_unsafe_identity(self):
        with _temporary_directory() as temporary:
            root = Path(temporary)
            manifest, live, _ = _fixture(root)
            live["queues"][0]["shots"][1]["ordinal"] = 0
            with self.assertRaisesRegex(
                    ManifestReconciliationError, "A9_SHOT_ORDINAL_INVALID"):
                build_reconciled_manifest(manifest, root, live,
                                          parent_sha256="b" * 64)
        with _temporary_directory() as temporary:
            root = Path(temporary)
            manifest, live, _ = _fixture(root)
            live["queues"][0]["shots"][0]["job_identity"]["prompt_id"] = "../prompt"
            with self.assertRaisesRegex(
                    ManifestReconciliationError,
                    "A9_SHOT_RESULT_IDENTITY_INCOMPLETE"):
                build_reconciled_manifest(manifest, root, live,
                                          parent_sha256="b" * 64)


if __name__ == "__main__":
    unittest.main()
