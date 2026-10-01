from __future__ import annotations

import base64
import hashlib
import json
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.architect_video_studio.mock_api.guide_frame_api import GuideFrameAPI
from apps.architect_video_studio.mock_api.job_api import JobAPI
from apps.architect_video_studio.mock_api.project_api import ProjectAPI
from apps.architect_video_studio.mock_api.reference_api import ReferenceAPI
from apps.architect_video_studio.mock_api.server import _experimental_io_isolated
from apps.architect_video_studio.mock_api.store import StudioStore
from runtime.a4_profiles import h3_frame_count_for_duration
from runtime.adapters.golden_workflow_binding import bind_golden_workflow
from runtime.adapters.multiframe_guide_capability import capability_from_object_info
from runtime.adapters.production_workflow_binding import validate_production_payload
from runtime.multiframe_guides import (
    GuideFrameError, canonical_execution_sha256, compile_native_guides,
    compile_timeline_guide_prompt, guide_comfy_filename,
    resolve_guide_bindings, resolve_guide_time,
)


ADD_GUIDE_INFO = {
    "input": {
        "required": {"positive": ["CONDITIONING"], "latent": ["LATENT"],
                     "frame_idx": ["INT"]},
        "optional": {"vae": ["VAE"], "image": ["IMAGE"],
                     "audio_vae": ["VAE"], "audio": ["AUDIO"]},
    },
}


