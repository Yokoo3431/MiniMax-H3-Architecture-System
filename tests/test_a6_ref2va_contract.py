"""A6 Ref2VA CPU-only schema, binding, and Study reference-board contracts."""

from __future__ import annotations

import base64
import hashlib
import json
import struct
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import zlib
from pathlib import Path
from types import SimpleNamespace
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from apps.architect_video_studio.mock_api.job_api import JobAPI  # noqa: E402
from apps.architect_video_studio.mock_api.intent_api import IntentAPI  # noqa: E402
from apps.architect_video_studio.mock_api.prompt_api import PromptAPI  # noqa: E402
from apps.architect_video_studio.mock_api.project_api import ProjectAPI  # noqa: E402
from apps.architect_video_studio.mock_api.reference_api import ReferenceAPI  # noqa: E402
from apps.architect_video_studio.mock_api.server import StudioServer  # noqa: E402
from apps.architect_video_studio.mock_api.store import StudioStore  # noqa: E402
from apps.architect_video_studio.mock_api.study_state import build_study_state  # noqa: E402
from runtime.adapters.ref2va_workflow_binding import (  # noqa: E402
    REF2VA_MODEL, Ref2VAWorkflowError, compile_ref2va_workflow,
)
from runtime.h3_prompt_engine import OfflineH3Compiler, PromptReasoningRequest  # noqa: E402
from runtime.reference_contract import (  # noqa: E402
    build_ref2va_reference_plan, reference_bindings,
    ref2va_schema_capabilities,
)


def tiny_png(color=(255, 255, 255)) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        payload = struct.pack(">I", len(data)) + tag + data
        return payload + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    raw = b"\x00" + bytes(color)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def image_ref(asset_id: str, role: str, color: str, *, project="study") -> dict:
    return {
        "id": asset_id, "project_id": project, "role": role,
        "media_type": "image", "state": "APPROVED",
        "sha256": hashlib.sha256(color.encode()).hexdigest(),
        "source_identity": f"sha256:{hashlib.sha256(color.encode()).hexdigest()}",
        "filename": f"{asset_id}.png", "path_or_ref": f"{asset_id}.png",
    }


def node_info(*, include_checkpoint=True, include_vae=True) -> dict:
    models = ["minimax_h3_fl2va_pruned_int8.safetensors"]
    if include_checkpoint:
        models.append(REF2VA_MODEL)
    vaes = ["minimax_h3_video_vae_fp16.safetensors"] if include_vae else ["other.safetensors"]
    return {
        "MiniMaxH3ReferenceToVideo": {
            "input": {
                "required": {
                    **{name: [] for name in (
                        "clip", "prompt", "width", "height", "length")},
                    "ref_image_size": ["COMBO", {"options": ["match", "max"]}],
                },
                "optional": {
                    "vae": [], "audio_vae": [],
                    "ref_images": ["IMAGE", {"template": {"max": 9}}],
                    "ref_videos": ["IMAGE", {"template": {"max": 3}}],
                    "ref_video_audios": ["AUDIO", {"template": {"max": 3}}],
                    "ref_audios": ["AUDIO", {"template": {"max": 3}}],
                },
            },
            "output": ["CONDITIONING", "LATENT"],
        },
        "UNETLoader": {"input": {"required": {"unet_name": [models]}}},
        "VAELoader": {"input": {"required": {"vae_name": [vaes]}}},
    }


def base_graph() -> dict:
    return {
        "1": {"class_type": "LoadImage", "inputs": {"image": "old.png"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "clip.safetensors"}},
        "3": {"class_type": "UNETLoader", "inputs": {
            "unet_name": "minimax_h3_fl2va_pruned_int8.safetensors"}},
        "4": {"class_type": "VAELoader", "inputs": {
            "vae_name": "minimax_h3_video_vae_fp16.safetensors"}},
        "5": {"class_type": "MiniMaxH3ImageToVideo", "inputs": {
            "clip": ["2", 0], "vae": ["4", 0],
            "prompt": "subject_definitions: <Picture 1> and <Picture 2>\n\n"
                      "summary: architecture\n\ndetailed_description: architecture",
            "width": 1344, "height": 768, "length": 107,
            "first_frame": ["1", 0],
        }},
        "6": {"class_type": "BasicGuider", "inputs": {"conditioning": ["5", 0]}},
        "7": {"class_type": "SaveVideo", "inputs": {"video": ["6", 0]}},
    }


