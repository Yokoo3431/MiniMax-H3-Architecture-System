from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from release import build_shareable_release as release_builder


class TestShareableReleasePrivacy(unittest.TestCase):
    def test_release_candidate_comes_from_tracked_runtime_manifest(self):
        with tempfile.TemporaryDirectory(prefix="avs-release-version-") as temp:
            root = Path(temp)
            configs = root / "configs"
            configs.mkdir()
            (configs / "release_runtime_manifest.json").write_text(
                '{"release":"v0.8.0-rc3.3-shareable"}', encoding="utf-8")
            with mock.patch.object(release_builder, "ROOT", root):
                self.assertEqual(
                    release_builder._release_candidate(),
                    "v0.8.0-rc3.3-shareable")

    def test_release_candidate_rejects_stale_or_invalid_identity(self):
        with tempfile.TemporaryDirectory(prefix="avs-release-version-") as temp:
            root = Path(temp)
            configs = root / "configs"
            configs.mkdir()
            manifest = configs / "release_runtime_manifest.json"
            manifest.write_text(
                '{"release":"v0.8.0-rc1-shareable"}', encoding="utf-8")
            with mock.patch.object(release_builder, "ROOT", root):
                self.assertEqual(
                    release_builder._release_candidate(),
                    "v0.8.0-rc1-shareable")
                manifest.write_text('{"release":"latest"}', encoding="utf-8")
                with self.assertRaisesRegex(RuntimeError, "valid version"):
                    release_builder._release_candidate()

    def test_final_payload_file_count_tracks_unique_files(self):
        with tempfile.TemporaryDirectory(prefix="avs-payload-count-") as temp:
            payload = Path(temp) / "payload"
            (payload / "launcher").mkdir(parents=True)
            (payload / "launcher" / "app.exe").write_bytes(b"app")
            (payload / "README.md").write_text("readme", encoding="utf-8")
            self.assertEqual(release_builder._payload_file_count(payload), 2)

    def test_payload_copies_only_tracked_safe_sources(self):
        with tempfile.TemporaryDirectory(prefix="avs-release-privacy-") as temp:
            root = Path(temp)
            (root / "references").mkdir()
            (root / "models").mkdir()
            (root / "configs").mkdir()
            (root / "installer").mkdir()

            (root / "references" / "synthetic-sample.png").write_bytes(b"synthetic")
            (root / "references" / "local-private.jpg").write_bytes(b"untracked")
            (root / "models" / "local-checkpoint.pt").write_bytes(b"untracked")
            (root / "models" / "fixture.safetensors").write_bytes(b"fixture")
            (root / "configs" / "installer_bootstrap.json").write_text(
                "{}", encoding="utf-8")
            (root / "installer" / "Setup.cmd").write_text("@echo off", encoding="utf-8")
            (root / "installer" / "Setup.ps1").write_text("# fixture", encoding="utf-8")

            tracked = {
                "references/synthetic-sample.png",
                "models/fixture.safetensors",
                "configs/installer_bootstrap.json",
                "installer/Setup.cmd",
                "installer/Setup.ps1",
            }
            stage = root / "stage"
            with (
                mock.patch.object(release_builder, "ROOT", root),
                mock.patch.object(release_builder, "ROOT_FILES", ()),
                mock.patch.object(release_builder, "DIRECTORIES", ("references", "models", "configs")),
                mock.patch.object(release_builder, "RELEASE_WORKFLOW_FILES", ()),
                mock.patch.object(release_builder, "DOC_FILES", ()),
                mock.patch.object(release_builder, "HARDENING_FILES", ()),
                mock.patch.object(release_builder, "SETUP_CMD", root / "installer" / "Setup.cmd"),
                mock.patch.object(release_builder, "SETUP_PS1", root / "installer" / "Setup.ps1"),
                mock.patch.object(release_builder, "_tracked_source_paths", return_value=tracked),
            ):
                copied_count = release_builder.assemble_payload(stage)

            payload = stage / "payload"
            self.assertEqual(copied_count, 4)
            self.assertTrue((payload / "references" / "synthetic-sample.png").is_file())
            self.assertFalse((payload / "references" / "local-private.jpg").exists())
            self.assertFalse((payload / "models" / "local-checkpoint.pt").exists())
            self.assertFalse((payload / "models" / "fixture.safetensors").exists())
            self.assertTrue((payload / "configs" / "installer_bootstrap.json").is_file())
            self.assertTrue((stage / "Setup.cmd").is_file())
            self.assertTrue((stage / "Setup.ps1").is_file())

    def test_common_model_weight_formats_are_never_allowed(self):
        for suffix in (
            ".safetensors", ".bin", ".ckpt", ".pt", ".pth", ".gguf",
            ".ggml", ".onnx", ".tflite", ".engine", ".weights", ".pb",
            ".h5", ".hdf5", ".tensor", ".model",
        ):
            with self.subTest(suffix=suffix):
                self.assertFalse(release_builder._allowed(Path("models/weight" + suffix)))

    def test_common_video_and_audio_containers_are_never_allowed(self):
        for suffix in (
            ".mp4", ".avi", ".mov", ".mkv", ".m4v", ".wmv", ".flv",
            ".mpeg", ".mpg", ".webm", ".3gp", ".ts", ".wav", ".mp3",
            ".m4a", ".aac", ".flac", ".ogg", ".opus",
        ):
            with self.subTest(suffix=suffix):
                self.assertFalse(release_builder._allowed(Path("samples/media" + suffix)))

    def test_models_directory_only_allows_metadata(self):
        self.assertTrue(release_builder._allowed(Path("models/manifest.json")))
        self.assertTrue(release_builder._allowed(Path("models/README.md")))
        self.assertFalse(release_builder._allowed(Path("models/unrecognized-format.tensor")))


if __name__ == "__main__":
    unittest.main()
