from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from apps.architect_video_studio.mock_api.job_api import JobAPI
from apps.architect_video_studio.mock_api.output_api import OutputAPI
from apps.architect_video_studio.mock_api.project_api import ProjectAPI
from apps.architect_video_studio.mock_api.server import StudioServer
from apps.architect_video_studio.mock_api.store import StudioStore
from runtime.a8_delivery import DeliveryError, DeliveryPipeline, sha256_file
from runtime.media_probe import _from_ffmpeg_text, _from_ffprobe, probe_media_file


class A8DeliveryFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = StudioStore(self.root / "data")
        self.project = ProjectAPI(self.store).create_project("A8 Delivery Fixture")
        self.job_id = "job-a8-delivery-fixture"
        self.source_root = self.root / "native-output"
        self.source_root.mkdir()
        self.source = self.source_root / f"04_Drone_Aerial_{self.job_id}.mp4"
        self.source.write_bytes(b"synthetic-native-media-for-a8-fixture")
        project = self.store.load_project(self.project["id"])
        project["output_directory"] = str(self.source_root)
        self.store.save_project(project)
        self.workflow_sha = "a" * 64
        self.prompt_id = "prompt-a8-fixture"
        self.runtime_identity = {
            "runtime_id": "production-h3-8189",
            "runtime_role": "production",
            "backend": "comfyui",
            "comfyui_version": "0.33.1",
            "endpoint_identity": "loopback:8189",
            "config_fingerprint": "b" * 64,
            "output_root_fingerprint": "c" * 64,
        }
        self.job = {
            "id": self.job_id,
            "project_id": self.project["id"],
            "state": "COMPLETED",
            "runtime": "native",
            "runtime_target": "production",
            "workflow": "04_Drone_Aerial",
            "prompt_id": self.prompt_id,
            "execution_workflow_sha256": self.workflow_sha,
            "final_output_path": str(self.source),
            "output_path": str(self.source),
            "generation_parameters": {
                "width": 1344, "height": 768, "fps": 24, "duration": 4.46,
            },
            "execution_trace": {
                "workflow_sha256": self.workflow_sha,
                "runtime_identity": dict(self.runtime_identity),
                "native_generation": {"width": 1344, "height": 768, "fps": 24},
                "guide_bindings": [{"resolved_frame_idx": 36},
                                   {"resolved_frame_idx": 72}],
            },
        }
        self.store.save_jobs(self.project["id"], {self.job_id: self.job})
        self.output = OutputAPI(self.store, allow_mock_outputs=False)
        self.expected = {"width": 1920, "height": 1080, "fps": 48}
        self.ffmpeg_stub = self.root / "ffmpeg.exe"
        self.ffmpeg_stub.write_bytes(b"test-only executable placeholder")
        self.pipeline = DeliveryPipeline(
            store=self.store, ffmpeg_executable=self.ffmpeg_stub,
            probe=self._probe, min_free_bytes=1,
        )
        self.pipeline._version = lambda: "ffmpeg version 7.1-test"
        self.interpolation_calls = 0
        self.encode_calls = 0
        self.alignment_calls = 0
        self.aligned_path = None
        self.pipeline._run_interpolation = self._interpolate
        self.pipeline._run_tail_alignment = self._align_tail
        self.pipeline._run_encode = self._encode
        self.output.delivery_pipeline = self.pipeline
        self.jobs = JobAPI(self.store, output_api=self.output, allow_mock_jobs=False)

    def tearDown(self):
        self.tmp.cleanup()

    def _probe(self, path, **_kwargs):
        path = Path(path)
        if path == self.source:
            return {
                "available": True, "width": 1344, "height": 768,
                "fps": 24.0, "duration_seconds": 4.46,
                "frame_count": 107, "video_codec": "h264",
                "container_format": "mov,mp4,m4a,3gp,3g2,mj2",
                "audio_stream": True, "probe_tool": "fixture",
            }
        if path.suffix.lower() == ".mkv":
            expected_frames = int(round(4.46 * self.expected["fps"]))
            if path == self.aligned_path:
                frame_count = expected_frames
            else:
                frame_count = expected_frames - 2
            return {
                "available": True, "width": 1344, "height": 768,
                "fps": float(self.expected["fps"]), "duration_seconds": 4.46,
                "frame_count": frame_count,
                "video_codec": "ffv1", "audio_stream": False,
                "probe_tool": "fixture",
            }
        return {
            "available": True, "width": int(self.expected["width"]),
            "height": int(self.expected["height"]),
            "fps": float(self.expected["fps"]), "duration_seconds": 4.46,
            "frame_count": int(round(4.46 * self.expected["fps"])),
            "video_codec": "h264", "container_format": "mov,mp4",
            "audio_stream": True, "probe_tool": "fixture",
        }

    def _interpolate(self, _source, pending, _fps, _work_dir):
        self.interpolation_calls += 1
        Path(pending).write_bytes(b"verified-lossless-interpolation-checkpoint")

    def _align_tail(self, _source, pending, _pad_frames, _work_dir):
        self.alignment_calls += 1
        self.aligned_path = Path(pending)
        Path(pending).write_bytes(b"timeline-aligned-lossless-checkpoint")

    def _encode(self, _video, _audio, pending, _target, _work_dir):
        self.encode_calls += 1
        Path(pending).write_bytes(b"verified-delivery-mp4-fixture")

    def _create(self, resolution="ULTRA_1080", fps=48):
        target = {"NATIVE": (1344, 768), "ULTRA_1080": (1920, 1080),
                  "ULTRA_2K": (2048, 1152)}[resolution]
        self.expected = {"width": target[0], "height": target[1], "fps": fps}
        return self.jobs.create_delivery(self.job_id, {
            "target_resolution": resolution,
            "delivery_fps": fps,
        })

    def test_delivery_idempotency_trace_and_source_preservation(self):
        original_sha = sha256_file(self.source)
        first = self._create("ULTRA_1080", 48)
        second = self._create("ULTRA_1080", 48)
        self.assertEqual(first["status"], "READY")
        self.assertEqual(first["delivery_id"], second["delivery_id"])
        self.assertEqual(sha256_file(self.source), original_sha)
        self.assertEqual(self.interpolation_calls, 1)
        self.assertEqual(self.alignment_calls, 1)
        self.assertEqual(self.encode_calls, 1)
        self.assertEqual(first["native_generation_resolution"],
                         {"width": 1344, "height": 768})
        self.assertEqual(first["delivery_resolution"],
                         {"width": 1920, "height": 1080})
        self.assertEqual(first["frame_interpolation_method"],
                         "ffmpeg_minterpolate_mci")
        self.assertEqual(first["upscale_method"], "ffmpeg_scale_lanczos_pad")
        self.assertEqual(first["expected_delivery_frame_count"], 214)
        self.assertEqual(first["terminal_padding_frames"], 2)
        self.assertEqual(first["timeline_alignment_method"],
                         "ffmpeg_tpad_clone_last")
        saved = self.store.load_jobs(self.project["id"])[self.job_id]
        self.assertEqual(saved["execution_trace"]["delivery_outputs"][0]["delivery_id"],
                         first["delivery_id"])
        raw = json.dumps(first)
        self.assertNotIn(str(self.root), raw)

    def test_failed_encode_resumes_from_interpolation_checkpoint(self):
        self.expected = {"width": 1344, "height": 768, "fps": 48}
        original_encode = self.pipeline._run_encode
        calls = {"count": 0}

        def fail_once(video, audio, pending, target, work_dir):
            calls["count"] += 1
            if calls["count"] == 1:
                raise DeliveryError("DELIVERY_FFMPEG_STAGE_FAILED")
            return original_encode(video, audio, pending, target, work_dir)

        self.pipeline._run_encode = fail_once
        with self.assertRaises(DeliveryError):
            self._create("NATIVE", 48)
        first_records = self.output.list_deliveries(self.job_id)["items"]
        self.assertEqual(first_records[0]["status"], "FAILED")
        self.assertEqual(first_records[0]["stage_status"]["frame_interpolation"], "COMPLETED")
        result = self._create("NATIVE", 48)
        self.assertEqual(result["status"], "READY")
        self.assertEqual(self.interpolation_calls, 1)
        self.assertEqual(self.alignment_calls, 1)
        self.assertEqual(calls["count"], 2)

    def test_low_disk_reserve_blocks_delivery_before_processing(self):
        with patch("runtime.a8_delivery.shutil.disk_usage",
                   return_value=SimpleNamespace(free=0)):
            with self.assertRaisesRegex(
                    DeliveryError, "DELIVERY_INSUFFICIENT_DISK_RESERVE"):
                self._create("ULTRA_1080", 48)

        self.assertEqual(self.interpolation_calls, 0)
        self.assertEqual(self.alignment_calls, 0)
        self.assertEqual(self.encode_calls, 0)
        output_root = self.store.job_package_dir(
            self.project["id"], self.job_id) / "delivery" / "outputs"
        self.assertEqual(list(output_root.glob("*.mp4")), [])

    def test_interpolation_validation_failure_preserves_observed_probe(self):
        original_probe = self.pipeline._probe

        def probe_with_bad_duration(path, runtime_paths, probe):
            value = original_probe(path, runtime_paths, probe)
            if Path(path).suffix.lower() == ".mkv":
                value["duration_seconds"] = 4.8
            return value

        self.pipeline._probe = probe_with_bad_duration
        with self.assertRaisesRegex(
                DeliveryError, "DELIVERY_INTERPOLATION_VALIDATION_FAILED"):
            self._create("NATIVE", 60)
        records = self.output.list_deliveries(self.job_id)["items"]
        failed = next(item for item in records if item["delivery_fps"] == 60)
        manifest = self.pipeline.manifest_for_job(
            job_id=self.job_id,
            package_root=self.store.job_package_dir(self.project["id"], self.job_id),
            delivery_id=failed["delivery_id"],
        )
        stage = manifest["stages"]["frame_interpolation"]
        self.assertEqual(stage["status"], "FAILED")
        self.assertEqual(stage["observed_probe"]["duration_seconds"], 4.8)
        self.assertIn("duration_mismatch", stage["validation_failures"])

    def test_missing_or_wrong_execution_identity_fails_closed(self):
        broken = dict(self.job)
        broken.pop("prompt_id")
        with self.assertRaisesRegex(DeliveryError, "DELIVERY_EXECUTION_IDENTITY_INCOMPLETE"):
            self.pipeline.create(
                job=broken, source=self.source,
                package_root=self.store.job_package_dir(self.project["id"], self.job_id),
                target_resolution="ULTRA_1080", delivery_fps=48)
        incomplete_runtime = dict(self.job)
        incomplete_runtime["execution_trace"] = dict(self.job["execution_trace"])
        incomplete_runtime["execution_trace"]["runtime_identity"] = {"runtime_role": "production"}
        with self.assertRaisesRegex(DeliveryError, "DELIVERY_RUNTIME_IDENTITY_INCOMPLETE"):
            self.pipeline.create(
                job=incomplete_runtime, source=self.source,
                package_root=self.store.job_package_dir(self.project["id"], self.job_id),
                target_resolution="ULTRA_1080", delivery_fps=48)

    def test_delivery_media_requires_current_strong_identity_and_range_route(self):
        result = self._create("ULTRA_1080", 48)
        package = self.store.job_package_dir(self.project["id"], self.job_id)
        path = self.output.delivery_media_path(self.job_id, result["delivery_id"])
        self.assertEqual(path.read_bytes(), b"verified-delivery-mp4-fixture")
        saved = self.store.load_jobs(self.project["id"])[self.job_id]
        saved["execution_trace"]["runtime_identity"]["runtime_id"] = "wrong-runtime"
        self.store.save_jobs(self.project["id"], {self.job_id: saved})
        with self.assertRaisesRegex(DeliveryError, "DELIVERY_IDENTITY_MISMATCH"):
            self.output.delivery_media_path(self.job_id, result["delivery_id"])

    def test_http_delivery_route_supports_range_and_never_submits_generation(self):
        self.expected = {"width": 2048, "height": 1152, "fps": 60}
        server = StudioServer(("127.0.0.1", 0), self.store,
                              {"output": self.output, "job": self.jobs})
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        submit_calls = {"count": 0}
        self.jobs.submit_job = lambda *_a, **_k: submit_calls.__setitem__(
            "count", submit_calls["count"] + 1)
        try:
            request = urllib.request.Request(
                f"{base}/api/jobs/{self.job_id}/deliveries", method="POST",
                data=json.dumps({"target_resolution": "ULTRA_2K",
                                 "delivery_fps": 60}).encode("utf-8"),
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(request, timeout=5) as response:
                created = json.loads(response.read())["data"]
                self.assertEqual(response.status, 200)
            self.assertEqual(created["status"], "READY")
            with urllib.request.urlopen(
                    f"{base}/api/jobs/{self.job_id}/deliveries", timeout=5) as response:
                listing = json.loads(response.read())["data"]
            self.assertEqual(len(listing["items"]), 1)
            self.assertEqual(listing["items"][0]["delivery_id"], created["delivery_id"])
            media_url = base + f"/api/jobs/{self.job_id}/deliveries/{created['delivery_id']}/media"
            range_request = urllib.request.Request(media_url, headers={"Range": "bytes=0-7"})
            with urllib.request.urlopen(range_request, timeout=5) as response:
                self.assertEqual(response.status, 206)
                self.assertEqual(response.read(), b"verified")
            self.assertEqual(submit_calls["count"], 0)
            self.assertEqual(self.store.load_jobs(self.project["id"])[self.job_id]["state"],
                             "COMPLETED")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_invalid_profile_and_noop_are_rejected(self):
        with self.assertRaisesRegex(DeliveryError, "DELIVERY_RESOLUTION_UNSUPPORTED"):
            self.output.create_delivery(
                self.job_id, target_resolution="../../output", delivery_fps=48)
        with self.assertRaisesRegex(DeliveryError, "DELIVERY_NO_POSTPROCESS_REQUESTED"):
            self.output.create_delivery(
                self.job_id, target_resolution="NATIVE", delivery_fps=24)

    def test_legacy_package_refresh_preserves_job_delivery_artifacts(self):
        package = self.store.package_dir(self.project["id"])
        job_artifact = self.store.job_package_dir(self.project["id"], self.job_id)
        job_artifact.mkdir(parents=True, exist_ok=True)
        marker = job_artifact / "delivery" / "outputs" / "keep.mp4"
        marker.parent.mkdir(parents=True)
        marker.write_bytes(b"job-owned delivery")
        legacy = package / "output" / "video.mp4"
        legacy.parent.mkdir(parents=True)
        legacy.write_bytes(b"legacy shared output")

        self.store.clear_package(self.project["id"])

        self.assertTrue(marker.is_file())
        self.assertFalse(legacy.exists())


class A8ProbeTests(unittest.TestCase):
    def test_ffmpeg_compatibility_probe_extracts_final_frame_count(self):
        value = _from_ffmpeg_text(
            "Duration: 00:00:04.46, start: 0.0, bitrate: 1 kb/s\n"
            "Video: h264, yuv420p, 1344x768, 48 fps\n"
            "Audio: aac\nframe=  214 fps=0.0 q=-0.0 Lsize=N/A time=00:00:04.46\n")
        self.assertEqual(value["frame_count"], 214)
        self.assertEqual(value["probe_tool"], "managed_ffmpeg_decode_count_fallback")

    def test_ffprobe_prefers_decoded_frame_count_not_container_estimate(self):
        value = _from_ffprobe({
            "streams": [{"codec_type": "video", "codec_name": "h264",
                         "width": 1344, "height": 768,
                         "avg_frame_rate": "24/1", "duration": "4.46",
                         "nb_frames": "999", "nb_read_frames": "107"}],
            "format": {"duration": "4.46"},
        })
        self.assertEqual(value["frame_count"], 107)
        self.assertEqual(value["probe_tool"], "managed_ffprobe")

    def test_ffmpeg_probe_requests_progress_and_returns_exact_frame_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            media = Path(tmp) / "synthetic.mp4"
            media.write_bytes(b"fixture")
            completed = SimpleNamespace(
                returncode=0,
                stderr=("Duration: 00:00:04.46, start: 0.0, bitrate: 1 kb/s\n"
                        "Video: h264, yuv420p, 1344x768, 24 fps\nAudio: aac\n"),
                stdout="frame=107\nprogress=end\n",
            )
            with patch("runtime.media_probe._managed_executable",
                       return_value=("ffmpeg", Path(tmp) / "ffmpeg.exe")), \
                    patch("runtime.media_probe.subprocess.run",
                          return_value=completed) as run:
                value = probe_media_file(media)
        self.assertEqual(value["frame_count"], 107)
        self.assertEqual(value["probe_tool"], "managed_ffmpeg_decode_count_fallback")
        args = run.call_args.args[0]
        self.assertIn("-progress", args)
        self.assertIn("pipe:1", args)
        self.assertIn("-map", args)
        self.assertIn("0:v:0", args)

    def test_ffmpeg_probe_does_not_promote_incomplete_progress_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            media = Path(tmp) / "synthetic.mp4"
            media.write_bytes(b"fixture")
            completed = SimpleNamespace(
                returncode=0,
                stderr=("Duration: 00:00:04.46, start: 0.0, bitrate: 1 kb/s\n"
                        "Video: h264, yuv420p, 1344x768, 24 fps\n"),
                stdout="frame=54\nprogress=continue\n",
            )
            with patch("runtime.media_probe._managed_executable",
                       return_value=("ffmpeg", Path(tmp) / "ffmpeg.exe")), \
                    patch("runtime.media_probe.subprocess.run",
                          return_value=completed):
                value = probe_media_file(media)
        self.assertIsNone(value["frame_count"])
        self.assertEqual(value["probe_tool"], "managed_ffmpeg_compatibility")


if __name__ == "__main__":
    unittest.main()
