"""A5.1 result-pipeline identity, recovery, and privacy regressions (CPU-only)."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.request
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from apps.architect_video_studio.mock_api.job_api import JobAPI  # noqa: E402
from apps.architect_video_studio.mock_api.output_api import OutputAPI  # noqa: E402
from apps.architect_video_studio.mock_api.project_api import ProjectAPI  # noqa: E402
from apps.architect_video_studio.mock_api.server import StudioServer  # noqa: E402
from apps.architect_video_studio.mock_api.store import StudioStore  # noqa: E402
from runtime.adapters.comfyui_client import (  # noqa: E402
    ComfyUIClient, ComfyUIExecutionError,
)
from runtime.adapters.native_runtime_adapter import NativeRuntimeAdapter  # noqa: E402
from runtime.adapters.production_workflow_binding import (  # noqa: E402
    canonical_workflow_sha256,
)
from runtime.result_pipeline import (  # noqa: E402
    ResultIdentityError, classify_result_failure, expected_save_video_identity,
    sanitize_result_error, select_history_video,
)


class RecoveryAdapter:
    def __init__(self, client):
        self.client = client
        self.generate_calls = 0

    def generate(self, *_args, **_kwargs):
        self.generate_calls += 1
        raise AssertionError("recovery must never resubmit generation")


class RecoveryHarness:
    def __init__(self, *, history_override=None, runtime_port=8190):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = StudioStore(self.root / "data")
        self.project_id = ProjectAPI(self.store).create_project("Recovery Fixture")["id"]
        self.output_root = self.root / "isolated-runtime-output"
        self.output_root.mkdir()
        self.job_id = "job-a5-recovery"
        self.prompt_id = "prompt-a5-001"
        self.prefix = f"video/04_Drone_Aerial_{self.job_id}"
        self.filename = f"04_Drone_Aerial_{self.job_id}_00001.mp4"
        self.media = self.output_root / "video" / self.filename
        self.media.parent.mkdir(parents=True)
        self.media.write_bytes(b"synthetic-mp4-bytes-for-range-test")
        self.graph = {
            "15": {
                "class_type": "SaveVideo",
                "inputs": {
                    "filename_prefix": self.prefix,
                    "format": "auto",
                    "codec": "auto",
                    "video": ["14", 0],
                },
            },
        }
        self.workflow_sha = canonical_workflow_sha256(self.graph)
        self.expected = expected_save_video_identity(
            self.graph, self.job_id, self.workflow_sha)
        self.history = {
            "prompt_id": self.prompt_id,
            "status": {"status_str": "success", "completed": True},
            "outputs": {
                "15": {
                    "videos": [{
                        "filename": self.filename,
                        "subfolder": "video",
                        "type": "output",
                        "format": "video/h264-mp4",
                        "size": self.media.stat().st_size,
                    }],
                },
            },
        }
        if history_override:
            self.history = history_override(self.history)
        self.client = ComfyUIClient(
            base_url=f"http://127.0.0.1:{runtime_port}",
            output_root=str(self.output_root), strict_output=False)
        self.client.get_history = self._get_history
        self.client.list_history = lambda: (_ for _ in ()).throw(
            AssertionError("recovery must not search global/latest history"))
        self.submit_calls = 0
        self.client.submit_workflow = self._submit_forbidden
        self.history_calls = 0
        self.adapter = RecoveryAdapter(self.client)
        self.output_api = OutputAPI(self.store, allow_mock_outputs=False)
        self.jobs = JobAPI(
            self.store, output_api=self.output_api,
            experimental_runtime_adapter=self.adapter)
        self._create_failed_job()

    def _get_history(self, prompt_id):
        self.history_calls += 1
        if prompt_id != self.prompt_id:
            raise AssertionError("recovery queried a different prompt")
        return dict(self.history)

    def _submit_forbidden(self, *_args, **_kwargs):
        self.submit_calls += 1
        raise AssertionError("result recovery must not call /prompt")

    def _create_failed_job(self):
        project = self.store.load_project(self.project_id)
        project["state"] = "GPU_RUNNING"
        self.store.save_project(project)
        guide_bindings = []
        guide_refs = {}
        for ordinal, frame_idx in enumerate((36, 72), start=1):
            asset_id = f"guide-fixture-{ordinal}"
            filename = f"{asset_id}.png"
            content = f"synthetic-guide-{ordinal}".encode()
            guide_path = self.store.input_dir(self.project_id) / filename
            guide_path.write_bytes(content)
            content_sha = hashlib.sha256(content).hexdigest().upper()
            guide_refs[asset_id] = {
                "id": asset_id, "project_id": self.project_id,
                "role": "timeline_guide", "state": "APPROVED",
                "stored_path": str(guide_path), "filename": filename,
                "sha256": content_sha, "version": 1,
                "approved_at": "2026-09-24T00:00:00Z",
            }
            guide_bindings.append({
                "asset_id": asset_id, "role": "timeline_guide",
                "requested_time_seconds": ordinal * 1.5,
                "resolved_frame_idx": frame_idx, "ordinal": ordinal,
                "content_sha256": content_sha,
                "source_identity": f"reference:{asset_id}:v1:sha256:{content_sha}",
                "approval_evidence": {"state": "APPROVED"},
            })
        self.store.save_references(self.project_id, guide_refs)
        self.job = {
            "id": self.job_id,
            "project_id": self.project_id,
            "state": "FAILED",
            "runtime": "native",
            "runtime_target": "experimental",
            "prompt_id": self.prompt_id,
            "workflow": "04_Drone_Aerial",
            "workflow_snapshot": {
                "workflow": self.graph,
                "execution_workflow_sha256": self.workflow_sha,
            },
            "execution_workflow_sha256": self.workflow_sha,
            "generation_parameters": {
                "resolution": "1344x768", "width": 1344, "height": 768,
                "fps": 24, "duration": 4.0,
                "resolved_duration_seconds": 4.4583333333,
                "frame_count": 107, "steps": 50, "sampler": "euler",
                "scheduler": "simple", "denoise": 1.0, "seed": 42,
            },
            "camera_motion": "slow_push",
            "seed": 42,
            "prompt_snapshot": {
                "workflow": "04_Drone_Aerial", "mode": "I2VA",
                "prompt": "synthetic private prompt text",
                "prompt_hash": "prompt-hash-fixture",
            },
            "reference_assets_snapshot": [],
            "guide_bindings_snapshot": guide_bindings,
            "execution_trace": {
                "runtime_identity": {
                    "target": "experimental", "port": 8190,
                    "output_root_fingerprint": self.client.output_root_fingerprint,
                },
                "delivery": {"status": "NOT_PRODUCED", "postprocess_applied": False},
                "guide_count": 2,
                "guide_bindings": guide_bindings,
            },
            "result_pipeline": {
                "schema_version": 1,
                "current_stage": "PACKAGING",
                "status": "FAILED",
                "expected_output_identity": self.expected,
                "history_outputs": [],
                "packaging_status": "FAILED",
                "events": [],
            },
            "last_observation": {
                "source": "history", "status": "COMPLETED",
                "prompt_id": self.prompt_id,
            },
            "stages": ["PREPARING", "LOADING_MODEL", "SAMPLING",
                       "DECODING", "EXPORTING", "FAILED"],
            "submission_state": "ACKNOWLEDGED",
            "package_built": False,
            "runtime_output_path": "",
            "final_output_path": "",
            "cancelled": False,
        }
        self.store.save_jobs(self.project_id, {self.job_id: self.job})

    def close(self):
        self.tmp.cleanup()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class TestResultPipelineContract(unittest.TestCase):
    def test_failure_classifications_are_stable(self):
        cases = {
            "SAVE_VIDEO_NODE_FAILURE": "SAVE_VIDEO_NODE_FAILURE",
            "SAVE_VIDEO_OUTPUT_MISSING": "UNKNOWN",
            "OUTPUT_FILE_CREATED_BUT_NOT_DISCOVERED":
                "OUTPUT_FILE_CREATED_BUT_NOT_DISCOVERED",
            "PROMPT_OUTPUT_ASSOCIATION_FAILURE": "PROMPT_OUTPUT_ASSOCIATION_FAILURE",
            "MEDIA_PROBE_FAILURE": "MEDIA_PROBE_FAILURE",
            "PACKAGING_COPY_FAILURE": "PACKAGING_COPY_FAILURE",
            "RESULT_PERSISTENCE_FAILURE": "RESULT_PERSISTENCE_FAILURE",
            "OUTPUT_PATH_INVALID": "PATH_OR_FILENAME_FAILURE",
        }
        for code, expected in cases.items():
            with self.subTest(code=code):
                self.assertEqual(classify_result_failure(code), expected)
        self.assertEqual(classify_result_failure(
            "RUNTIME_OUTPUT_IDENTITY_MISMATCH", runtime_target="experimental"),
            "EXPERIMENTAL_RUNTIME_OUTPUT_LAYOUT_MISMATCH")

    def test_native_adapter_persists_save_video_node_failure_stage(self):
        adapter = object.__new__(NativeRuntimeAdapter)
        adapter.jobs = {}
        adapter.clock = __import__("time").time
        adapter.submit = lambda _request: "prompt-save-video-failure"

        def fail_poll(*_args, **_kwargs):
            raise ComfyUIExecutionError("SaveVideo node failed on synthetic input")

        adapter.poll = fail_poll
        events = []
        graph = {"15": {"class_type": "SaveVideo", "inputs": {
            "filename_prefix": "video/job-native-test"}}}
        prepared = {
            "job_id": "native-test", "study_id": "study-test",
            "workflow_id": "04_Drone_Aerial", "translated_payload": graph,
            "execution_workflow_sha256": canonical_workflow_sha256(graph),
            "avs_job_id": "job-native-test",
            "control": {"history_timeout_seconds": 1, "poll_interval_seconds": 0.1},
            "_result_event_callback": events.append,
        }
        with self.assertRaises(ComfyUIExecutionError):
            adapter.generate(object(), prepared=prepared)
        failure = next(item for item in events if item["status"] == "FAILED")
        self.assertEqual(failure["stage"], "SAVE_VIDEO_NODE")
        self.assertEqual(failure["error_code"], "SAVE_VIDEO_NODE_FAILURE")

    def test_history_video_requires_exact_prompt_node_and_prefix(self):
        with RecoveryHarness() as harness:
            selected = select_history_video(
                harness.history, prompt_id=harness.prompt_id,
                expected=harness.expected)
            self.assertEqual(selected["filename"], harness.filename)

            wrong_prompt = dict(harness.history, prompt_id="other-prompt")
            with self.assertRaises(ResultIdentityError):
                select_history_video(wrong_prompt, prompt_id=harness.prompt_id,
                                    expected=harness.expected)

            wrong_node = dict(harness.history, outputs={
                "99": harness.history["outputs"]["15"]})
            with self.assertRaises(ResultIdentityError):
                select_history_video(wrong_node, prompt_id=harness.prompt_id,
                                    expected=harness.expected)

            wrong_prefix = dict(harness.history, outputs={
                "15": {"videos": [{**harness.history["outputs"]["15"]["videos"][0],
                                    "filename": "unrelated.mp4"}]}})
            with self.assertRaises(ResultIdentityError):
                select_history_video(wrong_prefix, prompt_id=harness.prompt_id,
                                    expected=harness.expected)

            missing_node_output = dict(harness.history, outputs={
                "15": {"images": []}})
            with self.assertRaises(ResultIdentityError) as missing:
                select_history_video(missing_node_output, prompt_id=harness.prompt_id,
                                     expected=harness.expected)
            self.assertEqual(missing.exception.code, "SAVE_VIDEO_OUTPUT_MISSING")

            unexpected_video = dict(harness.history, outputs={
                "15": {"videos": [{
                    "filename": "unrelated.mp4", "subfolder": "video",
                    "type": "output", "format": "video/mp4",
                }]}})
            with self.assertRaises(ResultIdentityError) as undiscovered:
                select_history_video(unexpected_video, prompt_id=harness.prompt_id,
                                     expected=harness.expected)
            self.assertEqual(undiscovered.exception.code,
                             "OUTPUT_FILE_CREATED_BUT_NOT_DISCOVERED")

    def test_exact_collection_uses_explicit_runtime_output_root(self):
        with RecoveryHarness() as harness:
            output = harness.client.collect_output(
                harness.history, harness.job_id, "04_Drone_Aerial", {
                    "expected_prompt_id": harness.prompt_id,
                    "expected_output_identity": harness.expected,
                    "execution_workflow_sha256": harness.workflow_sha,
                    "studio_job_id": harness.job_id,
                })
            self.assertEqual(Path(output["video_path"]).resolve(), harness.media.resolve())
            self.assertEqual(output["runtime_info"]["output_root_fingerprint"],
                             harness.client.output_root_fingerprint)

    def test_strict_video_probe_retries_managed_decoder_after_preferred_failure(self):
        with tempfile.TemporaryDirectory() as raw:
            media = Path(raw) / "synthetic.mp4"
            preferred = Path(raw) / "preferred-ffmpeg.exe"
            fallback = Path(raw) / "managed-ffmpeg.exe"
            media.write_bytes(b"synthetic-media")
            preferred.write_bytes(b"synthetic-executable")
            fallback.write_bytes(b"synthetic-executable")
            imageio = SimpleNamespace(
                get_ffmpeg_exe=lambda: str(fallback))
            rejected = SimpleNamespace(returncode=1, stdout="", stderr="")
            accepted = SimpleNamespace(returncode=0, stdout="", stderr="")
            client = ComfyUIClient(ffmpeg_path=str(preferred), strict_output=True)
            with patch.dict(sys.modules, {"imageio_ffmpeg": imageio}), \
                 patch("runtime.adapters.comfyui_client.subprocess.run",
                       side_effect=[rejected, accepted]) as run:
                client._validate_real_video(str(media))

            self.assertEqual(run.call_count, 2)
            self.assertEqual(run.call_args_list[0].args[0][0], str(preferred.resolve()))
            self.assertEqual(run.call_args_list[1].args[0][0], str(fallback.resolve()))

    def test_experimental_delivery_probe_does_not_use_production_runtime_tools(self):
        with RecoveryHarness() as harness:
            harness.jobs.runtime_paths = object()
            project_id, job = harness.store.find_job(harness.job_id)
            job["runtime_target"] = "experimental"
            harness.jobs._save_job(project_id, job)
            probe_result = {
                "available": True, "width": 832, "height": 480,
                "fps": 24.0, "duration_seconds": 4.46,
                "probe_tool": "imageio_ffmpeg_compatibility",
            }
            with patch("runtime.media_probe.probe_media_file",
                       return_value=probe_result) as probe:
                harness.jobs._update_delivery_probe(
                    project_id, job, str(harness.media))

            probe.assert_called_once_with(harness.media, runtime_paths=None)
            _, saved = harness.store.find_job(harness.job_id)
            self.assertEqual(saved["execution_trace"]["delivery"]["status"],
                             "PROBED")

    def test_missing_media_and_media_probe_failure_are_distinct(self):
        with RecoveryHarness() as harness:
            missing = dict(harness.history, outputs={
                "15": {"videos": [{
                    "filename": "04_Drone_Aerial_job-a5-recovery_00001.mp4",
                    "subfolder": "video", "type": "output", "format": "video/mp4",
                }]}})
            harness.media.unlink()
            harness.client.strict_output = True
            with self.assertRaises(ComfyUIExecutionError) as error:
                harness.client.collect_output(missing, harness.job_id,
                                              "04_Drone_Aerial", {
                    "expected_prompt_id": harness.prompt_id,
                    "expected_output_identity": harness.expected,
                })
            self.assertIn("OUTPUT_FILE_CREATED_BUT_NOT_DISCOVERED",
                          str(error.exception))

        with RecoveryHarness() as harness:
            harness.client.strict_output = True
            harness.client._validate_real_video = lambda _path: (_ for _ in ()).throw(
                RuntimeError("synthetic invalid media"))
            with self.assertRaises(ComfyUIExecutionError) as error:
                harness.client.collect_output(harness.history, harness.job_id,
                                              "04_Drone_Aerial", {
                    "expected_prompt_id": harness.prompt_id,
                    "expected_output_identity": harness.expected,
                })
            self.assertIn("MEDIA_PROBE_FAILURE", str(error.exception))

    def test_diagnostics_store_stage_identity_without_prompt_or_absolute_path(self):
        with RecoveryHarness() as harness:
            for stage in ("SAVE_VIDEO_NODE", "OUTPUT_DISCOVERY", "MEDIA_PROBE",
                          "PACKAGING", "RESULT_PERSISTENCE", "RECOVERY"):
                harness.jobs._record_result_event(
                    harness.project_id, harness.job_id, stage, "FAILED",
                    error=RuntimeError("synthetic secret prompt and C:\\private\\media.mp4"),
                    error_code=f"{stage}_FIXTURE",
                    candidates=[{
                        "node_id": "15", "field": "videos",
                        "filename": "private-prompt-video.mp4",
                        "subfolder": "C:\\private\\owner-output",
                        "type": "output", "format": "video/mp4", "size": 18,
                    }])
            records = harness.store.load_job_result_events(
                harness.project_id, harness.job_id)
            encoded = json.dumps(records, ensure_ascii=False)
            self.assertEqual(len(records), 6)
            self.assertIn(harness.prompt_id, encoded)
            self.assertIn(harness.workflow_sha, encoded)
            self.assertIn("<INVALID>", encoded)
            self.assertNotIn("synthetic secret prompt", encoded)
            self.assertNotIn("private-prompt-video", encoded)
            self.assertNotIn("C:\\private", encoded)

    def test_error_sanitizer_redacts_paths_and_credentials(self):
        safe = sanitize_result_error(
            "failed at C:\\private\\video.mp4 with Bearer abc123 and /home/owner/out.mp4")
        self.assertNotIn("C:\\private", safe)
        self.assertNotIn("abc123", safe)
        self.assertNotIn("/home/owner", safe)


class TestResultRecovery(unittest.TestCase):
    def test_legacy_shared_package_from_another_job_is_never_associated(self):
        with RecoveryHarness() as harness:
            legacy = harness.store.package_dir(harness.project_id)
            (legacy / "output").mkdir(parents=True, exist_ok=True)
            (legacy / "report").mkdir(parents=True, exist_ok=True)
            (legacy / "output" / "video.mp4").write_bytes(b"stale-other-job")
            (legacy / "report" / "generation_report.json").write_text(
                json.dumps({"job_id": "job-unrelated", "status": "COMPLETED"}),
                encoding="utf-8")
            project_id, job = harness.store.find_job(harness.job_id)
            self.assertIsNone(harness.output_api._job_media_path(project_id, job))

    def test_completed_history_recovers_once_and_serves_http_ranges(self):
        harness = RecoveryHarness()
        try:
            recovered = harness.jobs.recover_result(harness.job_id)
            self.assertEqual(recovered["state"], "COMPLETED")
            self.assertEqual(harness.history_calls, 1)
            self.assertEqual(harness.submit_calls, 0)
            self.assertEqual(harness.adapter.generate_calls, 0)
            self.assertEqual(recovered["result_pipeline"]["observed_output_identity"][
                "node_id"], "15")
            self.assertTrue(harness.output_api.media_path(harness.job_id).is_file())

            package = harness.store.job_package_dir(
                harness.project_id, harness.job_id)
            package_video = package / "output" / "video.mp4"
            package_hash = hashlib.sha256(package_video.read_bytes()).hexdigest()
            again = harness.jobs.recover_result(harness.job_id)
            self.assertEqual(again["id"], recovered["id"])
            self.assertEqual(harness.history_calls, 1)
            self.assertEqual(hashlib.sha256(package_video.read_bytes()).hexdigest(),
                             package_hash)
            self.assertEqual(len(harness.store.load_jobs(harness.project_id)), 1)

            server = StudioServer(
                ("127.0.0.1", 0), harness.store,
                {"job": harness.jobs, "output": harness.output_api})
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                url = (f"http://127.0.0.1:{server.server_address[1]}"
                       f"/api/jobs/{harness.job_id}/media")
                request = urllib.request.Request(url, headers={"Range": "bytes=-5"})
                with urllib.request.urlopen(request, timeout=3) as response:
                    self.assertEqual(response.status, 206)
                    self.assertEqual(response.read(), b"-test")
                    self.assertEqual(response.headers.get("Accept-Ranges"), "bytes")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)
        finally:
            harness.close()

    def test_recovery_and_result_http_payloads_do_not_expose_absolute_paths(self):
        harness = RecoveryHarness()
        server = StudioServer(
            ("127.0.0.1", 0), harness.store,
            {"job": harness.jobs, "output": harness.output_api})
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_address[1]}"
            request = urllib.request.Request(
                f"{base}/api/jobs/{harness.job_id}/recover-result",
                data=b"{}", headers={"Content-Type": "application/json"},
                method="POST")
            with urllib.request.urlopen(request, timeout=3) as response:
                recovered = json.loads(response.read().decode("utf-8"))["data"]
            encoded_recovery = json.dumps(recovered, ensure_ascii=False)
            self.assertNotIn(str(harness.root), encoded_recovery)
            self.assertNotIn("runtime_output_path", recovered)
            self.assertNotIn("final_output_path", recovered)
            self.assertNotIn("prompt_snapshot", recovered)
            self.assertEqual(recovered["state"], "COMPLETED")
            self.assertEqual(recovered["media_url"],
                             f"/api/jobs/{harness.job_id}/media")

            with urllib.request.urlopen(
                    f"{base}/api/jobs/{harness.job_id}/result", timeout=3) as response:
                manifest = json.loads(response.read().decode("utf-8"))["data"]
            encoded_manifest = json.dumps(manifest, ensure_ascii=False)
            self.assertNotIn(str(harness.root), encoded_manifest)
            self.assertNotIn("runtime_output_path", manifest)
            self.assertNotIn("final_output_path", manifest)
            self.assertFalse(Path(manifest["package_root"]).is_absolute())
            for value in manifest["files"].values():
                self.assertFalse(Path(value).is_absolute())
            self.assertEqual(harness.history_calls, 1)
            self.assertEqual(harness.submit_calls, 0)
            self.assertEqual(harness.adapter.generate_calls, 0)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            harness.close()

    def test_wrong_prompt_and_wrong_runtime_are_rejected_without_submission(self):
        def wrong_prompt(history):
            return {**history, "prompt_id": "unrelated-prompt"}

        harness = RecoveryHarness(history_override=wrong_prompt)
        try:
            with self.assertRaises((ResultIdentityError, ValueError)):
                harness.jobs.recover_result(harness.job_id)
            self.assertEqual(harness.submit_calls, 0)
            self.assertEqual(harness.adapter.generate_calls, 0)
            self.assertEqual(harness.store.find_job(harness.job_id)[1]["state"], "FAILED")
        finally:
            harness.close()

        harness = RecoveryHarness(runtime_port=8190)
        try:
            job = harness.store.load_jobs(harness.project_id)[harness.job_id]
            job["execution_trace"]["runtime_identity"]["port"] = 8189
            harness.store.save_jobs(harness.project_id, {harness.job_id: job})
            with self.assertRaisesRegex(ValueError, "RUNTIME_TARGET_MISMATCH"):
                harness.jobs.recover_result(harness.job_id)
            self.assertEqual(harness.history_calls, 0)
            self.assertEqual(harness.submit_calls, 0)
        finally:
            harness.close()

    def test_workflow_hash_mismatch_fails_closed_before_history_lookup(self):
        harness = RecoveryHarness()
        try:
            job = harness.store.load_jobs(harness.project_id)[harness.job_id]
            job["execution_workflow_sha256"] = "0" * 64
            harness.store.save_jobs(harness.project_id, {harness.job_id: job})
            with self.assertRaisesRegex(ValueError, "WORKFLOW_SHA_MISMATCH"):
                harness.jobs.recover_result(harness.job_id)
            self.assertEqual(harness.history_calls, 0)
            self.assertEqual(harness.submit_calls, 0)
        finally:
            harness.close()

    def test_output_root_fingerprint_mismatch_fails_before_history_lookup(self):
        with RecoveryHarness() as harness:
            job = harness.store.load_jobs(harness.project_id)[harness.job_id]
            job["execution_trace"]["runtime_identity"][
                "output_root_fingerprint"] = "not-the-configured-runtime"
            harness.store.save_jobs(harness.project_id, {harness.job_id: job})
            with self.assertRaisesRegex(ValueError, "OUTPUT_ROOT_MISMATCH"):
                harness.jobs.recover_result(harness.job_id)
            self.assertEqual(harness.history_calls, 0)
            self.assertEqual(harness.submit_calls, 0)

    def test_packaging_failure_recovers_from_same_runtime_file_without_history_retry(self):
        harness = RecoveryHarness()
        original = harness.output_api.build_real_output_package
        attempts = 0

        def fail_once(*args, **kwargs):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise OSError("synthetic packaging failure")
            return original(*args, **kwargs)

        try:
            harness.output_api.build_real_output_package = fail_once
            with self.assertRaisesRegex(OSError, "synthetic packaging"):
                harness.jobs.recover_result(harness.job_id)
            failed = harness.store.find_job(harness.job_id)[1]
            self.assertEqual(failed["state"], "FAILED")
            self.assertEqual(failed["result_pipeline"]["current_stage"], "RECOVERY")
            self.assertEqual([
                item["resolved_frame_idx"]
                for item in failed["execution_trace"]["guide_bindings"]], [36, 72])

            recovered = harness.jobs.recover_result(harness.job_id)
            self.assertEqual(recovered["state"], "COMPLETED")
            self.assertEqual(harness.history_calls, 1)
            self.assertEqual(harness.submit_calls, 0)
            self.assertEqual(harness.adapter.generate_calls, 0)
            stages = [event["stage"] for event in recovered["result_pipeline"]["events"]]
            self.assertIn("PACKAGING", stages)
        finally:
            harness.close()

    def test_result_persistence_failure_is_sidecar_recorded_then_retried_without_generation(self):
        harness = RecoveryHarness()
        original_save = harness.store.save_jobs
        fail_once = True

        def fail_completed_once(project_id, jobs):
            nonlocal fail_once
            if (fail_once and jobs.get(harness.job_id, {}).get("state") == "COMPLETED"):
                fail_once = False
                raise OSError("synthetic result write failure")
            return original_save(project_id, jobs)

        try:
            harness.store.save_jobs = fail_completed_once
            with self.assertRaises(OSError):
                harness.jobs.recover_result(harness.job_id)
            events = harness.store.load_job_result_events(
                harness.project_id, harness.job_id)
            self.assertTrue(any(
                event["stage"] == "RESULT_PERSISTENCE"
                and event["status"] == "FAILED" for event in events))
            self.assertEqual(harness.store.find_job(harness.job_id)[1]["state"], "FAILED")

            recovered = harness.jobs.recover_result(harness.job_id)
            self.assertEqual(recovered["state"], "COMPLETED")
            self.assertEqual(harness.history_calls, 1)
            self.assertEqual(harness.submit_calls, 0)
            self.assertEqual(harness.adapter.generate_calls, 0)
        finally:
            harness.close()

    def test_probe_failure_does_not_repeat_generation_and_manifest_can_probe_again(self):
        harness = RecoveryHarness()
        probe_calls = 0

        def fake_probe(_path, runtime_paths=None):
            nonlocal probe_calls
            probe_calls += 1
            if probe_calls == 1:
                raise RuntimeError("synthetic probe error")
            if probe_calls == 2:
                return {"available": False, "error_code": "PROBE_TEMPORARY"}
            return {
                "available": True, "duration_seconds": 4.46,
                "width": 1344, "height": 768, "fps": 24.0,
                "video_codec": "h264", "audio_stream": True,
                "probe_tool": "synthetic-fixture",
            }

        try:
            with patch("runtime.media_probe.probe_media_file", side_effect=fake_probe):
                harness.jobs.recover_result(harness.job_id)
                stored = harness.store.find_job(harness.job_id)[1]
                self.assertEqual(stored["state"], "COMPLETED")
                self.assertEqual(stored["execution_trace"]["delivery"]["status"],
                                 "PROBE_UNAVAILABLE")
                result = harness.output_api.get_result(harness.job_id)
                self.assertEqual(result["ffprobe"]["width"], 1344)
            self.assertEqual(probe_calls, 3)
            self.assertEqual(harness.history_calls, 1)
            self.assertEqual(harness.submit_calls, 0)
            self.assertEqual(harness.adapter.generate_calls, 0)
        finally:
            harness.close()


if __name__ == "__main__":
    unittest.main()