class Ref2VAContractTests(unittest.TestCase):
    def setUp(self):
        self.schema = node_info()

    def test_live_schema_contract_requires_fields_outputs_and_dynamic_limits(self):
        capability = ref2va_schema_capabilities(self.schema)
        self.assertTrue(capability["available"])
        self.assertEqual(capability["limits"], {"image": 9, "video": 3, "audio": 3})
        self.assertEqual(capability["outputs"], ["CONDITIONING", "LATENT"])
        broken = json.loads(json.dumps(self.schema))
        del broken["MiniMaxH3ReferenceToVideo"]["input"]["required"]["ref_image_size"]
        self.assertFalse(ref2va_schema_capabilities(broken)["available"])

    def test_reference_plan_is_ordered_and_uses_flat_dynamic_api_input_keys(self):
        refs = [image_ref("site", "site_reference", "site"),
                image_ref("first", "first_frame", "first"),
                image_ref("style", "style_reference", "style")]
        plan = build_ref2va_reference_plan(
            refs, self.schema, project_id="study", runtime_id="experimental-h3-8190",
            video_vae_available=True)
        bindings = plan["bindings"]
        self.assertEqual([item["role"] for item in bindings],
                         ["first_frame", "style_reference", "site_reference"])
        self.assertEqual([item["native_input"] for item in bindings],
                         ["ref_images.ref_image_0", "ref_images.ref_image_1",
                          "ref_images.ref_image_2"])
        self.assertEqual([item["prompt_tag"] for item in bindings],
                         ["<Picture 1>", "<Picture 2>", "<Picture 3>"])
        self.assertNotIn("ref_images", bindings[0])
        self.assertEqual(bindings[0]["requested_fidelity"], "match")
        self.assertEqual(bindings[0]["runtime_compatibility"],
                         "experimental-h3-8190")
        self.assertTrue(bindings[0]["validation_evidence"]["approved"])
        self.assertEqual(plan["reference_image_size"], "match")

    def test_plan_sanitizes_source_identity_and_rejects_invalid_content_hash(self):
        reference = image_ref("site", "site_reference", "site")
        reference["source_identity"] = r"C:\private\reference.png"
        binding = reference_bindings([reference], ref2va=True)[0]
        self.assertFalse(binding["validation_evidence"][
            "source_identity_matches_content"])
        self.assertNotIn("project_match", binding["validation_evidence"])
        plan = build_ref2va_reference_plan(
            [reference], self.schema, project_id="study",
            runtime_id="experimental-h3-8190", video_vae_available=True)
        digest = reference["sha256"]
        self.assertEqual(plan["bindings"][0]["source_identity"], f"sha256:{digest}")
        self.assertFalse(plan["bindings"][0]["validation_evidence"][
            "source_identity_matches_content"])
        reference["sha256"] = "not-a-sha"
        with self.assertRaisesRegex(ValueError, "REF2VA_CONTENT_SHA256_INVALID"):
            build_ref2va_reference_plan(
                [reference], self.schema, project_id="study",
                runtime_id="experimental-h3-8190", video_vae_available=True)

    def test_ref2va_rejects_a5_guide_with_specific_contract_error(self):
        with self.assertRaisesRegex(ValueError, "REF2VA_TIMELINE_GUIDE_USES_ADDGUIDE"):
            build_ref2va_reference_plan(
                [image_ref("guide", "timeline_guide", "guide")], self.schema,
                project_id="study", runtime_id="experimental-h3-8190",
                video_vae_available=True)

    def test_ref2va_rejects_cross_project_unapproved_duplicates_and_missing_vae(self):
        cases = [
            ([image_ref("x", "identity_reference", "x", project="elsewhere")],
             True, "REF2VA_CROSS_PROJECT"),
            ([dict(image_ref("x", "identity_reference", "x"), state="PENDING")],
             True, "REF2VA_NOT_APPROVED"),
            ([image_ref("x", "identity_reference", "same"),
              image_ref("y", "style_reference", "same")], True,
             "REF2VA_DUPLICATE_CONTENT"),
            ([image_ref("x", "identity_reference", "x")], False,
             "REF2VA_VIDEO_VAE_REQUIRED"),
        ]
        for refs, video_vae, error in cases:
            with self.subTest(error=error), self.assertRaisesRegex(ValueError, error):
                build_ref2va_reference_plan(
                    refs, self.schema, project_id="study",
                    runtime_id="experimental-h3-8190",
                    video_vae_available=video_vae)

    def test_compiler_is_copy_only_and_emits_exact_dotted_slots(self):
        refs = [image_ref("first", "first_frame", "first"),
                image_ref("style", "style_reference", "style")]
        original = base_graph()
        result, plan = compile_ref2va_workflow(
            original, refs, self.schema, project_id="study",
            runtime_id="experimental-h3-8190")
        self.assertEqual(original["5"]["class_type"], "MiniMaxH3ImageToVideo")
        node = result["5"]
        self.assertEqual(node["class_type"], "MiniMaxH3ReferenceToVideo")
        self.assertEqual(node["inputs"]["ref_images.ref_image_0"], ["8", 0])
        self.assertEqual(node["inputs"]["ref_images.ref_image_1"], ["9", 0])
        self.assertNotIn("ref_images", node["inputs"])
        self.assertEqual(result["3"]["inputs"]["unet_name"], REF2VA_MODEL)
        self.assertEqual(plan["graph"]["load_image_node_ids"], ["8", "9"])

    def test_compiler_fails_closed_without_checkpoint_or_prompt_tags(self):
        refs = [image_ref("first", "first_frame", "first")]
        with self.assertRaisesRegex(Ref2VAWorkflowError, "REF2VA_CHECKPOINT_UNAVAILABLE"):
            compile_ref2va_workflow(
                base_graph(), refs, node_info(include_checkpoint=False),
                project_id="study", runtime_id="experimental-h3-8190")
        graph = base_graph()
        graph["5"]["inputs"]["prompt"] = "subject_definitions: generic"
        with self.assertRaisesRegex(Ref2VAWorkflowError,
                                    "REF2VA_PROMPT_TAG_BINDING_MISMATCH"):
            compile_ref2va_workflow(
                graph, refs, self.schema, project_id="study",
                runtime_id="experimental-h3-8190")
        incompatible_size = json.loads(json.dumps(self.schema))
        incompatible_size["MiniMaxH3ReferenceToVideo"]["input"]["required"][
            "ref_image_size"][1]["options"] = ["max"]
        with self.assertRaisesRegex(Ref2VAWorkflowError,
                                    "REF2VA_IMAGE_SIZE_UNAVAILABLE"):
            compile_ref2va_workflow(
                base_graph(), refs, incompatible_size, project_id="study",
                runtime_id="experimental-h3-8190")

    def test_compiler_requires_live_video_vae_loader_choice(self):
        with self.assertRaisesRegex(Ref2VAWorkflowError, "REF2VA_VIDEO_VAE_UNAVAILABLE"):
            compile_ref2va_workflow(
                base_graph(), [image_ref("first", "first_frame", "first")],
                node_info(include_vae=False), project_id="study",
                runtime_id="experimental-h3-8190")

    def test_offline_prompt_compiler_emits_matching_picture_roles(self):
        request = PromptReasoningRequest(
            mode="Ref2VA", duration=4.0, user_intent="保持建筑体量与场地关系",
            reference_role="multi_reference_roles", reference_count=2,
            workflow_id="04_Drone_Aerial", camera_motion="slow_push",
            reference_roles=("first_frame", "site_reference"),
        )
        prompt = OfflineH3Compiler().compile(request)
        self.assertIn("<Picture 1>", prompt["prompt"])
        self.assertIn("<Picture 2>", prompt["prompt"])
        self.assertIn("site context reference", prompt["prompt"])


class ReferenceBoardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = StudioStore(Path(self.temp.name) / "data")
        self.projects = ProjectAPI(self.store)
        self.api = ReferenceAPI(self.store)
        self.project = self.projects.create_project("A6 Contract Study")
        self.project_id = self.project["id"]

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def encoded(color):
        return base64.b64encode(tiny_png(color)).decode("ascii")

    def test_a6_approval_keeps_study_state_and_binds_only_after_approval(self):
        self.api.upload_and_approve(
            self.project_id, "first.png", "first_frame", self.encoded((255, 0, 0)))
        project = self.store.load_project(self.project_id)
        project["state"] = "USER_CONFIRM"
        self.store.save_project(project)
        uploaded = self.api.upload_reference(
            self.project_id, "identity.png", "identity_reference",
            self.encoded((0, 255, 0)))
        self.assertEqual(self.store.load_project(self.project_id)["state"], "USER_CONFIRM")
        self.assertNotIn("identity_reference",
                         self.store.load_project(self.project_id)["selected_reference_asset_ids"])
        approved = self.api.approve_reference(self.project_id, uploaded["id"])
        project = self.store.load_project(self.project_id)
        self.assertEqual(approved["state"], "APPROVED")
        self.assertEqual(project["state"], "USER_CONFIRM")
        self.assertEqual(project["selected_reference_asset_ids"]["identity_reference"],
                         uploaded["id"])

    def test_explicit_same_role_selection_checks_owner_approval_hash_and_path(self):
        first = self.api.upload_and_approve(
            self.project_id, "first.png", "first_frame", self.encoded((255, 0, 0)))
        style = self.api.upload_and_approve(
            self.project_id, "style.png", "style_reference", self.encoded((0, 255, 0)))
        self.api.clear_role_binding(self.project_id, "style_reference")
        bound = self.api.select_role_asset(
            self.project_id, "style_reference", style["reference"]["id"])
        self.assertEqual(bound["selected_reference_asset_ids"]["style_reference"],
                         style["reference"]["id"])
        self.assertNotIn("stored_path", json.dumps(bound))
        with self.assertRaisesRegex(ValueError, "REFERENCE_DUPLICATE_CONTENT"):
            self.api.upload_reference(
                self.project_id, "material.png", "material_reference",
                self.encoded((0, 255, 0)))
        refs = self.store.load_references(self.project_id)
        pending = self.api.upload_reference(
            self.project_id, "style2.png", "style_reference", self.encoded((0, 0, 255)))
        refs = self.store.load_references(self.project_id)
        refs[pending["id"]]["state"] = "PENDING"
        self.store.save_references(self.project_id, refs)
        with self.assertRaisesRegex(ValueError, "REFERENCE_NOT_APPROVED"):
            self.api.select_role_asset(self.project_id, "style_reference", pending["id"])
        self.assertEqual(first["reference"]["role"], "first_frame")

    def test_a6_role_requires_real_image_bytes_and_video_audio_ingest_stays_closed(self):
        with self.assertRaisesRegex(ValueError, "REFERENCE_IMAGE_REQUIRED"):
            self.api.upload_reference(self.project_id, "identity.png", "identity_reference")
        with self.assertRaisesRegex(ValueError, "REF2VA_MEDIA_INGEST_NOT_READY"):
                self.api.upload_reference(
                self.project_id, "motion.mp4", "motion_reference_video", "AAAA")

    def test_oversized_a6_base64_is_rejected_before_decoding(self):
        with patch("apps.architect_video_studio.mock_api.reference_api._UPLOAD_LIMIT_BYTES", 3), \
                patch("apps.architect_video_studio.mock_api.reference_api.base64.b64decode",
                      side_effect=AssertionError("oversized input must be rejected first")):
            with self.assertRaisesRegex(ValueError, "REFERENCE_IMAGE_TOO_LARGE"):
                self.api.upload_reference(
                    self.project_id, "identity.png", "identity_reference", "AAAAA")

    def test_reference_board_post_route_binds_only_requested_role(self):
        first = self.api.upload_and_approve(
            self.project_id, "first.png", "first_frame", self.encoded((255, 0, 0)))
        style = self.api.upload_and_approve(
            self.project_id, "style.png", "style_reference", self.encoded((0, 255, 0)))
        self.api.clear_role_binding(self.project_id, "style_reference")
        server = StudioServer(("127.0.0.1", 0), self.store,
                              {"reference": self.api})
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            body = json.dumps({"asset_id": style["reference"]["id"]}).encode("utf-8")
            request = Request(
                f"http://127.0.0.1:{server.server_address[1]}"
                f"/api/projects/{self.project_id}/reference-board/style_reference",
                data=body, headers={"Content-Type": "application/json"}, method="POST")
            with urlopen(request, timeout=3) as response:
                payload = json.loads(response.read().decode("utf-8"))
            self.assertTrue(payload["ok"])
            self.assertEqual(
                payload["data"]["selected_reference_asset_ids"]["style_reference"],
                style["reference"]["id"])
            self.assertEqual(payload["data"]["selected_reference_asset_ids"]["first_frame"],
                             first["reference"]["id"])
            self.assertEqual(self.store.load_jobs(self.project_id), {})
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)


