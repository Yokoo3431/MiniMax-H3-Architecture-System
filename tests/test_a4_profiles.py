from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
import unittest
from pathlib import Path
import sys

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from runtime.a4_profiles import (
    ARCHITECTURE_PROFILES,
    PRESERVATION_SEMANTICS,
    QUALITY_PROFILE_SPECS,
    actual_execution_parameters,
    apply_architecture_profile,
    h3_frame_count_for_duration,
    normalize_quality_id,
    quality_profile_catalog,
    resolve_product_parameters,
    validate_native_canvas,
    workflow_quality_matrix,
)
from runtime.adapters.golden_workflow_binding import (
    GoldenWorkflowError,
    bind_golden_workflow,
    golden_entry,
)
from runtime.h3_prompt_engine import H3PromptValidator
from runtime.prompt_provenance import a4_profile_identity, prompt_input_hash
from runtime.reference_contract import REFERENCE_ROLES, validate_guide_frames
from runtime.h3_generation_parameters import (
    H3ParameterError, normalize_generation_parameters,
)
from runtime.a4_2_quality_acceptance import (
    A4_2AcceptanceError, A4_2AcceptanceRuntimeAdapter,
    _standard_arm_passed, compare_execution_payloads,
)


class TestA4Profiles(unittest.TestCase):
    def test_exact_seven_quality_profiles_and_legacy_aliases(self):
        expected = {"DRAFT", "PREVIEW", "BALANCED", "STANDARD",
                    "NATIVE_HIGH", "ULTRA_1080", "ULTRA_2K"}
        self.assertEqual(set(QUALITY_PROFILE_SPECS), expected)
        self.assertEqual(normalize_quality_id("PREVIEW"), "PREVIEW")
        self.assertEqual(normalize_quality_id("draft"), "DRAFT")
        self.assertEqual(normalize_quality_id("diagnostic"), "DRAFT")
        self.assertEqual(normalize_quality_id("production"), "STANDARD")
        catalog = quality_profile_catalog()
        self.assertEqual({p["id"] for p in catalog["profiles"]}, expected)
        self.assertEqual({p["id"] for p in catalog["profiles"]
                          if p["available"]}, {"PREVIEW", "NATIVE_HIGH"})
        for profile in catalog["profiles"]:
            self.assertEqual(profile["native_generation_fps"], 24)
            self.assertEqual(profile["delivery_fps_options"], [
                {"id": "NATIVE_24", "fps": 24, "availability": "READY"},
                {"id": "DELIVERY_30", "fps": 30,
                 "availability": "FUTURE_POSTPROCESS"},
                {"id": "SMOOTH_48", "fps": 48,
                 "availability": "FUTURE_POSTPROCESS"},
                {"id": "SMOOTH_60", "fps": 60,
                 "availability": "FUTURE_POSTPROCESS"},
            ])

    def test_available_profile_rows_bind_to_real_golden_parameters(self):
        matrix = workflow_quality_matrix()
        self.assertEqual(len(matrix), 35)
        available_rows = [row for row in matrix if row["availability"] == "READY"]
        self.assertEqual(len(available_rows), 10)
        for row in available_rows:
            workflow = row["workflow_id"]
            profile = row["quality_profile"]
            params, resolved = resolve_product_parameters(
                workflow,
                {"quality": profile, "duration": 6, "fps": 24,
                 "seed": 7123, "resolution": "832x480", "steps": 2,
                 "sampler_mode": "res_multistep", "velocity_cache": True},
            )
            self.assertEqual(params["quality"], profile)
            self.assertEqual(params["seed"], 7123)
            self.assertEqual(params["duration"], 6)
            roles = (("first_frame", "last_frame")
                     if workflow == "02_Day_Night_Transition" else ("first_frame",))
            refs = [{"path_or_ref": f"safe-reference-{index}.png", "role": role}
                    for index, role in enumerate(roles)]
            graph = bind_golden_workflow({
                "reference_assets": refs,
                "generation_parameters": params,
                "prompt_payload": {"prompt": "static A4 binder test prompt"},
            }, workflow)
            final = actual_execution_parameters(graph, workflow, resolved)
            self.assertEqual(final["resolution"], resolved["final_execution_parameters"]["resolution"])
            self.assertEqual(final["steps"], resolved["final_execution_parameters"]["steps"])
            self.assertEqual(final["sampler"], resolved["final_execution_parameters"]["sampler_mode"])
            self.assertEqual(final["seed"], 7123)
            self.assertEqual(final["frame_count"], 158)
            self.assertAlmostEqual(final["duration_seconds"], 158 / 24, places=6)
            self.assertEqual(final["requested_duration_seconds"], 6)
            self.assertFalse(any("execution_trace" in node for node in graph.values()))
            malformed_graph = deepcopy(graph)
            for node in malformed_graph.values():
                if node.get("class_type") == "MiniMaxH3ImageToVideo":
                    node["inputs"]["length"] = 11
                    break
            with self.assertRaisesRegex(ValueError, r"17k\+5 grid"):
                actual_execution_parameters(malformed_graph, workflow, resolved)
            if workflow == "01_Exterior_Hero" and profile == "NATIVE_HIGH":
                quantized_params, quantized_profile = resolve_product_parameters(
                    workflow,
                    {"quality": profile, "duration": 4.333, "fps": 24,
                     "seed": 7123},
                )
                quantized_graph = bind_golden_workflow({
                    "reference_assets": refs,
                    "generation_parameters": quantized_params,
                    "prompt_payload": {"prompt": "static A4 quantization test"},
                }, workflow)
                quantized_final = actual_execution_parameters(
                    quantized_graph, workflow, quantized_profile)
                self.assertAlmostEqual(
                    quantized_final["duration_seconds"], 107 / 24, places=6)

    def test_requested_duration_rounds_up_to_native_h3_frame_grid(self):
        expected = {4.0: 107, 4.333: 107, 4.4584: 124,
                    5.0: 124, 6.0: 158, 15.0: 362}
        for duration, frame_count in expected.items():
            with self.subTest(duration=duration):
                resolved = h3_frame_count_for_duration(duration)
                self.assertEqual(resolved, frame_count)
                self.assertEqual((resolved - 5) % 17, 0)
                self.assertGreaterEqual(resolved / 24, duration)
        self.assertEqual(h3_frame_count_for_duration(107 / 24), 107)
        self.assertEqual(h3_frame_count_for_duration((107 / 24) + 1e-12), 124)
        for invalid in (0.0, 3.9999, 15.0001, float("nan"), float("inf")):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                h3_frame_count_for_duration(invalid)
        for invalid in (3.9999, 15.0001):
            with self.subTest(profile_duration=invalid), self.assertRaisesRegex(
                    ValueError, "duration must be between 4 and 15"):
                resolve_product_parameters(
                    "01_Exterior_Hero", {"quality": "PREVIEW", "duration": invalid})
        with self.assertRaisesRegex(ValueError, "24 FPS"):
            h3_frame_count_for_duration(5.0, 24.5)
        with self.assertRaisesRegex(ValueError, "24 fps"):
            resolve_product_parameters("01_Exterior_Hero", {"fps": 24.5})

    def test_a4_2_standard_candidate_is_aligned_and_opt_in_only(self):
        self.assertEqual(validate_native_canvas(1248, 704), (1248, 704))
        self.assertEqual(validate_native_canvas(1344, 768), (1344, 768))
        for width, height in ((1280, 720), (1248.5, 704),
                              (Decimal("1248.5"), 704), (0, 704), (1248, -32)):
            with self.subTest(canvas=(width, height)), self.assertRaises(ValueError):
                validate_native_canvas(width, height)

        with self.assertRaisesRegex(H3ParameterError, "QUALITY_PROFILE_UNAVAILABLE:STANDARD"):
            normalize_generation_parameters({"quality": "STANDARD"})
        with self.assertRaisesRegex(ValueError, "QUALITY_PROFILE_UNAVAILABLE:STANDARD"):
            resolve_product_parameters("04_Drone_Aerial", {
                "quality": "STANDARD", "duration": 4, "seed": 42})

        standard, standard_profile = resolve_product_parameters(
            "04_Drone_Aerial", {
                "quality": "STANDARD", "duration": 4, "fps": 24,
                "delivery_fps": 24, "seed": 42,
            }, allow_a4_2_candidate=True)
        high, high_profile = resolve_product_parameters(
            "04_Drone_Aerial", {
                "quality": "NATIVE_HIGH", "duration": 4, "fps": 24,
                "delivery_fps": 24, "seed": 42,
            })
        self.assertEqual((standard["width"], standard["height"]), (1248, 704))
        self.assertEqual((high["width"], high["height"]), (1344, 768))
        self.assertEqual((standard["steps"], high["steps"]), (50, 50))
        self.assertEqual((standard["sampler_mode"], high["sampler_mode"]),
                         ("euler", "euler"))
        self.assertEqual((standard["frame_count"], high["frame_count"]), (107, 107))
        self.assertEqual(standard_profile["availability"], "CANDIDATE_FOR_A4_2")
        standard_catalog = next(
            p for p in quality_profile_catalog()["profiles"] if p["id"] == "STANDARD")
        self.assertIn("Owner review did not establish a meaningful quality/cost separation",
                      standard_catalog["availability_reason"])
        self.assertEqual(high_profile["availability"], "READY")
        self.assertFalse(next(p for p in quality_profile_catalog()["profiles"]
                              if p["id"] == "STANDARD")["available"])

        reference = [{
            "asset_id": "ref-a4-2", "project_id": "study-a4-2",
            "role": "first_frame", "approval_state": "APPROVED",
            "sha256": "B" * 64, "path_or_ref": "same-approved-reference.png",
        }]
        prompt_payload = {
            "prompt": "same architecture intent for both acceptance arms",
            "a4_profile": {"contract_version": "a4.1"},
        }
        with self.assertRaisesRegex(GoldenWorkflowError,
                                    "QUALITY_PROFILE_UNAVAILABLE:STANDARD"):
            bind_golden_workflow({
                "study_id": "study-a4-2", "reference_assets": reference,
                "generation_parameters": standard,
                "prompt_payload": prompt_payload,
            }, "04_Drone_Aerial")
        standard_graph = bind_golden_workflow({
            "study_id": "study-a4-2", "reference_assets": reference,
            "generation_parameters": standard,
            "prompt_payload": prompt_payload,
        }, "04_Drone_Aerial", allow_a4_2_candidate=True)
        high_graph = bind_golden_workflow({
            "study_id": "study-a4-2", "reference_assets": reference,
            "generation_parameters": high,
            "prompt_payload": prompt_payload,
        }, "04_Drone_Aerial")
        gate = compare_execution_payloads(standard_graph, high_graph)
        self.assertTrue(gate["pass"])
        self.assertEqual(gate["only_variable"],
                         "MiniMaxH3ImageToVideo.width,height")
        route_adapter = A4_2AcceptanceRuntimeAdapter(client=object())
        standard_route = route_adapter.attach_job_identity(
            {"translated_payload": deepcopy(standard_graph)}, "job-standard")
        high_route = route_adapter.attach_job_identity(
            {"translated_payload": deepcopy(high_graph)}, "job-native-high")
        prefixes = tuple(
            next(node for node in route["translated_payload"].values()
                 if node.get("class_type") == "SaveVideo")["inputs"]["filename_prefix"]
            for route in (standard_route, high_route)
        )
        self.assertNotEqual(prefixes[0], prefixes[1])
        isolated_gate = compare_execution_payloads(
            standard_route["translated_payload"], high_route["translated_payload"],
            operational_output_prefixes=prefixes)
        self.assertEqual(isolated_gate["per_job_output_isolation"],
                         "PASS_NON_GENERATION_METADATA_ONLY")
        changed = deepcopy(high_route["translated_payload"])
        changed["7"]["inputs"]["sampler_name"] = "res_multistep"
        with self.assertRaisesRegex(A4_2AcceptanceError,
                                    "differ beyond H3 width/height"):
            compare_execution_payloads(
                standard_route["translated_payload"], changed,
                operational_output_prefixes=prefixes)
        self.assertFalse(_standard_arm_passed({"state": "FAILED"}))
        self.assertFalse(_standard_arm_passed({
            "state": "COMPLETED", "acceptance_evidence": {"pass": False}}))
        self.assertTrue(_standard_arm_passed({
            "state": "COMPLETED", "acceptance_evidence": {"pass": True}}))

    def test_quality_selection_ignores_retired_internal_overrides(self):
        params, profile = resolve_product_parameters(
            "01_Exterior_Hero",
            {"quality": "preview", "resolution": "1344x768", "steps": 99,
             "sampler_mode": "euler", "velocity_cache": True, "seed": 81},
        )
        self.assertEqual(params["resolution"], "832x480")
        self.assertEqual(params["steps"], 21)
        self.assertEqual(params["sampler_mode"], "res_multistep")
        self.assertEqual(params["accel"], "off")
        self.assertEqual(params["seed"], 81)
        self.assertEqual(profile["profile_parameter_overrides"], {
            "resolution": {"from": "1344x768", "to": "832x480"},
            "width": {"from": 1344, "to": 832},
            "height": {"from": 768, "to": 480},
            "steps": {"from": 50, "to": 21},
            "sampler_mode": {"from": "euler", "to": "res_multistep"},
        })
        job_params, a4_profile = resolve_product_parameters(
            "01_Exterior_Hero", {"quality": "PREVIEW", "duration": 4.0})
        a4_request = {
            "study_id": "study-a4",
            "reference_assets": [{
                "asset_id": "ref-a4", "project_id": "study-a4",
                "role": "first_frame", "approval_state": "APPROVED",
                "sha256": "A" * 64, "path_or_ref": "reference.png",
            }],
            "generation_parameters": job_params,
            "prompt_payload": {
                "prompt": "static profile-locked binder test",
                "a4_profile": a4_profile,
            },
        }
        bound = bind_golden_workflow(a4_request, "01_Exterior_Hero")
        actual = actual_execution_parameters(bound, "01_Exterior_Hero", a4_profile)
        self.assertEqual((actual["resolution"], actual["steps"]), ("832x480", 21))
        altered = deepcopy(a4_request)
        altered["generation_parameters"]["steps"] = 50
        with self.assertRaisesRegex(GoldenWorkflowError, "steps differs from its selected profile"):
            bind_golden_workflow(altered, "01_Exterior_Hero")

    def test_each_architecture_profile_is_distinct_and_h3_valid(self):
        self.assertEqual(len(ARCHITECTURE_PROFILES), 5)
        self.assertEqual(len(PRESERVATION_SEMANTICS), 8)
        prefixes = {
            "02_Day_Night_Transition": (
                "How the reference pictures align with the target video — Picture 1 at 0.00 seconds; Picture 2 at 4.00 seconds.",
                "FL2VA", 2,
            )
        }
        for workflow in ARCHITECTURE_PROFILES:
            prefix, mode, refs = prefixes.get(workflow, (
                "For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.",
                "I2VA", 1,
            ))
            prompt = (f"{prefix}\n\n"
                      "integrated_multimodal_description: [Shot 1] Keep the architecture visible.\n\n"
                      "overall_soundscape: Quiet ambience.\n\nnon_diegetic_music: N/A")
            profiled = apply_architecture_profile(prompt, workflow)
            result = H3PromptValidator().validate(
                profiled, mode=mode, duration=4, reference_count=refs)
            self.assertTrue(result["pass"], result["errors"])
            self.assertNotEqual(profiled, prompt)
            self.assertEqual(apply_architecture_profile(profiled, workflow), profiled)

    def test_prompt_engine_accepts_maximum_frame_snapped_duration(self):
        from runtime.h3_prompt_engine import OfflineH3Compiler, PromptReasoningRequest

        result = OfflineH3Compiler().compile(PromptReasoningRequest(
            mode="I2VA", duration=362 / 24, reference_count=1,
            workflow_id="01_Exterior_Hero", camera_motion="slow_push",
            user_intent="show a slow architectural reveal",
        ))
        self.assertTrue(result["validator_result"]["pass"], result)
        rejected = H3PromptValidator().validate(
            result["prompt"], mode="I2VA", duration=(362 / 24) + 0.01,
            reference_count=1)
        self.assertFalse(rejected["pass"])

    def test_prompt_hash_binds_automatic_profile_identity(self):
        preview = {"quality": "PREVIEW", "duration": 4, "fps": 24, "seed": 42}
        high = {**preview, "quality": "NATIVE_HIGH"}
        identity = a4_profile_identity("04_Drone_Aerial", preview)
        self.assertEqual(identity["architecture_profile"], "drone_aerial")
        self.assertEqual(identity["architecture_profile_version"], "a4-architecture-v1")
        self.assertTrue(identity["prompt_profile_version"])
        self.assertNotEqual(
            prompt_input_hash("intent", "04_Drone_Aerial", "ref", preview),
            prompt_input_hash("intent", "04_Drone_Aerial", "ref", high),
        )
        candidate = {"quality": "STANDARD", "duration": 4, "fps": 24, "seed": 42}
        candidate_identity = a4_profile_identity(
            "04_Drone_Aerial", candidate, allow_a4_2_candidate=True)
        self.assertEqual(candidate_identity["quality_profile"], "STANDARD")
        self.assertEqual(a4_profile_identity(
            "04_Drone_Aerial", {**candidate, "seed": float("inf")},
            allow_a4_2_candidate=True), {})

    def test_unavailable_profiles_delivery_fps_and_future_guides_fail_closed(self):
        for profile in ("DRAFT", "BALANCED", "STANDARD", "ULTRA_1080", "ULTRA_2K"):
            with self.subTest(profile=profile), self.assertRaisesRegex(
                    ValueError, "QUALITY_PROFILE_UNAVAILABLE|QUALITY_EXECUTION_MODE_REQUIRED"):
                resolve_product_parameters("01_Exterior_Hero", {"quality": profile})
        with self.assertRaisesRegex(ValueError, "DELIVERY_FPS_UNAVAILABLE"):
            resolve_product_parameters(
                "01_Exterior_Hero", {"quality": "PREVIEW", "delivery_fps": 30})
        with self.assertRaisesRegex(ValueError, "QUALITY_EXECUTION_MODE_MISMATCH"):
            resolve_product_parameters("01_Exterior_Hero", {
                "quality": "PREVIEW", "quality_execution_mode": "POST_UPSCALE"})
        params, trace = resolve_product_parameters(
            "01_Exterior_Hero", {"quality": "PREVIEW", "fps": 24})
        self.assertEqual(params["fps"], 24)
        self.assertEqual(params["delivery_fps"], 24)
        self.assertEqual(trace["native_generation"]["fps"], 24)
        self.assertEqual(trace["delivery"]["fps"], 24)
        self.assertIsNone(trace["delivery"]["upscale_method"])
        self.assertIsNone(trace["delivery"]["interpolation_method"])
        self.assertFalse(trace["delivery"]["postprocess_applied"])
        self.assertEqual(len(REFERENCE_ROLES), 10)
        self.assertEqual(validate_guide_frames([{
            "asset_id": "asset-1", "role": "timeline_guide",
            "time_seconds": 0.5, "frame_index": 12, "approval_state": "APPROVED",
        }]), [{"asset_id": "asset-1", "role": "timeline_guide",
               "time_seconds": 0.5, "frame_index": 12,
               "approval_state": "APPROVED"}])
        with self.assertRaisesRegex(ValueError, r"guide_frames\[0\]"):
            validate_guide_frames([{"asset_id": "asset-1", "role": "timeline_guide"}])
        for invalid_guide in (
                {"asset_id": "asset-1", "role": "timeline_guide",
                 "time_seconds": float("nan"), "frame_index": 1},
                {"asset_id": "asset-1", "role": "timeline_guide",
                 "time_seconds": 1.0, "frame_index": 1.5}):
            with self.subTest(guide=invalid_guide), self.assertRaisesRegex(
                    ValueError, r"guide_frames\[0\]"):
                validate_guide_frames([invalid_guide])

    def test_studio_exposes_only_product_controls(self):
        root = Path(__file__).resolve().parent.parent
        html = (root / "apps/architect_video_studio/frontend/workspace.html").read_text(encoding="utf-8")
        js = (root / "apps/architect_video_studio/frontend/js/workspace.js").read_text(encoding="utf-8")
        for label in ("日夜过渡需要两张不同的图片", "选择首帧", "选择末帧",
                      "上传并审批首帧", "上传并审批末帧", "交付帧率",
                      "Architecture Fidelity", "STANDARD · 720p-class · 保持候选",
                      "原生画布 1248×704"):
            self.assertIn(label, html)
        for retired_id in ("param-resolution", "param-sampler", "param-steps",
                           "param-velocity", "param-cache-dit", "param-speed"):
            self.assertNotIn(retired_id, html)
            self.assertNotIn(retired_id, js)
        self.assertIn("/api/capabilities", js)
        self.assertIn("renderDayNightRefs", js)
        self.assertIn("const pendingRoleUrls = {first_frame: null, last_frame: null};", js)


if __name__ == "__main__":
    unittest.main()
