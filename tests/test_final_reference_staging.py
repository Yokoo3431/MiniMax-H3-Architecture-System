"""CPU-only tests for the production reference-to-ComfyUI handoff."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from apps.architect_video_studio.mock_api.job_api import (  # noqa: E402
    InputStagingError,
    JobAPI,
)
from runtime.adapters.runtime_adapter import VideoGenerationRequest  # noqa: E402


class _Store:
    def __init__(self, refs):
        self.refs = refs

    def load_references(self, _project_id):
        return self.refs


class _Client:
    def __init__(self, input_dir: Path):
        self.input_dir = input_dir
        self.checked = []

    def input_file_available(self, filename: str) -> bool:
        self.checked.append(filename)
        return (self.input_dir / filename).is_file()


class _Adapter:
    def __init__(self, input_dir: Path):
        self.client = _Client(input_dir)


class TestFinalReferenceStaging(unittest.TestCase):
    def test_stages_ascii_name_and_rewrites_request_before_prompt(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "studio" / "微信图片.png"
            source.parent.mkdir()
            source.write_bytes(b"image-bytes")
            comfy_input = root / "runtime" / "ComfyUI" / "input"
            ref = {
                "id": "ref-fc9bdeef6821",
                "filename": "微信图片_20260611140851_1240_1841.png",
                "stored_path": str(source),
                "state": "APPROVED",
            }
            request = VideoGenerationRequest(
                study_id="study-1",
                reference_assets=[{
                    "asset_id": ref["id"],
                    "role": "first_frame",
                    "path_or_ref": ref["stored_path"],
                }],
                workflow_id="05_Slow_Walkthrough",
                camera_motion="walkthrough",
                generation_parameters={"resolution": "1344x768", "fps": 24,
                                        "duration": 4, "quality": "diagnostic",
                                        "seed": 1},
                prompt_payload={"mode": "I2VA", "prompt": "test",
                                "prompt_hash": "hash"},
            )
            api = JobAPI(_Store({ref["id"]: ref}),
                         runtime_adapter=_Adapter(comfy_input),
                         comfy_input_dir=str(comfy_input))

            staged = api._stage_refs_to_comfy_input("study-1", request)

            expected = "avs_ref-fc9bdeef6821_" + __import__("hashlib").sha256(b"image-bytes").hexdigest()[:12] + ".png"
            self.assertEqual(staged, {ref["id"]: expected})
            self.assertEqual(request.reference_assets[0]["path_or_ref"], expected)
            self.assertEqual((comfy_input / expected).read_bytes(), b"image-bytes")
            self.assertEqual(api.runtime_adapter.client.checked, [expected])

    def test_missing_approved_reference_is_input_error_before_prompt(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ref = {
                "id": "ref-missing",
                "filename": "missing.png",
                "stored_path": str(root / "missing.png"),
                "state": "APPROVED",
            }
            request = VideoGenerationRequest(
                study_id="study-1",
                reference_assets=[{"asset_id": ref["id"], "path_or_ref": "missing.png"}],
                workflow_id="05_Slow_Walkthrough",
                camera_motion="walkthrough",
                generation_parameters={"resolution": "1344x768", "fps": 24,
                                        "duration": 4, "quality": "diagnostic",
                                        "seed": 1},
                prompt_payload={"mode": "I2VA", "prompt": "test",
                                "prompt_hash": "hash"},
            )
            api = JobAPI(_Store({ref["id"]: ref}),
                         runtime_adapter=_Adapter(root / "input"),
                         comfy_input_dir=str(root / "input"))

            with self.assertRaises(InputStagingError):
                api._stage_refs_to_comfy_input("study-1", request)


if __name__ == "__main__":
    unittest.main()
