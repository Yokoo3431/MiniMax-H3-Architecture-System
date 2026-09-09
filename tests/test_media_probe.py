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


if __name__ == "__main__":
    unittest.main()