class MultiFrameGuideTests(unittest.TestCase):
    def test_live_comfy_dropdown_values_fail_closed_before_submission(self):
        payload = {
            "5": {"class_type": "VAELoader",
                  "inputs": {"vae_name": "missing-audio-vae.safetensors"}},
            "1": {"class_type": "LoadImage", "inputs": {"image": "staged-guide.png"}},
            "6": {"class_type": "BasicGuider",
                  "inputs": {"conditioning": ["5", 0]}},
        }
        object_info = {
            "VAELoader": {"input": {"required": {
                "vae_name": [["registered-video-vae.safetensors"], {}]}}},
            "LoadImage": {"input": {"required": {
                "image": [["another-image.png"], {}]}}},
            "BasicGuider": {"input": {"required": {
                "conditioning": ["CONDITIONING"]}}},
        }

        result = validate_production_payload(payload, object_info)
        self.assertFalse(result["ready"])
        self.assertEqual(result["live_input_enum_mismatches"], [{
            "node_id": "1", "node_type": "LoadImage", "input_name": "image",
        }, {
            "node_id": "5", "node_type": "VAELoader", "input_name": "vae_name",
        }])
        preflight = validate_production_payload(
            payload, object_info, allow_dynamic_asset_inputs=True)
        self.assertEqual(preflight["live_input_enum_mismatches"], [{
            "node_id": "5", "node_type": "VAELoader", "input_name": "vae_name",
        }])

        payload["5"]["inputs"]["vae_name"] = "registered-video-vae.safetensors"
        self.assertTrue(validate_production_payload(
            payload, object_info, allow_dynamic_asset_inputs=True)["ready"])

    def _approved_record(self, root: Path, *, asset_id="ref-guide-1", project_id="p",
                         filename="guide.png", content=b"guide-image"):
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"{asset_id}.png"
        path.write_bytes(content)
        return {
            "id": asset_id, "project_id": project_id, "role": "timeline_guide",
            "state": "APPROVED", "stored_path": str(path), "filename": filename,
            "sha256": hashlib.sha256(content).hexdigest().upper(), "version": 1,
            "approved_at": "2026-09-24T00:00:00Z",
        }

    def _resolved(self, root: Path, rows=None, references=None):
        record = self._approved_record(root)
        source = references or {record["id"]: record}
        return resolve_guide_bindings(
            "p", rows or [{"guide_id": "g1", "asset_id": record["id"],
                           "role": "timeline_guide", "requested_time_seconds": 1.5,
                           "ordinal": 1}], source, target_frame_count=107,
            fps=24, workflow_id="04_Drone_Aerial", reference_root=root)

    @staticmethod
    def _base_graph():
        return bind_golden_workflow({
            "study_id": "p",
            "reference_assets": [{"asset_id": "endpoint", "project_id": "p",
                                  "role": "first_frame", "approval_state": "APPROVED",
                                  "path_or_ref": "endpoint.png", "sha256": "a" * 64}],
            "generation_parameters": {"resolution": "1344x768", "fps": 24,
                                       "duration": 4, "quality": "NATIVE_HIGH", "seed": 42},
            "prompt_payload": {"prompt": "A neutral architectural study."},
        }, "04_Drone_Aerial")

    def test_decimal_half_up_uses_actual_target_frame_count(self):
        self.assertEqual(h3_frame_count_for_duration(4, 24), 107)
        self.assertEqual(resolve_guide_time(0.5 / 24, fps=24, target_frame_count=107), 1)
        self.assertEqual(resolve_guide_time(1.5 / 24, fps=24, target_frame_count=107), 2)
        with self.assertRaisesRegex(GuideFrameError, "FIRST_FRAME_COLLISION"):
            resolve_guide_time(0, fps=24, target_frame_count=107)
        with self.assertRaisesRegex(GuideFrameError, "LAST_FRAME_COLLISION"):
            resolve_guide_time(106 / 24, fps=24, target_frame_count=107)
        with self.assertRaisesRegex(GuideFrameError, "OUT_OF_RANGE"):
            resolve_guide_time(107 / 24, fps=24, target_frame_count=107)
        with self.assertRaisesRegex(GuideFrameError, "TIME_INVALID"):
            resolve_guide_time(-0.1, fps=24, target_frame_count=107)

    def test_timeline_prompt_compilation_is_deterministic_idempotent_and_explicit(self):
        source = (
            "For the target video, <Picture 1> is fully referenced.\n\n"
            "integrated_multimodal_description: A coastal architecture study.\n\n"
            "overall_soundscape: Quiet wind.\n\nnon_diegetic_music: N/A")
        guides = [
            {"ordinal": 1, "resolved_frame_idx": 36},
            {"ordinal": 2, "resolved_frame_idx": 72},
        ]
        compiled = compile_timeline_guide_prompt(source, guides, fps=24)
        self.assertEqual(compiled["guide_frame_indexes"], [36, 72])
        self.assertIn("Intended cut to timeline guide 1 at 1.500 seconds (frame 36).",
                      compiled["prompt"])
        self.assertIn("Intended cut to timeline guide 2 at 3.000 seconds (frame 72).",
                      compiled["prompt"])
        self.assertIn("does not guarantee exact cuts", compiled["prompt"])
        self.assertIn("preserve the same building identity", compiled["prompt"])
        self.assertEqual(compiled["source_prompt_sha256"],
                         hashlib.sha256(source.encode("utf-8")).hexdigest())
        self.assertEqual(compiled["execution_prompt_sha256"],
                         hashlib.sha256(compiled["prompt"].encode("utf-8")).hexdigest())
        self.assertEqual(compile_timeline_guide_prompt(
            compiled["prompt"], guides, fps=24)["prompt"], compiled["prompt"])
        self.assertEqual(compile_timeline_guide_prompt(source, [], fps=24)["prompt"],
                         source)
        self.assertEqual(compile_timeline_guide_prompt(source, [], fps=24)[
            "execution_prompt_sha256"], hashlib.sha256(source.encode("utf-8")).hexdigest())
        authored_marker = source.replace(
            "A coastal architecture study.",
            "A coastal architecture study. Storyboard guide timing (A5.2): is a literal label.")
        preserved = compile_timeline_guide_prompt(authored_marker, guides, fps=24)
        self.assertIn("Storyboard guide timing (A5.2): is a literal label.",
                      preserved["prompt"])

    def test_timeline_prompt_compilation_rejects_bad_order_schema_and_size(self):
        source = (
            "integrated_multimodal_description: Short description.\n\n"
            "overall_soundscape: Quiet.\n\nnon_diegetic_music: N/A")
        with self.assertRaisesRegex(GuideFrameError, "GUIDE_PROMPT_FRAME_ORDER_INVALID"):
            compile_timeline_guide_prompt(source, [
                {"ordinal": 1, "resolved_frame_idx": 72},
                {"ordinal": 2, "resolved_frame_idx": 36},
            ])
        with self.assertRaisesRegex(GuideFrameError, "GUIDE_PROMPT_DESCRIPTION_SECTION_MISSING"):
            compile_timeline_guide_prompt("A plain unstructured prompt.", [
                {"ordinal": 1, "resolved_frame_idx": 36},
            ])
        with self.assertRaisesRegex(GuideFrameError, "GUIDE_PROMPT_EXCEEDS_LIMIT"):
            compile_timeline_guide_prompt(
                source.replace("Short description.", "x" * 7000), [
                    {"ordinal": 1, "resolved_frame_idx": 36},
                ])

    def test_job_request_binds_compiled_prompt_but_preserves_source_hash(self):
        source = (
            "For the target video, <Picture 1> is fully referenced.\n\n"
            "integrated_multimodal_description: Preserve the coastal building.\n\n"
            "overall_soundscape: Quiet.\n\nnon_diegetic_music: N/A")
        guides = [
            {"ordinal": 1, "resolved_frame_idx": 36},
            {"ordinal": 2, "resolved_frame_idx": 72},
        ]
        compiled = compile_timeline_guide_prompt(source, guides)
        api = JobAPI.__new__(JobAPI)
        api.store = SimpleNamespace(load_intent=lambda _project_id: {})
        prompt = {
            "workflow": "04_Drone_Aerial", "mode": "I2VA", "prompt": source,
            "alignment": "", "integrated_multimodal_description": "Preserve the coastal building.",
            "overall_soundscape": "Quiet.", "prompt_hash": "owner-source-hash",
            "a4_profile": {}, "reference_bindings": [],
        }
        params = {
            "width": 1344, "height": 768, "fps": 24, "duration": 4.0,
            "resolved_duration_seconds": 4.4583333333, "frame_count": 107,
            "resolution": "1344x768", "steps": 50, "sampler_mode": "euler",
            "scheduler": "simple", "denoise": 1.0, "seed": 42,
            "generation_speed": "standard", "acceleration": "off",
            "delivery_fps": 24,
        }
        approved = [{
            "id": "endpoint-ref", "role": "first_frame", "media_type": "image",
            "state": "APPROVED", "stored_path": "endpoint.png",
            "filename": "endpoint.png", "sha256": "a" * 64,
        }]
        request = api._build_request("synthetic-study", {}, prompt, approved,
                                     params, None, guides, guide_prompt=compiled)
        self.assertEqual(request.prompt_payload["prompt"], compiled["prompt"])
        self.assertEqual(request.prompt_payload["prompt_hash"], "owner-source-hash")
        self.assertEqual(request.prompt_payload["guide_prompt_compilation"][
            "execution_prompt_sha256"], compiled["execution_prompt_sha256"])
        with self.assertRaisesRegex(ValueError, "GUIDE_PROMPT_SOURCE_HASH_MISMATCH"):
            api._build_request("synthetic-study", {}, prompt, approved,
                params, None, guides,
                guide_prompt={**compiled, "source_prompt_sha256": "0" * 64})
        with self.assertRaisesRegex(ValueError, "GUIDE_PROMPT_HASH_MISMATCH"):
            api._build_request("synthetic-study", {}, prompt, approved,
                params, None, guides,
                guide_prompt={**compiled, "execution_prompt_sha256": "0" * 64})
        bound = bind_golden_workflow(request.to_dict(), "04_Drone_Aerial")
        h3 = next(node for node in bound.values()
                  if node["class_type"] == "MiniMaxH3ImageToVideo")
        self.assertEqual(h3["inputs"]["prompt"], compiled["prompt"])

    def test_project_approval_and_upload_use_existing_reference_store(self):
        with tempfile.TemporaryDirectory() as directory:
            store = StudioStore(directory)
            project = ProjectAPI(store).create_project("Guide Contract Study")
            project_id = project["id"]
            ref_api = ReferenceAPI(store)
            result = ref_api.upload_and_approve(
                project_id, "guide.png", role="timeline_guide",
                data_base64=base64.b64encode(b"single approved guide image").decode())
            self.assertEqual(result["reference"]["state"], "APPROVED")
            self.assertEqual(result["project"]["state"], "CREATED")
            self.assertFalse(result["selected_reference_asset_ids"])
            guide_api = GuideFrameAPI(store)
            added = guide_api.add(project_id, result["reference"]["id"], 1.5)
            self.assertEqual(len(added["guide_frames"]), 1)
            self.assertEqual(added["guide_frames"][0]["role"], "timeline_guide")
            self.assertNotIn("stored_path", json.dumps(added))
            resolved = guide_api.resolve(project_id, duration_seconds=4,
                                         workflow_id="04_Drone_Aerial")
            self.assertTrue(resolved["valid"])
            self.assertEqual(resolved["target_frame_count"], 107)
            self.assertEqual(resolved["guides"][0]["resolved_frame_idx"], 36)

            second = ref_api.upload_and_approve(
                project_id, "guide-2.png", role="timeline_guide",
                data_base64=base64.b64encode(b"second approved guide image").decode())
            third = ref_api.upload_and_approve(
                project_id, "guide-3.png", role="timeline_guide",
                data_base64=base64.b64encode(b"third approved guide image").decode())
            guide_api.add(project_id, second["reference"]["id"], 2.5)
            guide_api.add(project_id, third["reference"]["id"], 3.0)
            guide_api.remove(project_id, added["guide_frames"][0]["guide_id"])

            remaining = guide_api.list(project_id)["guide_frames"]
            self.assertEqual([item["ordinal"] for item in remaining], [1, 2])
            resolved = guide_api.resolve(project_id, duration_seconds=4,
                                         workflow_id="04_Drone_Aerial")
            self.assertTrue(resolved["valid"], resolved.get("reason"))
            self.assertEqual([item["resolved_frame_idx"] for item in resolved["guides"]],
                             [60, 72])

    def test_cross_project_unapproved_stale_and_hash_mismatch_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            approved = self._approved_record(root)
            with self.assertRaisesRegex(GuideFrameError, "CROSS_PROJECT"):
                resolve_guide_bindings("other", [{"asset_id": approved["id"],
                    "role": "timeline_guide", "ordinal": 1,
                    "requested_time_seconds": 1.5}], {approved["id"]: approved},
                    target_frame_count=107, reference_root=root)
            pending = dict(approved, state="PENDING")
            with self.assertRaisesRegex(GuideFrameError, "NOT_APPROVED"):
                resolve_guide_bindings("p", [{"asset_id": approved["id"],
                    "role": "timeline_guide", "ordinal": 1,
                    "requested_time_seconds": 1.5}], {approved["id"]: pending},
                    target_frame_count=107, reference_root=root)
            with self.assertRaisesRegex(GuideFrameError, "SHA_MISMATCH"):
                resolve_guide_bindings("p", [{"asset_id": approved["id"],
                    "role": "timeline_guide", "ordinal": 1,
                    "requested_time_seconds": 1.5, "content_sha256": "0" * 64}],
                    {approved["id"]: approved}, target_frame_count=107,
                    reference_root=root)
            Path(approved["stored_path"]).write_bytes(b"changed")
            with self.assertRaisesRegex(GuideFrameError, "STALE_CONTENT"):
                resolve_guide_bindings("p", [{"asset_id": approved["id"],
                    "role": "timeline_guide", "ordinal": 1,
                    "requested_time_seconds": 1.5}], {approved["id"]: approved},
                    target_frame_count=107, reference_root=root)

    def test_frame_collisions_and_chronology_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = self._approved_record(root, asset_id="ref-1", filename="one.png")
            second = self._approved_record(root, asset_id="ref-2", filename="two.png",
                                           content=b"second guide")
            refs = {first["id"]: first, second["id"]: second}
            with self.assertRaisesRegex(GuideFrameError, "FRAME_COLLISION"):
                resolve_guide_bindings("p", [
                    {"asset_id": "ref-1", "role": "timeline_guide",
                     "requested_time_seconds": 1.0, "ordinal": 1},
                    {"asset_id": "ref-2", "role": "timeline_guide",
                     "requested_time_seconds": 1.01, "ordinal": 2},
                ], refs, target_frame_count=107, reference_root=root)
            with self.assertRaisesRegex(GuideFrameError, "ORDER_INVALID"):
                resolve_guide_bindings("p", [
                    {"asset_id": "ref-2", "role": "timeline_guide",
                     "requested_time_seconds": 2.0, "ordinal": 1},
                    {"asset_id": "ref-1", "role": "timeline_guide",
                     "requested_time_seconds": 1.0, "ordinal": 2},
                ], refs, target_frame_count=107, reference_root=root)

    def test_compiler_is_additive_deterministic_and_hashes_guide_identity(self):
        base = self._base_graph()
        original = json.loads(json.dumps(base))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            guides = self._resolved(root)
            compiled = compile_native_guides(base, guides,
                object_info={"MiniMaxH3AddGuide": ADD_GUIDE_INFO},
                target_frame_count=107)
            self.assertEqual(base, original)
            self.assertEqual(sum(node["class_type"] == "MiniMaxH3AddGuide"
                                 for node in compiled.values()), 1)
            add_node = next(node for node in compiled.values()
                            if node["class_type"] == "MiniMaxH3AddGuide")
            self.assertEqual(add_node["inputs"]["frame_idx"], 36)
            add_node_id = next(key for key, node in compiled.items()
                               if node["class_type"] == "MiniMaxH3AddGuide")
            self.assertEqual(compiled["10"]["inputs"]["conditioning"],
                             [add_node_id, 0])
            again = compile_native_guides(base, guides,
                object_info={"MiniMaxH3AddGuide": ADD_GUIDE_INFO},
                target_frame_count=107)
            self.assertEqual(canonical_execution_sha256(compiled),
                             canonical_execution_sha256(again))
            changed = dict(guides[0], asset_id="another-asset")
            changed["comfy_filename"] = guide_comfy_filename(changed)
            changed["source_identity"] = (
                f"reference:another-asset:v1:sha256:{changed['content_sha256']}")
            changed_graph = compile_native_guides(base, [changed],
                object_info={"MiniMaxH3AddGuide": ADD_GUIDE_INFO},
                target_frame_count=107)
            self.assertNotEqual(canonical_execution_sha256(compiled),
                                canonical_execution_sha256(changed_graph))
            self.assertEqual(compile_native_guides(base, [], object_info={},
                target_frame_count=107), base)

    def test_compiler_builds_three_guide_chain_and_rejects_missing_capability(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            refs = {}
            rows = []
            for index, second in enumerate((1.0, 2.0, 3.0), start=1):
                record = self._approved_record(root, asset_id=f"ref-{index}",
                    filename=f"guide-{index}.png", content=f"image-{index}".encode())
                refs[record["id"]] = record
                rows.append({"guide_id": f"g{index}", "asset_id": record["id"],
                             "role": "timeline_guide", "requested_time_seconds": second,
                             "ordinal": index})
            guides = resolve_guide_bindings("p", rows, refs, target_frame_count=107,
                workflow_id="04_Drone_Aerial", reference_root=root)
            compiled = compile_native_guides(self._base_graph(), guides,
                object_info={"MiniMaxH3AddGuide": ADD_GUIDE_INFO},
                target_frame_count=107)
            nodes = [(int(key), node) for key, node in compiled.items()
                     if node["class_type"] == "MiniMaxH3AddGuide"]
            nodes.sort()
            self.assertEqual([node["inputs"]["frame_idx"] for _, node in nodes],
                             [24, 48, 72])
            self.assertEqual(nodes[1][1]["inputs"]["positive"], [str(nodes[0][0]), 0])
            self.assertEqual(nodes[2][1]["inputs"]["positive"], [str(nodes[1][0]), 0])
            self.assertEqual(compiled["10"]["inputs"]["conditioning"],
                             [str(nodes[-1][0]), 0])
            with self.assertRaisesRegex(GuideFrameError, "RUNTIME_UNAVAILABLE"):
                compile_native_guides(self._base_graph(), guides, object_info={},
                                      target_frame_count=107)

    def test_runtime_capability_matrix_is_live_schema_based_and_explicit(self):
        production = capability_from_object_info({}, runtime_name="production",
                                                 version="0.33.1", port=8189)
        experimental = capability_from_object_info(
            {"MiniMaxH3AddGuide": ADD_GUIDE_INFO}, runtime_name="experimental",
            version="0.36.0", port=8190)
        self.assertEqual(production["status"], "UNAVAILABLE")
        self.assertEqual(experimental["status"], "AVAILABLE")
        self.assertEqual(experimental["routing"], "EXPLICIT_ONLY")

        class RuntimeProbe:
            def __init__(self, version="0.36.0", node=ADD_GUIDE_INFO, offline=False):
                self.version = version
                self.node = node
                self.offline = offline

            def health_check(self):
                if self.offline:
                    raise ConnectionError("synthetic offline runtime")
                return {"system": {"comfyui_version": self.version}}

            def object_info(self):
                return ({"MiniMaxH3AddGuide": self.node} if self.node else {})

        static_identity = {
            "runtime_id": "experimental-h3-8190", "runtime_role": "experimental",
            "comfyui_version": "0.36.0", "comfyui_git_sha": "e" * 40,
            "available": True, "status": "AVAILABLE", "health": "NOT_CHECKED",
            "capabilities": ["MiniMaxH3AddGuide"], "route_enabled": True,
        }
        live_api = GuideFrameAPI(
            None, experimental_client=RuntimeProbe(), experimental_enabled=True,
            experimental_identity=static_identity)
        live = live_api.capabilities()["experimental"]
        self.assertTrue(live["available"])
        self.assertEqual(live["health"], "PASS")
        self.assertEqual(live["observed_version"], "0.36.0")

        offline_api = GuideFrameAPI(
            None, experimental_client=RuntimeProbe(offline=True),
            experimental_enabled=True, experimental_identity=static_identity)
        offline = offline_api.capabilities()["experimental"]
        self.assertFalse(offline["available"])
        self.assertEqual(offline["status"], "UNAVAILABLE")
        self.assertEqual(offline["health"], "UNAVAILABLE")
        self.assertEqual(offline["capabilities"], [])

        wrong_version_api = GuideFrameAPI(
            None, experimental_client=RuntimeProbe(version="0.35.0"),
            experimental_enabled=True, experimental_identity=static_identity)
        wrong_version = wrong_version_api.capabilities()["experimental"]
        self.assertFalse(wrong_version["available"])
        self.assertEqual(wrong_version["status"], "UNAVAILABLE")
        self.assertEqual(wrong_version["reason"],
                         "EXPERIMENTAL_RUNTIME_VERSION_MISMATCH")
        self.assertEqual(wrong_version["observed_version"], "0.35.0")

        missing_node_api = GuideFrameAPI(
            None, experimental_client=RuntimeProbe(node=None),
            experimental_enabled=True, experimental_identity=static_identity)
        missing_node = missing_node_api.capabilities()["experimental"]
        self.assertFalse(missing_node["available"])
        self.assertEqual(missing_node["status"], "UNAVAILABLE")

    def test_experimental_job_route_is_real_loopback_8190_only(self):
        with self.assertRaisesRegex(ValueError, "EXPERIMENTAL_RUNTIME_UNAVAILABLE"):
            JobAPI._validate_experimental_endpoint(None)
        for url in ("http://127.0.0.1:8190", "http://localhost:8190/"):
            adapter = SimpleNamespace(client=SimpleNamespace(base_url=url))
            JobAPI._validate_experimental_endpoint(adapter)
        for url in ("http://127.0.0.1:8189", "http://192.168.1.5:8190",
                    "https://localhost:8190", "http://localhost.evil.example:8190",
                    "http://localhost:abc"):
            adapter = SimpleNamespace(client=SimpleNamespace(base_url=url))
            with self.subTest(url=url), self.assertRaisesRegex(
                    ValueError, "EXPERIMENTAL_RUNTIME_IDENTITY_MISMATCH"):
                JobAPI._validate_experimental_endpoint(adapter)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prod_input = root / "production" / "input"
            prod_output = root / "production" / "output"
            exp_input = root / "experimental" / "input"
            exp_output = root / "experimental" / "output"
            self.assertTrue(_experimental_io_isolated(
                exp_input, exp_output, prod_input, prod_output))
            self.assertFalse(_experimental_io_isolated(
                prod_input, exp_output, prod_input, prod_output))
            self.assertFalse(_experimental_io_isolated(
                root / "production", exp_output, prod_input, prod_output))
            self.assertFalse(_experimental_io_isolated(
                exp_input, exp_output, None, prod_output))

    def test_compiler_rejects_missing_approval_or_source_provenance(self):
        base = self._base_graph()
        with tempfile.TemporaryDirectory() as directory:
            guides = self._resolved(Path(directory))
            for key, error in (("approval_evidence", "APPROVAL_EVIDENCE_INVALID"),
                               ("source_identity", "SOURCE_IDENTITY_INVALID")):
                broken = [dict(guides[0])]
                broken[0][key] = None
                with self.subTest(key=key), self.assertRaisesRegex(GuideFrameError, error):
                    compile_native_guides(base, broken,
                        object_info={"MiniMaxH3AddGuide": ADD_GUIDE_INFO},
                        target_frame_count=107)

    def test_excessive_timestamp_rejected_before_frame_math(self):
        with self.assertRaisesRegex(GuideFrameError, "TIME_INVALID"):
            resolve_guide_time("1e100000", fps=24, target_frame_count=107)

    def test_reorder_swaps_asset_identity_between_chronological_slots(self):
        with tempfile.TemporaryDirectory() as directory:
            store = StudioStore(directory)
            project = ProjectAPI(store).create_project("Guide Reorder Study")
            project_id = project["id"]
            api = ReferenceAPI(store)
            guide_ids = []
            for index, time_seconds in enumerate((1.5, 3.0), start=1):
                result = api.upload_and_approve(
                    project_id, f"guide-{index}.png", role="timeline_guide",
                    data_base64=base64.b64encode(f"guide-{index}".encode()).decode())
                guide = GuideFrameAPI(store).add(
                    project_id, result["reference"]["id"], time_seconds)
                guide_ids.append(guide["guide_frames"][-1]["guide_id"])
            reordered = GuideFrameAPI(store).reorder(project_id, guide_ids[::-1])
            self.assertEqual([row["guide_id"] for row in reordered["guide_frames"]],
                             guide_ids[::-1])
            self.assertEqual([row["requested_time_seconds"]
                              for row in reordered["guide_frames"]], [1.5, 3.0])

    def test_update_replaces_guide_asset_atomically_and_rejects_duplicate(self):
        with tempfile.TemporaryDirectory() as directory:
            store = StudioStore(directory)
            project = ProjectAPI(store).create_project("Guide Replace Study")
            project_id = project["id"]
            refs = ReferenceAPI(store)
            assets = []
            for index in range(1, 4):
                result = refs.upload_and_approve(
                    project_id, f"guide-{index}.png", role="timeline_guide",
                    data_base64=base64.b64encode(f"guide-{index}".encode()).decode())
                assets.append(result["reference"])
            api = GuideFrameAPI(store)
            first = api.add(project_id, assets[0]["id"], 1.5)["guide_frames"][0]
            second = api.add(project_id, assets[1]["id"], 3.0)["guide_frames"][1]

            replaced = api.update(project_id, first["guide_id"], asset_id=assets[2]["id"])
            self.assertEqual(replaced["guide_frames"][0]["guide_id"], first["guide_id"])
            self.assertEqual(replaced["guide_frames"][0]["asset_id"], assets[2]["id"])
            self.assertEqual(replaced["guide_frames"][0]["requested_time_seconds"], 1.5)
            self.assertEqual(replaced["guide_frames"][0]["filename"], "guide-3.png")
            self.assertEqual(replaced["guide_frames"][1]["guide_id"], second["guide_id"])

            with self.assertRaisesRegex(GuideFrameError, "GUIDE_DUPLICATE_ASSET"):
                api.update(project_id, first["guide_id"], asset_id=assets[1]["id"])

            with self.assertRaisesRegex(GuideFrameError, "GUIDE_UPDATE_EMPTY"):
                api.update(project_id, first["guide_id"])

    def test_update_replacement_rejects_unapproved_or_cross_project_asset(self):
        with tempfile.TemporaryDirectory() as directory:
            store = StudioStore(directory)
            project = ProjectAPI(store).create_project("Guide Replace Study")
            other = ProjectAPI(store).create_project("Other Study")
            project_id = project["id"]
            other_id = other["id"]
            refs = ReferenceAPI(store)
            first = refs.upload_and_approve(
                project_id, "guide.png", role="timeline_guide",
                data_base64=base64.b64encode(b"guide").decode())["reference"]
            other_guide = refs.upload_and_approve(
                other_id, "other-guide.png", role="timeline_guide",
                data_base64=base64.b64encode(b"other guide").decode())["reference"]
            api = GuideFrameAPI(store)
            guide = api.add(project_id, first["id"], 1.5)["guide_frames"][0]
            with self.assertRaisesRegex(GuideFrameError, "GUIDE_CROSS_PROJECT"):
                api.update(project_id, guide["guide_id"], asset_id=other_guide["id"])

            unapproved = dict(first, id="ref-unapproved", state="PENDING")
            project_references = store.load_references(project_id)
            project_references[unapproved["id"]] = unapproved
            store.save_references(project_id, project_references)
            with self.assertRaisesRegex(GuideFrameError, "GUIDE_NOT_APPROVED"):
                api.update(project_id, guide["guide_id"], asset_id=unapproved["id"])


if __name__ == "__main__":
    unittest.main()
