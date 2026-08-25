"""RC3.4 PATCH2.7-C2-B - Multi-workflow native runtime tests (NO real GPU).

Covers: workflow registry, input mode (I2VA/FL2VA first+last no swap),
parameter mapping, output collector, error mapping.
"""

import json
import sys
import unittest
from pathlib import Path

from runtime.yaml_compat import safe_load

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from runtime.adapters.comfyui_client import (  # noqa: E402
    ComfyUIClient,
    ComfyUIExecutionError,
    ComfyUIOfflineError,
    GenerationTimeoutError,
    WorkflowNotFoundError,
)
from runtime.adapters.native_runtime_adapter import NativeRuntimeAdapter  # noqa: E402
from runtime.adapters.runtime_adapter import VideoGenerationRequest  # noqa: E402

MAPPING = SYSTEM_ROOT / "runtime" / "contracts" / "workflow_mapping.yaml"
REGISTRY_VALIDATION = SYSTEM_ROOT / "configs" / "rc34_patch27c2b_workflow_registry_validation.json"

WORKFLOWS = ["01_Exterior_Hero", "02_Day_Night_Transition", "03_Material_Detail",
             "04_Drone_Aerial", "05_Slow_Walkthrough"]

CONFIG = {
    "01_Exterior_Hero": ("I2VA", ["01_Exterior_Hero.png"], "slow_push"),
    "02_Day_Night_Transition": ("FL2VA", ["DAY.png", "NIGHT.png"], "static"),
    "03_Material_Detail": ("I2VA", ["03.jpg"], "static"),
    "04_Drone_Aerial": ("I2VA", ["aerial.png"], "aerial_reveal"),
    "05_Slow_Walkthrough": ("I2VA", ["walk.png"], "walkthrough"),
}


def make_request(workflow_id, refs=None, camera=None, seed=777888900):
    mode, default_refs, default_cam = CONFIG[workflow_id]
    refs = refs or default_refs
    camera = camera or default_cam
    assets = [{"asset_id": f"r{i}", "role": ("first_frame" if i == 0 else "last_frame"),
               "path_or_ref": n, "sha256": "A" * 64} for i, n in enumerate(refs)]
    return VideoGenerationRequest(
        study_id="c2b_test", reference_assets=assets, workflow_id=workflow_id,
        camera_motion=camera,
        generation_parameters={"resolution": "1344x768", "fps": 24,
                               "duration": 4.0, "quality": "diagnostic",
                               "seed": seed},
        prompt_payload={"mode": mode, "prompt": "For the target video, at 0.00 seconds ...",
                        "alignment": "a", "integrated_multimodal_description": "d",
                        "overall_soundscape": "s", "non_diegetic_music": "N/A",
                        "prompt_hash": "B" * 64},
        output_spec={"container": "mp4", "codec": "h264", "fps": 24,
                     "resolution": "1344x768", "report_format": "json"},
        gates={"reference_approved": True, "intent_confirmed": True,
               "prompt_verified": True, "risk_reviewed": True},
    )


class FakeClient:
    def __init__(self, offline=False, timeout=False, fail=False):
        self.offline = offline
        self.timeout = timeout
        self.fail = fail
        self.submitted = []

    def submit_workflow(self, payload, client_id=None):
        if self.offline:
            raise ComfyUIOfflineError("offline")
        self.submitted.append(payload)
        return {"prompt_id": "fake-2"}

    def wait_completion(self, prompt_id, timeout_seconds=1500.0, poll_interval=5.0):
        if self.timeout:
            raise GenerationTimeoutError("timeout")
        if self.fail:
            return {"status": "ERROR", "prompt_id": prompt_id, "messages": []}
        return {"status": "COMPLETED", "prompt_id": prompt_id}

    def get_history(self, prompt_id):
        return {"prompt_id": prompt_id, "outputs": {
            "15": {"images": [{"filename": "x_C2B_00001_.mp4", "subfolder": "video",
                               "type": "output", "animated": True}]}}}

    def collect_output(self, history, job_id, workflow_id, metadata=None):
        return ComfyUIClient(output_root=r"C:\mock\output").collect_output(
            history, job_id, workflow_id, metadata)


class TestWorkflowRegistry(unittest.TestCase):
    def test_all_five_workflows_registered(self):
        mapping = safe_load(MAPPING.read_text(encoding="utf-8"))
        reg = mapping["workflow_registry"]
        self.assertEqual(set(reg), set(WORKFLOWS))

    def test_input_modes(self):
        mapping = safe_load(MAPPING.read_text(encoding="utf-8"))
        reg = mapping["workflow_registry"]
        for wf in ("01_Exterior_Hero", "03_Material_Detail",
                   "04_Drone_Aerial", "05_Slow_Walkthrough"):
            self.assertEqual(reg[wf]["input_mode"], "I2VA", wf)
        self.assertEqual(reg["02_Day_Night_Transition"]["input_mode"], "FL2VA")
        self.assertEqual(reg["02_Day_Night_Transition"]["supported_input"],
                         ["first_frame", "last_frame"])

    def test_native_assets_exist(self):
        mapping = safe_load(MAPPING.read_text(encoding="utf-8"))
        reg = mapping["workflow_registry"]
        for wf in WORKFLOWS:
            asset = SYSTEM_ROOT / reg[wf]["native_asset"]
            self.assertTrue(asset.is_file(), f"{wf}: {asset}")

    def test_registry_validation_json_consistent(self):
        validation = json.loads(REGISTRY_VALIDATION.read_text(encoding="utf-8"))
        self.assertEqual(validation["result"], "ALL_PASS")
        self.assertEqual(set(validation["workflows"]), set(WORKFLOWS))


