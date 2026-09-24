"""RC3.4 PATCH2.7-D - UI -> Runtime binding tests (NO real GPU).

Covers: API contract stability, VideoGenerationRequest construction, state
transitions (no auto retry), unified output package on real-run completion.
Uses a FakeRuntimeAdapter; no ComfyUI / GPU call.
"""

import base64
import json
import sys
import tempfile
import time
import unittest
import zlib
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from apps.architect_video_studio.mock_api.intent_api import IntentAPI  # noqa: E402
from apps.architect_video_studio.mock_api.job_api import JobAPI  # noqa: E402
from apps.architect_video_studio.mock_api.output_api import OutputAPI  # noqa: E402
from apps.architect_video_studio.mock_api.project_api import ProjectAPI  # noqa: E402
from apps.architect_video_studio.mock_api.prompt_api import PromptAPI  # noqa: E402
from apps.architect_video_studio.mock_api.reference_api import ReferenceAPI  # noqa: E402
from apps.architect_video_studio.mock_api.store import StudioStore  # noqa: E402
from apps.architect_video_studio.mock_api.study_state import build_study_state  # noqa: E402
from runtime.prompt_provenance import is_current_prompt, reference_asset_hash  # noqa: E402
from runtime.adapters.runtime_adapter import validate_request  # noqa: E402
from runtime.adapters.golden_workflow_binding import bind_golden_workflow  # noqa: E402
from runtime.adapters.production_workflow_binding import canonical_workflow_sha256  # noqa: E402
from runtime.reference_contract import resolve_selected_references  # noqa: E402


def tiny_png_b64(color=(255, 255, 255)) -> str:
    def chunk(tag: bytes, data: bytes) -> bytes:
        import struct
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    ihdr = b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", ihdr)
           + chunk(b"IDAT", zlib.compress(b"\x00" + bytes(color)))
           + chunk(b"IEND", b""))
    return base64.b64encode(png).decode()


class FakeRuntimeAdapter:
    """In-memory stand-in for the RuntimeAdapter (no GPU)."""

    def __init__(self, fail: bool = False, video_dir: Path | None = None) -> None:
        self.fail = fail
        self.video_dir = video_dir
        self.last_request = None
        self.job_id = "fake-rt-0001"

    def generate(self, request):
        self.last_request = request
        if self.fail:
            raise RuntimeError("fake runtime failure")
        return {"job_id": self.job_id, "status": "COMPLETED",
                "prompt_id": "fake-prompt"}

    def get_output(self, job_id):
        video = self.video_dir / "fake.mp4"
        video.write_bytes(b"FAKE-MP4-CONTAINER")
        return {
            "job_id": job_id,
            "video_path": str(video),
            "preview_path": str(self.video_dir / "preview.png"),
            "metadata": {"prompt_hash": "B" * 64},
            "runtime_info": {
                "adapter": "fake-native", "gpu_invoked": False,
                "comfyui_invoked": False, "native_runtime_invoked": True,
                "prompt_id": "fake-prompt",
            },
        }


class BoundTraceRuntimeAdapter(FakeRuntimeAdapter):
    """Builds a real Golden API payload, then stops before any GPU work."""

    def preflight(self):
        return None

    def prepare(self, request):
        payload = bind_golden_workflow({
            "study_id": request.study_id,
            "reference_assets": request.reference_assets,
            "generation_parameters": request.generation_parameters,
            "prompt_payload": request.prompt_payload,
        }, request.workflow_id)
        self.bound_payload = payload
        return {"translated_payload": payload}

    def generate(self, request, prepared=None):
        self.last_request = request
        self.bound_sha = canonical_workflow_sha256(prepared["translated_payload"])
        raise RuntimeError("intentional CPU-only trace boundary")