class JobSnapshotTests(unittest.TestCase):
    def test_ref2va_snapshot_keeps_role_slot_and_source_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            api = JobAPI(StudioStore(directory))
            refs = [image_ref("first", "first_frame", "first"),
                    image_ref("site", "site_reference", "site")]
            request = SimpleNamespace(
                workflow_id="04_Drone_Aerial",
                prompt_payload={"mode": "Ref2VA", "prompt_hash": "prompt-hash"},
                guide_frames=[],
            )
            snapshot = api._build_workflow_snapshot(
                request, refs, {"1": {"class_type": "MiniMaxH3ReferenceToVideo",
                                     "inputs": {"ref_images.ref_image_0": ["2", 0]}}})
            self.assertEqual(snapshot["reference_mode"], "Ref2VA")
            site = next(item for item in snapshot["reference_bindings"]
                        if item["role"] == "site_reference")
            self.assertEqual(site["media_type"], "image")
            self.assertEqual(site["ordinal"], 2)
            self.assertEqual(site["native_input"], "ref_images.ref_image_1")
            self.assertTrue(site["source_identity"].startswith("sha256:"))
            for key in ("content_sha256", "requested_fidelity",
                        "runtime_compatibility", "validation_evidence"):
                self.assertIn(key, site)

    def test_ref2va_is_rejected_before_job_creation_without_checkpoint(self):
        with self.assertRaisesRegex(ValueError, "REF2VA_CHECKPOINT_UNAVAILABLE"):
            JobAPI._require_ref2va_runtime({"object_info": node_info(include_checkpoint=False)})
        JobAPI._require_ref2va_runtime({"object_info": node_info()})