class TestInputMode(unittest.TestCase):
    def test_i2va_requires_one_reference(self):
        adapter = NativeRuntimeAdapter(client=FakeClient())
        with self.assertRaises(ValueError):
            adapter.prepare(make_request("03_Material_Detail",
                                         refs=["a.png", "b.png"]))

    def test_fl2va_requires_two_references(self):
        adapter = NativeRuntimeAdapter(client=FakeClient())
        with self.assertRaises(ValueError):
            adapter.prepare(make_request("02_Day_Night_Transition",
                                         refs=["DAY.png"]))

    def test_fl2va_first_last_no_swap(self):
        adapter = NativeRuntimeAdapter(client=FakeClient())
        native = adapter.prepare(make_request(
            "02_Day_Night_Transition",
            refs=["02_Day_Night_Transition--DAY.png",
                  "02_Day_Night_Transition--NIGHT.png"]))
        payload = native["translated_payload"]
        loads = {k: v["inputs"].get("image") for k, v in payload.items()
                 if v["class_type"] == "LoadImage"}
        self.assertEqual(loads.get("1"), "02_Day_Night_Transition--DAY.png")
        self.assertEqual(loads.get("16"), "02_Day_Night_Transition--NIGHT.png")
        self.assertIn("last_frame", payload["6"]["inputs"])


class TestParameterMapping(unittest.TestCase):
    def test_all_workflows_parameter_injection(self):
        adapter = NativeRuntimeAdapter(client=FakeClient())
        for wf in WORKFLOWS:
            native = adapter.prepare(make_request(wf, seed=777888900))
            p = native["translated_payload"]
            self.assertEqual(p["6"]["inputs"]["width"], 1344, wf)
            self.assertEqual(p["6"]["inputs"]["height"], 768, wf)
            self.assertEqual(p["6"]["inputs"]["length"], 107, wf)
            self.assertEqual(p["9"]["inputs"]["noise_seed"], 777888900, wf)
            self.assertEqual(p["14"]["inputs"]["fps"], 24.0, wf)
            self.assertIn("C2B", p["15"]["inputs"]["filename_prefix"], wf)

    def test_camera_not_supported_rejected(self):
        adapter = NativeRuntimeAdapter(client=FakeClient())
        with self.assertRaises(ValueError):
            adapter.prepare(make_request("05_Slow_Walkthrough", camera="aerial_reveal"))
        with self.assertRaises(ValueError):
            adapter.prepare(make_request("02_Day_Night_Transition", camera="walkthrough"))


class TestOutputCollector(unittest.TestCase):
    def test_collect_animated_image_output(self):
        client = ComfyUIClient(output_root=r"C:\mock\output")
        out = client.collect_output({
            "outputs": {"15": {"images": [
                {"filename": "02_C2B_00001_.mp4", "subfolder": "video",
                 "type": "output", "animated": True}]}}},
            "job-x", "02_Day_Night_Transition", metadata={})
        self.assertTrue(out["video_path"].endswith("video/02_C2B_00001_.mp4"))
        self.assertEqual(out["workflow_id"], "02_Day_Night_Transition")

    def test_missing_output_rejected(self):
        client = ComfyUIClient(output_root=r"C:\mock\output")
        with self.assertRaises(ComfyUIExecutionError):
            client.collect_output({"outputs": {"15": {"images": []}}},
                                  "job-x", "01_Exterior_Hero")


class TestErrorMapping(unittest.TestCase):
    def test_offline_runtime_error(self):
        adapter = NativeRuntimeAdapter(client=FakeClient(offline=True))
        with self.assertRaises(RuntimeError):
            adapter.generate(make_request("05_Slow_Walkthrough"))

    def test_timeout(self):
        adapter = NativeRuntimeAdapter(client=FakeClient(timeout=True))
        with self.assertRaises(GenerationTimeoutError):
            adapter.generate(make_request("03_Material_Detail"))

    def test_unknown_workflow(self):
        adapter = NativeRuntimeAdapter(client=FakeClient())
        adapter.workflow_mapping["workflow_registry"] = {}
        with self.assertRaises(WorkflowNotFoundError):
            adapter.prepare(make_request("01_Exterior_Hero"))

    def test_execution_error_maps_to_gpu_failed(self):
        adapter = NativeRuntimeAdapter(client=FakeClient(fail=True))
        with self.assertRaises(ComfyUIExecutionError):
            adapter.generate(make_request("04_Drone_Aerial"))
        job_id = next(iter(adapter.jobs))
        self.assertEqual(adapter.status(job_id)["existing_job_status"], "GPU_FAILED")


if __name__ == "__main__":
    unittest.main()