class Harness:
    def __init__(self, adapter=None):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.store = StudioStore(root / "data")
        self.comfy_input = root / "comfy_input"
        self.comfy_input.mkdir(exist_ok=True)
        self.project_api = ProjectAPI(self.store)
        self.reference_api = ReferenceAPI(self.store)
        self.intent_api = IntentAPI(self.store)
        self.prompt_api = PromptAPI(self.store)
        self.output_api = OutputAPI(self.store)
        self.adapter = adapter or FakeRuntimeAdapter(video_dir=root)
        self.job_api = JobAPI(
            self.store, output_api=self.output_api,
            runtime_adapter=self.adapter,
            comfy_input_dir=str(self.comfy_input))

    def full_project(self, name="绑定测试") -> str:
        pid = self.project_api.create_project(name, "exterior", "方案")["id"]
        ref = self.reference_api.upload_reference(
            pid, "01_Exterior_Hero.png", role="first_frame",
            data_base64=tiny_png_b64())
        self.reference_api.approve_reference(pid, ref["id"])
        self.intent_api.analyze_intent(pid, "做一个建筑外观主视角展示视频")
        self.prompt_api.generate_prompt(pid)
        return pid

    def close(self):
        for thread in list(getattr(self.job_api, "_threads", {}).values()):
            thread.join(timeout=2)
        try:
            self.tmp.cleanup()
        except OSError:
            pass  # best-effort temp cleanup on Windows


class TestApiContract(unittest.TestCase):
    def test_offline_prompt_can_record_standard_candidate_but_job_stays_blocked(self):
        h = Harness()
        try:
            pid = h.full_project()
            params = {"quality": "STANDARD", "duration": 4.0,
                      "fps": 24, "seed": 42}

            with self.assertRaisesRegex(ValueError,
                                        "QUALITY_PROFILE_UNAVAILABLE:STANDARD"):
                h.prompt_api.generate_prompt(pid, generation_parameters=params)

            prompt = h.prompt_api.generate_prompt(
                pid, generation_parameters=params,
                prompt_engine="OFFLINE_COMPILER", image_consent=False)
            self.assertTrue(prompt["verified"]["pass"], prompt["verified"])
            self.assertEqual(prompt["provider"], "OFFLINE_COMPILER")
            self.assertEqual(prompt["engine_mode"], "OFFLINE_COMPILER")
            self.assertEqual(prompt["a4_profile"]["availability"],
                             "CANDIDATE_FOR_A4_2")
            self.assertEqual(
                (prompt["generation_parameters"]["width"],
                 prompt["generation_parameters"]["height"]),
                (1248, 704))
            self.assertEqual(prompt["reference_bindings"][0]["role"],
                             "first_frame")

            intent = h.store.load_intent(pid)["natural_language"]
            approved = resolve_selected_references(
                pid, h.store.load_project(pid), h.store.load_references(pid),
                prompt["workflow"], require_approved=True,
                reference_root=h.store.input_dir(pid))
            self.assertTrue(is_current_prompt(
                prompt, intent=intent, workflow=prompt["workflow"],
                reference_hash=reference_asset_hash(approved),
                parameters=prompt["generation_parameters"],
                provider="OFFLINE_COMPILER", allow_a4_2_candidate=True))
            study = build_study_state(h.store, pid)
            self.assertTrue(study["prompt_ready"], study.get("gate_reasons"))
            self.assertFalse(study["generate_allowed"])
            self.assertFalse(study["prompt_confirmed"])
            self.assertEqual(study["generation_status"], "PROMPT_REVIEW")
            self.assertTrue(any(
                "STANDARD" in reason and "A4.2" in reason
                for reason in study["gate_reasons"]))

            # Prompt provenance is now current for review, but the normal Job
            # route must still reject this unaccepted quality candidate.
            with self.assertRaisesRegex(ValueError,
                                       "QUALITY_PROFILE_UNAVAILABLE:STANDARD"):
                h.job_api.submit_job(
                    pid, seed=42, risk_reviewed=True,
                    generation_parameters=params)
            self.assertEqual(h.store.load_jobs(pid), {})
        finally:
            h.close()

    def test_submit_accepts_generation_params_and_camera(self):
        h = Harness()
        try:
            pid = h.full_project()
            h.prompt_api.generate_prompt(
                pid, generation_parameters={"quality": "high", "duration": 4.0})
            job = h.job_api.submit_job(
                pid, seed=777888999, risk_reviewed=True,
                generation_parameters={"fps": 24, "duration": 4.0, "quality": "high"},
                camera_motion="slow_push")
            for field in ("id", "project_id", "workflow", "state", "seed",
                          "prompt_hash", "stages", "runtime"):
                self.assertIn(field, job, field)
            self.assertEqual(job["workflow"], "01_Exterior_Hero")
            self.assertEqual(job["seed"], 777888999)
            self.assertEqual(job["camera_motion"], "slow_push")
            self.assertEqual(job["runtime"], "native")
            self.assertEqual(job["generation_parameters"]["resolution"], "1344x768")
        finally:
            h.close()

    def test_list_jobs_shape(self):
        h = Harness()
        try:
            pid = h.full_project()
            h.job_api.submit_job(pid, risk_reviewed=True)
            jobs = h.job_api.list_jobs(pid)
            self.assertEqual(len(jobs), 1)
            self.assertIn("state", jobs[0])
        finally:
            h.close()