class PromptIntegrationTests(unittest.TestCase):
    def test_prompt_api_compiles_selected_a6_roles_and_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            store = StudioStore(Path(directory) / "data")
            project = ProjectAPI(store).create_project("Ref2VA Prompt Contract")
            project_id = project["id"]
            refs = ReferenceAPI(store)
            refs.upload_and_approve(
                project_id, "first.png", "first_frame",
                base64.b64encode(tiny_png((255, 0, 0))).decode("ascii"))
            refs.upload_and_approve(
                project_id, "site.png", "site_reference",
                base64.b64encode(tiny_png((0, 255, 0))).decode("ascii"))
            IntentAPI(store).analyze_intent(
                project_id, "表现建筑与周边场地的空间关系")
            prompt = PromptAPI(store).generate_prompt(
                project_id, workflow="04_Drone_Aerial",
                generation_parameters={"quality": "NATIVE_HIGH", "duration": 4.0,
                                       "fps": 24, "seed": 42},
                prompt_engine="OFFLINE_COMPILER")
            self.assertEqual(prompt["mode"], "Ref2VA")
            self.assertTrue(prompt["verified"]["pass"], prompt["verified"])
            self.assertIn("<Picture 1>", prompt["prompt"])
            self.assertIn("<Picture 2>", prompt["prompt"])
            self.assertEqual([item["role"] for item in prompt["reference_bindings"]],
                             ["first_frame", "site_reference"])
            self.assertEqual(prompt["reference_bindings"][1]["native_input"],
                             "ref_images.ref_image_1")
            self.assertEqual(prompt["integrated_multimodal_description"],
                             prompt["integrated_multimodal_description"].strip())
            study = build_study_state(store, project_id)
            self.assertTrue(study["prompt_ready"], study["gate_reasons"])
            self.assertTrue(study["reference_approved"], study["reference_error"])
            self.assertTrue(study["generate_allowed"], study["gate_reasons"])
            self.assertEqual(
                [item["role"] for item in study["reference_bindings"]],
                ["first_frame", "site_reference"])

    def test_a6_experimental_dry_run_persists_ref2va_plan_without_submission(self):
        with tempfile.TemporaryDirectory() as directory:
            store = StudioStore(Path(directory) / "data")
            project = ProjectAPI(store).create_project("A6 dry-run contract")
            project_id = project["id"]
            refs = ReferenceAPI(store)
            refs.upload_and_approve(
                project_id, "first.png", "first_frame",
                base64.b64encode(tiny_png((255, 0, 0))).decode("ascii"))
            refs.upload_and_approve(
                project_id, "site.png", "site_reference",
                base64.b64encode(tiny_png((0, 255, 0))).decode("ascii"))
            IntentAPI(store).analyze_intent(
                project_id, "表现建筑与周边场地的空间关系")
            PromptAPI(store).generate_prompt(
                project_id, workflow="04_Drone_Aerial",
                generation_parameters={"quality": "NATIVE_HIGH", "duration": 4.0,
                                       "fps": 24, "seed": 42},
                prompt_engine="OFFLINE_COMPILER")

            class Runtime:
                name = "native"

                def __init__(self):
                    self.runtime_identity_spec = {
                        "runtime_id": "experimental-h3-8190",
                        "runtime_role": "experimental", "backend": "comfyui",
                        "endpoint_identity": "loopback:8190",
                        "comfyui_version": "0.36.0",
                        "comfyui_git_sha": "ee71d5c4993f29086b27fde1629a945ae48425bf",
                        "config_fingerprint": "a" * 64,
                        "output_root_fingerprint": "b" * 24,
                    }
                    self.client = SimpleNamespace(
                        base_url="http://127.0.0.1:8190",
                        output_root_fingerprint="b" * 24,
                        get_queue=lambda: {"queue_running": [], "queue_pending": []})
                    self.prompt_calls = 0

                def preflight(self):
                    return {"health": {"comfyui_version": "0.36.0"},
                            "object_info": node_info()}

                def prepare(self, request):
                    roles = [item["role"] for item in request.reference_assets]
                    bindings = [{
                        "asset_id": str(item["asset_id"]), "role": item["role"],
                        "native_input": f"ref_images.ref_image_{ordinal}",
                        "prompt_tag": f"<Picture {ordinal + 1}>",
                        "ordinal": ordinal + 1,
                    } for ordinal, item in enumerate(request.reference_assets)]
                    self.assert_roles = roles
                    return {
                        "translated_payload": {
                            "5": {"class_type": "MiniMaxH3ReferenceToVideo",
                                  "inputs": {"ref_images.ref_image_0": ["8", 0],
                                             "ref_images.ref_image_1": ["9", 0]}},
                            "15": {"class_type": "SaveVideo", "inputs": {
                                "filename_prefix": "video/04_Drone_Aerial_C2B_42",
                                "video": ["5", 0]}},
                        },
                        "ref2va_plan": {
                            "schema_version": 1,
                            "runtime_id": "experimental-h3-8190",
                            "backend": "comfyui",
                            "node": "MiniMaxH3ReferenceToVideo",
                            "limits": {"image": 9, "video": 3, "audio": 3},
                            "counts": {"image": len(bindings), "video": 0,
                                       "audio": 0},
                            "reference_image_size": "match",
                            "required_vaes": {"video": True, "audio": False},
                            "bindings": bindings,
                        },
                    }

                def attach_job_identity(self, prepared, job_id):
                    prepared["translated_payload"]["15"]["inputs"][
                        "filename_prefix"] += f"_{job_id}"
                    return prepared

            runtime = Runtime()
            jobs = JobAPI(store, experimental_runtime_adapter=runtime,
                          experimental_route_enabled=True, allow_mock_jobs=False)
            before = store.load_jobs(project_id)
            result = jobs.submit_job(
                project_id, seed=42, risk_reviewed=True,
                generation_parameters={"quality": "NATIVE_HIGH", "duration": 4.0,
                                       "fps": 24, "seed": 42},
                runtime_target="experimental", runtime_id="experimental-h3-8190",
                execution_purpose="A6_REF2VA_VALIDATION", dry_run=True)

            self.assertEqual(result["state"], "DRY_RUN")
            self.assertEqual(result["snapshot_type"],
                             "A6_REF2VA_EXPERIMENTAL_PREFLIGHT")
            self.assertEqual(result["execution_purpose"], "A6_REF2VA_VALIDATION")
            self.assertEqual(result["ref2va_count"], 2)
            self.assertEqual(result["runtime_capability"]["node"],
                             "MiniMaxH3ReferenceToVideo")
            self.assertEqual(result["runtime_capability"]["status"], "AVAILABLE")
            self.assertEqual(
                [item["native_input"] for item in
                 result["reference_execution_plan"]["bindings"]],
                ["ref_images.ref_image_0", "ref_images.ref_image_1"])
            self.assertIn(result["id"], result["expected_output_prefix"])
            self.assertFalse(result["submission_attempted"])
            self.assertIsNone(result["prompt_id"])
            self.assertEqual(runtime.prompt_calls, 0)
            self.assertEqual(store.load_jobs(project_id), before)
            record = json.loads((store.data_root / "preflights" /
                                 f"{result['id']}.json").read_text(encoding="utf-8"))
            self.assertEqual(record["snapshot_type"],
                             "A6_REF2VA_EXPERIMENTAL_PREFLIGHT")
            self.assertEqual(record["reference_execution_plan"],
                             result["reference_execution_plan"])
            self.assertEqual(record["guide_count"], 0)

    def test_missing_ref2va_checkpoint_fails_before_job_or_prompt_submission(self):
        with tempfile.TemporaryDirectory() as directory:
            store = StudioStore(Path(directory) / "data")
            project = ProjectAPI(store).create_project("Ref2VA Fail-Closed Study")
            project_id = project["id"]
            refs = ReferenceAPI(store)
            refs.upload_and_approve(
                project_id, "first.png", "first_frame",
                base64.b64encode(tiny_png((255, 0, 0))).decode("ascii"))
            refs.upload_and_approve(
                project_id, "style.png", "style_reference",
                base64.b64encode(tiny_png((0, 255, 0))).decode("ascii"))
            IntentAPI(store).analyze_intent(project_id, "展现建筑外观与环境关系")
            selected_intent = store.load_intent(project_id)
            selected_intent["selected_workflow"] = "04_Drone_Aerial"
            store.save_intent(project_id, selected_intent)
            PromptAPI(store).generate_prompt(
                project_id, workflow="04_Drone_Aerial",
                generation_parameters={"quality": "NATIVE_HIGH", "duration": 4.0,
                                       "fps": 24, "seed": 42},
                prompt_engine="OFFLINE_COMPILER")

            class Runtime:
                name = "native"

                def __init__(self):
                    self.prompt_calls = 0
                    self.runtime_identity_spec = {
                        "runtime_id": "experimental-h3-8190",
                        "runtime_role": "experimental", "backend": "comfyui",
                        "endpoint_identity": "loopback:8190",
                        "comfyui_version": "0.36.0",
                        "comfyui_git_sha": "ee71d5c4993f29086b27fde1629a945ae48425bf",
                        "config_fingerprint": "a" * 64,
                        "output_root_fingerprint": "b" * 64,
                    }
                    self.client = SimpleNamespace(
                        base_url="http://127.0.0.1:8190",
                        output_root_fingerprint="b" * 64,
                        submit_workflow=self.submit_workflow)

                def submit_workflow(self, *_args, **_kwargs):
                    self.prompt_calls += 1
                    raise AssertionError("A6 preflight must not submit /prompt")

                def preflight(self):
                    return {"health": {"comfyui_version": "0.36.0"},
                            "object_info": node_info(include_checkpoint=False)}

            runtime = Runtime()
            jobs = JobAPI(store, experimental_runtime_adapter=runtime,
                          experimental_route_enabled=True, allow_mock_jobs=False)
            with self.assertRaisesRegex(ValueError, "REF2VA_CHECKPOINT_UNAVAILABLE"):
                jobs.submit_job(
                    project_id, seed=42, risk_reviewed=True,
                    generation_parameters={"quality": "NATIVE_HIGH", "duration": 4.0,
                                           "fps": 24, "seed": 42},
                    runtime_target="experimental", runtime_id="experimental-h3-8190",
                    execution_purpose="A6_REF2VA_VALIDATION")
            self.assertEqual(store.load_jobs(project_id), {})
            self.assertEqual(runtime.prompt_calls, 0)


if __name__ == "__main__":
    unittest.main()
