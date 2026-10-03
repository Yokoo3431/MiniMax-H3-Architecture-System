"""Metadata-only media probe and output-manifest contract tests."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from apps.architect_video_studio.mock_api.output_api import OutputAPI
from apps.architect_video_studio.mock_api.project_api import ProjectAPI
from apps.architect_video_studio.mock_api.store import StudioStore
from runtime.adapters.comfyui_client import ComfyUIClient
from runtime.media_probe import probe_media_file


class TestMediaProbe(unittest.TestCase):
    def test_ffprobe_metadata_is_normalized_to_public_contract(self):
        with tempfile.TemporaryDirectory() as raw:
            media = Path(raw) / "private-video.mp4"
            media.write_bytes(b"fixture")
            payload = {
                "streams": [
                    {
                        "codec_type": "video",
                        "codec_name": "h264",
                        "width": 1344,
                        "height": 768,
                        "avg_frame_rate": "24/1",
                        "duration": "4.458",
                    },
                    {"codec_type": "audio", "codec_name": "aac"},
                ],
                "format": {"duration": "4.458"},
            }
            completed = type("Completed", (), {
                "returncode": 0,
                "stdout": json.dumps(payload),
                "stderr": "",
            })()
            with patch("runtime.media_probe._managed_executable",
                       return_value=("ffprobe", Path("ffprobe.exe"))), \
                 patch("runtime.media_probe.subprocess.run", return_value=completed):
                result = probe_media_file(media)

            self.assertEqual(result, {
                "available": True,
                "duration_seconds": 4.458,
                "width": 1344,
                "height": 768,
                "fps": 24.0,
                "video_codec": "h264",
                "audio_stream": True,
                "frame_count": None,
                "probe_tool": "managed_ffprobe",
            })
            self.assertNotIn("private-video.mp4", json.dumps(result))

    def test_ffmpeg_compatibility_fallback_is_normalized(self):
        with tempfile.TemporaryDirectory() as raw:
            media = Path(raw) / "private-video.mp4"
            media.write_bytes(b"fixture")
            completed = type("Completed", (), {
                "returncode": 0,
                "stdout": "",
                "stderr": (
                    "Duration: 00:00:04.46, start: 0.000000, bitrate: N/A\n"
                    "Stream #0:0: Video: h264, yuv420p, 1344x768, 24 fps\n"
                    "Stream #0:1: Audio: aac, 48000 Hz"
                ),
            })()
            with patch("runtime.media_probe._managed_executable",
                       return_value=("ffmpeg", Path("ffmpeg.exe"))), \
                 patch("runtime.media_probe.subprocess.run", return_value=completed):
                result = probe_media_file(media)

            self.assertTrue(result["available"])
            self.assertEqual(result["probe_tool"], "managed_ffmpeg_compatibility")
            self.assertEqual(result["duration_seconds"], 4.46)
            self.assertEqual((result["width"], result["height"], result["fps"]),
                             (1344, 768, 24.0))
            self.assertTrue(result["audio_stream"])

    def test_pinned_runtime_pyav_probe_decodes_metadata_without_exposing_paths(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            media = root / "private-video.mp4"
            python = root / "isolated-python.exe"
            media.write_bytes(b"fixture")
            python.write_bytes(b"fixture")
            completed = type("Completed", (), {
                "returncode": 0,
                "stdout": json.dumps({
                    "container_format": "mov,mp4",
                    "video_codec": "h264",
                    "width": 832,
                    "height": 480,
                    "fps": 24.0,
                    "duration_seconds": 4.458333,
                    "frame_count": 107,
                    "audio_stream": False,
                }),
                "stderr": "",
            })()
            with patch("runtime.media_probe._managed_executable", return_value=None), \
                 patch("runtime.media_probe.subprocess.run",
                       return_value=completed) as run:
                result = probe_media_file(media, python_executable=python)

            self.assertTrue(result["available"])
            self.assertEqual(result["probe_tool"], "pinned_runtime_pyav")
            self.assertEqual(result["frame_count"], 107)
            self.assertEqual((result["width"], result["height"], result["fps"]),
                             (832, 480, 24.0))
            self.assertEqual(result["duration_seconds"], 4.458)
            self.assertNotIn(str(media), json.dumps(result))
            argv = run.call_args.args[0]
            self.assertEqual(argv[:3], [str(python), "-I", "-c"])
            self.assertEqual(argv[-1], str(media))
            self.assertNotIn("shell", run.call_args.kwargs)

    def test_strict_comfy_client_uses_only_explicit_runtime_pyav_fallback(self):
        with tempfile.TemporaryDirectory() as raw:
            media = Path(raw) / "fixture.mp4"
            python = Path(raw) / "isolated-python.exe"
            media.write_bytes(b"fixture")
            python.write_bytes(b"fixture")
            client = ComfyUIClient(
                strict_output=True, video_probe_python=str(python))
            with patch("runtime.adapters.comfyui_client.shutil.which",
                       return_value=None), \
                 patch.dict("sys.modules", {"imageio_ffmpeg": None}), \
                 patch("runtime.media_probe.probe_media_file", return_value={
                     "available": True, "probe_tool": "pinned_runtime_pyav",
                 }) as probe:
                client._validate_real_video(str(media))

            probe.assert_called_once_with(
                media, python_executable=str(python), timeout_seconds=30.0)

    def test_missing_media_is_non_throwing_and_path_free(self):
        with tempfile.TemporaryDirectory() as raw:
            media = Path(raw) / "missing-private-video.mp4"
            result = probe_media_file(media)
            self.assertEqual(result, {
                "available": False,
                "error_code": "MEDIA_MISSING",
            })
            self.assertNotIn(str(media), json.dumps(result))


class TestOutputManifestProbeWiring(unittest.TestCase):
    def test_native_manifest_backfills_probe_without_lifecycle_mutation(self):
        with tempfile.TemporaryDirectory() as raw:
            store = StudioStore(Path(raw))
            project_id = ProjectAPI(store).create_project("Probe Test")["id"]
            package = store.package_dir(project_id)
            (package / "output").mkdir(parents=True)
            media = package / "output" / "video.mp4"
            media.write_bytes(b"fixture")
            (package / "report").mkdir(parents=True, exist_ok=True)
            (package / "report" / "generation_report.json").write_text(
                json.dumps({"job_id": "job-test", "status": "COMPLETED"}),
                encoding="utf-8")
            job = {
                "id": "job-test",
                "runtime": "native",
                "state": "COMPLETED",
                "workflow": "04_Drone_Aerial",
                "runtime_output_path": str(media),
                "final_output_path": str(media),
            }
            expected = {
                "available": True,
                "duration_seconds": 4.46,
                "width": 1344,
                "height": 768,
                "fps": 24.0,
                "video_codec": "h264",
                "audio_stream": True,
                "probe_tool": "managed_ffmpeg_compatibility",
            }
            with patch("runtime.media_probe.probe_media_file",
                       return_value=expected) as probe:
                manifest = OutputAPI(store).manifest(project_id, job)

            probe.assert_called_once()
            self.assertEqual(manifest["ffprobe"], expected)
            self.assertEqual(job["state"], "COMPLETED")
            self.assertEqual(manifest["output"]["media_url"],
                             "/api/jobs/job-test/media")
            self.assertNotIn(str(media), json.dumps(manifest["ffprobe"]))
            self.assertFalse(Path(manifest["package_root"]).is_absolute())
            self.assertNotIn("runtime_output_path", manifest)
            self.assertNotIn("final_output_path", manifest)
            self.assertTrue(all(not Path(value).is_absolute()
                                for value in manifest["files"].values()))

    def test_experimental_manifest_uses_persisted_runtime_probe_evidence(self):
        with tempfile.TemporaryDirectory() as raw:
            store = StudioStore(Path(raw))
            project_id = ProjectAPI(store).create_project("Experimental Probe")["id"]
            package = store.job_package_dir(project_id, "job-exp")
            (package / "output").mkdir(parents=True)
            media = package / "output" / "video.mp4"
            media.write_bytes(b"fixture")
            (package / "report").mkdir(parents=True, exist_ok=True)
            (package / "report" / "generation_report.json").write_text(
                json.dumps({"job_id": "job-exp", "status": "COMPLETED"}),
                encoding="utf-8")
            job = {
                "id": "job-exp", "runtime": "native", "runtime_target": "experimental",
                "state": "COMPLETED", "workflow": "04_Drone_Aerial",
                "runtime_output_path": str(media), "final_output_path": str(media),
                "execution_trace": {"delivery": {
                    "status": "PROBED", "width": 832, "height": 480,
                    "fps": 24.0, "duration_seconds": 4.458,
                    "video_codec": "h264", "audio_stream": False,
                    "frame_count": 107, "container_format": "mov,mp4",
                    "probe_tool": "pinned_runtime_pyav",
                }},
            }
            production_paths = object()
            with patch("runtime.media_probe.probe_media_file",
                       return_value={"available": False}) as probe:
                manifest = OutputAPI(store, runtime_paths=production_paths).manifest(
                    project_id, job)

            probe.assert_not_called()
            self.assertEqual(manifest["ffprobe"]["probe_tool"],
                             "pinned_runtime_pyav")
            self.assertEqual(manifest["ffprobe"]["frame_count"], 107)

    def test_experimental_manifest_retries_probe_with_pinned_runtime_python(self):
        with tempfile.TemporaryDirectory() as raw:
            store = StudioStore(Path(raw))
            project_id = ProjectAPI(store).create_project("Probe Retry") ["id"]
            package = store.job_package_dir(project_id, "job-exp-retry")
            (package / "output").mkdir(parents=True)
            media = package / "output" / "video.mp4"
            media.write_bytes(b"fixture")
            job = {
                "id": "job-exp-retry", "runtime": "native",
                "runtime_target": "experimental", "state": "COMPLETED",
                "workflow": "04_Drone_Aerial",
                "runtime_output_path": str(media),
                "final_output_path": str(media),
                "execution_trace": {"delivery": {"status": "PROBE_UNAVAILABLE"}},
            }
            expected = {"available": True, "width": 832,
                        "probe_tool": "pinned_runtime_pyav"}
            output = OutputAPI(
                store, experimental_video_probe_python="C:/isolated/python.exe")
            with patch("runtime.media_probe.probe_media_file",
                       return_value=expected) as probe:
                manifest = output.manifest(project_id, job)

            probe.assert_called_once_with(
                media, runtime_paths=None,
                python_executable="C:/isolated/python.exe")
            self.assertEqual(manifest["ffprobe"], expected)


if __name__ == "__main__":
    unittest.main()