class TestRuntimeRequest(unittest.TestCase):
    def test_prompt_record_contains_versioned_automatic_profiles(self):
        h = Harness()
        try:
            pid = h.full_project()
            prompt = h.store.load_prompt(pid)
            self.assertEqual(prompt["a4_profile"]["quality_profile"], "NATIVE_HIGH")
            self.assertEqual(prompt["a4_profile"]["architecture_profile"], "exterior_hero")
            self.assertTrue(prompt["prompt_profile_version"])
            self.assertIn("Preserve the reference building's overall massing", prompt["prompt"])
            self.assertTrue(prompt["verified"]["pass"])
        finally:
            h.close()

    def test_job_trace_uses_exact_bound_golden_sha_and_values(self):
        adapter = BoundTraceRuntimeAdapter()
        h = Harness(adapter=adapter)
        try:
            pid = h.full_project()
            job = h.job_api.submit_job(pid, seed=73, risk_reviewed=True)
            deadline = time.time() + 5
            detail = None
            while time.time() < deadline:
                detail = h.job_api.get_job_detail(job["id"])
                if detail["technical_details"]["execution_trace"].get("workflow_sha256"):
                    break
                time.sleep(0.05)
            trace = detail["technical_details"]["execution_trace"]
            self.assertEqual(trace["status"], "BOUND")
            self.assertEqual(trace["workflow_sha256"], adapter.bound_sha)
            self.assertEqual(trace["quality_profile"], "NATIVE_HIGH")
            self.assertEqual(trace["architecture_profile"], "exterior_hero")
            self.assertEqual(trace["architecture_profile_version"], "a4-architecture-v1")
            self.assertEqual(trace["workflow_id"], "01_Exterior_Hero")
            self.assertEqual(trace["final_execution_parameters"]["seed"], 73)
            self.assertEqual(trace["final_execution_parameters"]["resolution"], "1344x768")
            self.assertTrue(trace["quality_profile_version"])
            self.assertTrue(trace["prompt_profile_version"])
        finally:
            h.close()

    def test_builds_valid_video_generation_request(self):
        h = Harness()
        try:
            pid = h.full_project()
            h.prompt_api.generate_prompt(
                pid, generation_parameters={"quality": "high", "duration": 4.0})
            h.job_api.submit_job(
                pid, seed=42, risk_reviewed=True,
                generation_parameters={"fps": 24, "duration": 4.0, "quality": "high"},
                camera_motion="slow_push")
            deadline = time.time() + 5
            while h.adapter.last_request is None and time.time() < deadline:
                time.sleep(0.05)
            request = h.adapter.last_request
            self.assertIsNotNone(request)
            data = request.to_dict()
            self.assertEqual(validate_request(data), [])
            self.assertEqual(data["workflow_id"], "01_Exterior_Hero")
            self.assertEqual(data["camera_motion"], "slow_push")
            self.assertEqual(data["generation_parameters"]["seed"], 42)
            self.assertTrue(data["gates"]["reference_approved"])
            self.assertTrue(data["gates"]["risk_reviewed"])
            # UI must not build a ComfyUI payload: no node class_type anywhere.
            dumped = json.dumps(data)
            self.assertNotIn("class_type", dumped)
            self.assertNotIn("translated_payload", dumped)
            tampered = json.loads(json.dumps(data))
            tampered["generation_parameters"]["frame_count"] += 1
            self.assertTrue(any(
                "generation_parameters.frame_count" in error
                for error in validate_request(tampered)))
            for key, invalid in (("steps", 49), ("sampler_mode", "res_multistep"),
                                 ("native_generation_fps", 30),
                                 ("scheduler", "karras"), ("denoise", 0.5),
                                 ("acceleration", "auto")):
                altered = json.loads(json.dumps(data))
                altered["generation_parameters"][key] = invalid
                with self.subTest(parameter=key):
                    self.assertTrue(any(
                        f"generation_parameters.{key}" in error
                        for error in validate_request(altered)))
        finally:
            h.close()

    def test_maximum_requested_duration_survives_prompt_and_native_binding(self):
        adapter = BoundTraceRuntimeAdapter()
        h = Harness(adapter=adapter)
        try:
            project_id = h.full_project()
            params = {"quality": "high", "duration": 15.0, "fps": 24}
            prompt = h.prompt_api.generate_prompt(
                project_id, generation_parameters=params)
            native = prompt["a4_profile"]["native_generation"]
            self.assertEqual(native["frame_count"], 362)
            self.assertAlmostEqual(native["duration_seconds"], 362 / 24, places=6)

            job = h.job_api.submit_job(
                project_id, seed=73, risk_reviewed=True,
                generation_parameters=params, camera_motion="slow_push")
            deadline = time.time() + 5
            detail = None
            while time.time() < deadline:
                detail = h.job_api.get_job_detail(job["id"])
                trace = detail["technical_details"]["execution_trace"]
                if trace.get("workflow_sha256") or detail["state"] == "FAILED":
                    break
                time.sleep(0.05)
            trace = detail["technical_details"]["execution_trace"]
            self.assertEqual(trace["status"], "BOUND")
            self.assertEqual(trace["final_execution_parameters"]["frame_count"], 362)
            self.assertAlmostEqual(
                trace["final_execution_parameters"]["duration_seconds"],
                362 / 24, places=6)
            self.assertEqual(
                trace["final_execution_parameters"]["requested_duration_seconds"],
                15.0)
        finally:
            h.close()

    def test_job_rejects_stale_a4_profile_identity(self):
        h = Harness()
        try:
            pid = h.full_project()
            valid_prompt = h.store.load_prompt(pid)
            variants = []
            for field, wrong_value in (
                    ("architecture_profile", "drone_aerial"),
                    ("prompt_profile_version", "obsolete-profile-version"),
                    ("workflow_id", "04_Drone_Aerial")):
                candidate = json.loads(json.dumps(valid_prompt))
                candidate["a4_profile"][field] = wrong_value
                variants.append((field, candidate))
            stale_workflow = json.loads(json.dumps(valid_prompt))
            stale_workflow["workflow"] = "04_Drone_Aerial"
            variants.append(("workflow", stale_workflow))

            for label, candidate in variants:
                with self.subTest(identity_field=label):
                    h.store.save_prompt(pid, candidate)
                    with self.assertRaisesRegex(
                            ValueError,
                            "WORKFLOW_PROMPT_MISMATCH|A4_PROFILE_PROMPT_MISMATCH"):
                        h.job_api.submit_job(pid, risk_reviewed=True)
            h.store.save_prompt(pid, valid_prompt)
        finally:
            h.close()


class TestStateTransitions(unittest.TestCase):
    def test_real_job_completes(self):
        h = Harness()
        try:
            pid = h.full_project()
            job = h.job_api.submit_job(pid, risk_reviewed=True)
            self.assertEqual(job["state"], "PREPARING")
            deadline = time.time() + 8
            final = None
            while time.time() < deadline:
                final = h.job_api.get_job(job["id"])
                if final["state"] == "COMPLETED":
                    break
                time.sleep(0.1)
            self.assertEqual(final["state"], "COMPLETED")
            self.assertTrue(final["package_built"])
            self.assertIn("COMPLETED", final["stages"])
        finally:
            h.close()

    def test_failure_no_auto_retry(self):
        h = Harness(adapter=FakeRuntimeAdapter(fail=True))
        try:
            pid = h.full_project()
            job = h.job_api.submit_job(pid, risk_reviewed=True)
            deadline = time.time() + 8
            final = None
            while time.time() < deadline:
                final = h.job_api.get_job(job["id"])
                if final["state"] == "FAILED":
                    break
                time.sleep(0.1)
            # A generic adapter failure is not evidence of CUDA/model
            # execution; GPU_FAILED is reserved for direct GPU/OOM evidence.
            self.assertEqual(final["state"], "FAILED")
            self.assertEqual(final["error_category"], "COMFYUI_ERROR")
            self.assertIn("fake runtime failure", final["failure_reason"])
            # no auto retry: still terminal after waiting
            time.sleep(0.5)
            self.assertEqual(h.job_api.get_job(job["id"])["state"], "FAILED")
        finally:
            h.close()

    def test_cancel_terminal_no_retry(self):
        h = Harness()
        try:
            pid = h.full_project()
            job = h.job_api.submit_job(pid, risk_reviewed=True)
            # cancel before the fast fake completes
            h.job_api.cancel(job["id"])
            self.assertEqual(h.job_api.get_job(job["id"])["state"], "CANCELLED")
            with self.assertRaises(ValueError):
                h.job_api.cancel(job["id"])
        finally:
            h.close()


class TestOutputPackage(unittest.TestCase):
    def test_unified_package_on_completion(self):
        h = Harness()
        try:
            pid = h.full_project()
            job = h.job_api.submit_job(pid, seed=777888999, risk_reviewed=True)
            deadline = time.time() + 8
            while time.time() < deadline:
                if h.job_api.get_job(job["id"])["state"] == "COMPLETED":
                    break
                time.sleep(0.1)
            pkg = h.store.package_dir(pid)
            for sub in ("input", "workflow", "prompt", "output", "report"):
                self.assertTrue((pkg / sub).is_dir(), sub)
            self.assertTrue((pkg / "output" / "video.mp4").is_file())
            self.assertTrue((pkg / "report" / "runtime_info.json").is_file())
            self.assertTrue((pkg / "report" / "provenance.json").is_file())
            self.assertTrue((pkg / "report" / "generation_report.json").is_file())
            self.assertTrue((pkg / "prompt" / "prompt.json").is_file())
            self.assertTrue(any((pkg / "workflow").glob("*.json")))
            runtime = json.loads((pkg / "report" / "runtime_info.json")
                                 .read_text(encoding="utf-8"))
            self.assertTrue(runtime["native_runtime_invoked"])
            manifest = h.output_api.manifest(pid, h.store.load_jobs(pid)[job["id"]])
            self.assertIn("video.mp4", manifest["structure"]["output"])
        finally:
            h.close()


class TestA41DayNightContract(unittest.TestCase):
    workflow = "02_Day_Night_Transition"

    def _ready_day_night_study(self, h):
        project = h.project_api.create_project("A4.1 dual reference", "exterior", "方案")
        project_id = project["id"]
        h.reference_api.upload_and_approve(
            project_id, "start.png", role="first_frame",
            data_base64=tiny_png_b64((240, 240, 240)))
        h.reference_api.upload_and_approve(
            project_id, "end.png", role="last_frame",
            data_base64=tiny_png_b64((24, 24, 24)))
        h.intent_api.analyze_intent(
            project_id, "Show the building changing from daylight to night lighting.")
        h.intent_api.select_workflow(project_id, self.workflow)
        return project_id

    def test_study_prompt_job_binder_and_diagnostics_preserve_two_roles(self):
        adapter = BoundTraceRuntimeAdapter()
        h = Harness(adapter=adapter)
        try:
            project_id = self._ready_day_night_study(h)
            study = h.project_api.get_project_detail(project_id)["study"]
            self.assertEqual(study["required_reference_roles"],
                             ["first_frame", "last_frame"])
            self.assertTrue(study["reference_approved"], study["gate_reasons"])
            self.assertEqual([item["role"] for item in study["reference_bindings"]],
                             ["first_frame", "last_frame"])
            self.assertEqual(len({item["sha256"] for item in study["reference_bindings"]}), 2)

            params = {"quality": "PREVIEW", "duration": 5.0, "fps": 24}
            prompt = h.prompt_api.generate_prompt(
                project_id, workflow=self.workflow,
                generation_parameters=params, prompt_engine="OFFLINE_COMPILER")
            self.assertTrue(prompt["verified"]["pass"], prompt["verified"])
            self.assertEqual([item["role"] for item in prompt["reference_bindings"]],
                             ["first_frame", "last_frame"])
            self.assertEqual(prompt["a4_profile"]["quality_profile"], "PREVIEW")
            self.assertEqual(prompt["a4_profile"]["native_generation"]["frame_count"], 124)
            self.assertAlmostEqual(
                prompt["a4_profile"]["native_generation"]["duration_seconds"],
                124 / 24, places=6)

            job = h.job_api.submit_job(
                project_id, seed=73, risk_reviewed=True,
                generation_parameters=params, camera_motion="static")
            deadline = time.time() + 5
            detail = None
            while time.time() < deadline:
                detail = h.job_api.get_job_detail(job["id"])
                trace = detail["technical_details"]["execution_trace"]
                if trace.get("workflow_sha256") or detail["state"] == "FAILED":
                    break
                time.sleep(0.05)

            trace = detail["technical_details"]["execution_trace"]
            self.assertEqual(trace["status"], "BOUND")
            self.assertEqual(trace["reference_bindings"], prompt["reference_bindings"])
            self.assertEqual(trace["final_execution_parameters"]["frame_count"], 124)
            self.assertAlmostEqual(
                trace["final_execution_parameters"]["duration_seconds"],
                124 / 24, places=6)
            self.assertEqual(
                trace["final_execution_parameters"]["requested_duration_seconds"], 5.0)
            self.assertEqual([item["role"] for item in detail["references"]],
                             ["first_frame", "last_frame"])
            self.assertEqual(trace["workflow_sha256"], adapter.bound_sha)

            graph = adapter.bound_payload
            by_id = {str(node_id): node for node_id, node in graph.items()}
            h3 = next(node for node in graph.values()
                      if node.get("class_type") == "MiniMaxH3ImageToVideo")
            first_node_id = str(h3["inputs"]["first_frame"][0])
            last_node_id = str(h3["inputs"]["last_frame"][0])
            staged_refs = adapter.last_request.reference_assets
            self.assertEqual([item["role"] for item in staged_refs],
                             ["first_frame", "last_frame"])
            self.assertEqual(
                by_id[first_node_id]["inputs"]["image"],
                Path(staged_refs[0]["path_or_ref"]).name)
            self.assertEqual(
                by_id[last_node_id]["inputs"]["image"],
                Path(staged_refs[1]["path_or_ref"]).name)
            snapshot = h.store.load_jobs(project_id)[job["id"]]["workflow_snapshot"]
            self.assertEqual(snapshot["reference_bindings"], prompt["reference_bindings"])
            self.assertEqual(snapshot["workflow_hash"], canonical_workflow_sha256(graph))
            self.assertEqual(len(snapshot["reference_bindings"]), 2)
        finally:
            h.close()

    def test_reference_resolver_rejects_missing_same_id_cross_project_unapproved_and_stale(self):
        h = Harness()
        try:
            project_id = self._ready_day_night_study(h)
            project = h.store.load_project(project_id)
            refs = h.store.load_references(project_id)
            selected = dict(project["selected_reference_asset_ids"])

            missing_first = dict(project)
            missing_first["selected_reference_asset_ids"] = {
                "last_frame": selected["last_frame"]}
            missing_first["current_reference_asset_id"] = None
            with self.assertRaisesRegex(ValueError, "REFERENCE_ROLE_REQUIRED:first_frame"):
                resolve_selected_references(
                    project_id, missing_first, refs, self.workflow,
                    reference_root=h.store.input_dir(project_id))

            missing_last = dict(project)
            missing_last["selected_reference_asset_ids"] = {"first_frame": selected["first_frame"]}
            with self.assertRaisesRegex(ValueError, "REFERENCE_ROLE_REQUIRED:last_frame"):
                resolve_selected_references(
                    project_id, missing_last, refs, self.workflow,
                    reference_root=h.store.input_dir(project_id))

            same = dict(project)
            same["selected_reference_asset_ids"] = {
                "first_frame": selected["first_frame"],
                "last_frame": selected["first_frame"],
            }
            with self.assertRaisesRegex(ValueError, "REFERENCE_DUPLICATE_ASSET_ID"):
                resolve_selected_references(
                    project_id, same, refs, self.workflow,
                    reference_root=h.store.input_dir(project_id))

            foreign_refs = dict(refs)
            foreign_refs[selected["last_frame"]] = {
                **foreign_refs[selected["last_frame"]], "project_id": "proj-foreign"}
            with self.assertRaisesRegex(ValueError, "REFERENCE_CROSS_PROJECT:last_frame"):
                resolve_selected_references(
                    project_id, project, foreign_refs, self.workflow,
                    reference_root=h.store.input_dir(project_id))

            pending_refs = dict(refs)
            pending_refs[selected["last_frame"]] = {
                **pending_refs[selected["last_frame"]], "state": "PENDING"}
            with self.assertRaisesRegex(ValueError, "REFERENCE_NOT_APPROVED:last_frame"):
                resolve_selected_references(
                    project_id, project, pending_refs, self.workflow,
                    reference_root=h.store.input_dir(project_id))

            changed_refs = dict(refs)
            changed = dict(changed_refs[selected["last_frame"]])
            Path(changed["stored_path"]).write_bytes(b"content changed after approval")
            changed_refs[selected["last_frame"]] = changed
            with self.assertRaisesRegex(ValueError, "REFERENCE_STALE_CONTENT:last_frame"):
                resolve_selected_references(
                    project_id, project, changed_refs, self.workflow,
                    reference_root=h.store.input_dir(project_id))
        finally:
            h.close()

    def test_api_rejects_duplicate_content_for_opposite_endpoints(self):
        h = Harness()
        try:
            project = h.project_api.create_project("Duplicate endpoints", "exterior", "方案")
            project_id = project["id"]
            same = tiny_png_b64((128, 128, 128))
            h.reference_api.upload_and_approve(
                project_id, "start.png", role="first_frame", data_base64=same)
            with self.assertRaisesRegex(ValueError, "REFERENCE_DUPLICATE_CONTENT"):
                h.reference_api.upload_and_approve(
                    project_id, "end.png", role="last_frame", data_base64=same)
        finally:
            h.close()


if __name__ == "__main__":
    unittest.main()
