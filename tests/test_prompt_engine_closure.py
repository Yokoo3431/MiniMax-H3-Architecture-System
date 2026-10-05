"""Regression tests for the real Prompt Engine closure path."""

from __future__ import annotations

import json
import hashlib
import sys
import unittest
from unittest import mock

from runtime.a4_profiles import apply_architecture_profile
from runtime.adapters.golden_workflow_binding import (
    bind_golden_workflow,
    canonical_payload_sha256,
    load_golden_registry,
)
from runtime.h3_prompt_engine import (
    CLIReasoningProvider,
    OfflineH3Compiler,
    PromptReasoningRequest,
    UniversalPromptEngine,
)
from runtime.prompt_provenance import is_current_prompt, prompt_input_hash
from runtime.reference_contract import required_reference_roles


GOLDEN_PROMPT_CORPUS = (
    {
        "workflow_id": "01_Exterior_Hero",
        "camera_motion": "slow_push",
        "intent": "Create a subtle exterior reveal while preserving building massing and facade openings.",
        "camera_fragment": "The camera pushes in",
    },
    {
        "workflow_id": "02_Day_Night_Transition",
        "camera_motion": "static",
        "intent": "Transition from daylight to night while keeping the architecture and composition unchanged.",
        "camera_fragment": "The camera holds a static shot",
    },
    {
        "workflow_id": "03_Material_Detail",
        "camera_motion": "static",
        "intent": "Show a close material detail without changing the building geometry.",
        "camera_fragment": "The camera holds a static shot",
    },
    {
        "workflow_id": "04_Drone_Aerial",
        "camera_motion": "aerial_reveal",
        "intent": "Reveal the full site from an elevated view while preserving its spatial layout.",
        "camera_fragment": "The camera rises and reveals the wider site",
    },
    {
        "workflow_id": "05_Slow_Walkthrough",
        "camera_motion": "walkthrough",
        "intent": "Move from the interior toward the exterior at a slightly faster controlled pace.",
        "camera_fragment": "The camera tracks forward",
    },
)


class PromptEngineClosureTests(unittest.TestCase):
    def request(self) -> PromptReasoningRequest:
        return PromptReasoningRequest(
            mode="I2VA", duration=5, reference_count=1,
            workflow_id="05_Slow_Walkthrough", camera_motion="walkthrough",
            user_intent="从目前图片视觉室内走到室外空间，移动速度可以稍微快点",
            reference_image_path=r"C:\private\reference.png",
        )

    def test_offline_owner_case_is_non_empty_and_preserves_speed(self):
        result = OfflineH3Compiler().compile(self.request())
        self.assertTrue(result["prompt"])
        self.assertTrue(result["validator_result"]["pass"], result)
        self.assertIn("interior", result["prompt"])
        self.assertIn("exterior", result["prompt"])
        self.assertIn("faster", result["prompt"])
        self.assertNotIn("slow speed", result["prompt"])

    def test_auto_without_configured_provider_uses_offline(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            result = UniversalPromptEngine().generate(self.request(), provider="AUTO")
        self.assertTrue(result["optimized_prompt"])
        self.assertEqual(result["engine_mode"], "OFFLINE_COMPILER")
        self.assertTrue(result["validator_result"]["pass"])
        provider = mock.Mock()
        provider.provider = "ANTIGRAVITY"
        provider.describe.return_value = {
            "provider": "ANTIGRAVITY", "configured": True, "available": True,
            "multimodal_capable": False,
        }
        provider.generate.side_effect = AssertionError("AUTO must stay offline")
        engine = UniversalPromptEngine({"ANTIGRAVITY": provider})
        configured_result = engine.generate(self.request(), provider="AUTO")
        self.assertEqual(configured_result["engine_mode"], "OFFLINE_COMPILER")
        self.assertEqual(configured_result["provider"], "OFFLINE_COMPILER")
        provider.generate.assert_not_called()

    def test_observed_agy_json_envelope_is_unwrapped(self):
        inner = json.dumps({"optimized_prompt": "For the target video, at 0.00 seconds into the target video, <Picture 1> is fully referenced.\n\nintegrated_multimodal_description: interior to exterior\n\noverall_soundscape: quiet\n\nnon_diegetic_music: N/A"})
        raw = json.dumps({"conversation_id": "opaque", "status": "SUCCESS", "response": inner})
        prompt, parsed = CLIReasoningProvider._parse_output(raw)
        self.assertIn("interior to exterior", prompt)
        self.assertEqual(parsed["conversation_id"], "opaque")

    def test_minimal_provider_payload_gets_common_contract_fields(self):
        provider = mock.Mock()
        provider.generate.return_value = {
            "optimized_prompt": (
                "For the target video, at 0.00 seconds into the target video, "
                "<Picture 1> is fully referenced.\n\n"
                "integrated_multimodal_description: interior to exterior\n\n"
                "overall_soundscape: quiet\n\n"
                "non_diegetic_music: N/A"
            )
        }
        result = UniversalPromptEngine({"TEST_PROVIDER": provider}).generate(
            self.request(), provider="TEST_PROVIDER"
        )
        self.assertEqual(result["mode"], "I2VA")
        self.assertEqual(result["workflow"], "05_Slow_Walkthrough")
        self.assertEqual(result["duration_seconds"], 5)
        self.assertEqual(result["reference_count"], 1)
        self.assertEqual(result["overall_soundscape"], "quiet")
        self.assertEqual(result["non_diegetic_music"], "N/A")

    def test_agy_command_attaches_print_prompt_and_safe_defaults(self):
        provider = CLIReasoningProvider("agy.exe", provider_name="ANTIGRAVITY")
        command = provider._build_command("probe")
        self.assertIn("--print=probe", command)
        self.assertIn("--output-format", command)
        self.assertIn("json", command)
        self.assertIn("--disable-slash-commands", command)
        self.assertIn("--effort", command)
        self.assertIn("medium", command)

    def test_text_provider_request_does_not_leak_local_image_path(self):
        provider = CLIReasoningProvider("agy.exe", provider_name="ANTIGRAVITY")
        payload = provider._request_text(self.request(), {"source": "public"})
        self.assertNotIn(r"C:\private", payload)
        self.assertIn('"reference_image_path": null', payload)

        # Exercise the non-AGY stdin protocol too; it must use the same
        # consent-gated request representation as the printed CLI prompt.
        text_provider = CLIReasoningProvider(sys.executable, provider_name="CUSTOM_CLI")
        completed = mock.Mock(returncode=0, stdout="compiled prompt", stderr="")
        with mock.patch("runtime.h3_prompt_engine.subprocess.run", return_value=completed) as run:
            text_provider.generate(self.request(), {"source": "public"})
        sent = json.loads(run.call_args.kwargs["input"])
        self.assertIsNone(sent["request"]["reference_image_path"])
        self.assertEqual(sent["request"]["reference_image_paths"], [])
        self.assertIsNone(sent["reference_image"])
        self.assertEqual(sent["reference_images"], [])
        self.assertNotIn(r"C:\private", json.dumps(sent))

    def test_skill_bundle_identity_is_part_of_prompt_freshness(self):
        identity = {
            "intent": "fixture intent",
            "workflow": "fixture",
            "reference_hash": "ref-hash",
            "parameters": {"duration": 5},
            "provider": "OFFLINE_COMPILER",
            "skill_hash": "a" * 64,
            "skill_version": "fixture-skill-v1",
        }
        record = {
            "verified": {"pass": True},
            "status": "CURRENT",
            "workflow": identity["workflow"],
            "input_hash": prompt_input_hash(
                identity["intent"], identity["workflow"],
                identity["reference_hash"], identity["parameters"],
                identity["provider"], skill_hash=identity["skill_hash"],
                skill_version=identity["skill_version"],
            ),
            "provenance": {"skill_hash": identity["skill_hash"]},
            "skill_version": identity["skill_version"],
        }
        self.assertTrue(is_current_prompt(
            record, intent=identity["intent"], workflow=identity["workflow"],
            reference_hash=identity["reference_hash"],
            parameters=identity["parameters"], provider=identity["provider"],
            skill_hash=identity["skill_hash"],
            skill_version=identity["skill_version"],
        ))
        self.assertFalse(is_current_prompt(
            record, intent=identity["intent"], workflow=identity["workflow"],
            reference_hash=identity["reference_hash"],
            parameters=identity["parameters"], provider=identity["provider"],
            skill_hash="b" * 64, skill_version=identity["skill_version"],
        ))
        legacy = {**record, "provenance": {}, "input_hash": prompt_input_hash(
            identity["intent"], identity["workflow"], identity["reference_hash"],
            identity["parameters"], identity["provider"],
        )}
        self.assertFalse(is_current_prompt(
            legacy, intent=identity["intent"], workflow=identity["workflow"],
            reference_hash=identity["reference_hash"],
            parameters=identity["parameters"], provider=identity["provider"],
            skill_hash=identity["skill_hash"],
            skill_version=identity["skill_version"],
        ))

    def test_golden_prompt_corpus_is_deterministic_and_matches_execution_binding(self):
        registry = load_golden_registry()["workflows"]
        corpus_ids = {case["workflow_id"] for case in GOLDEN_PROMPT_CORPUS}
        self.assertEqual(corpus_ids, set(registry))
        compiler = OfflineH3Compiler()

        for case in GOLDEN_PROMPT_CORPUS:
            workflow_id = case["workflow_id"]
            entry = registry[workflow_id]
            roles = required_reference_roles(workflow_id)
            self.assertEqual(len(roles), entry["required_reference_count"])
            request = PromptReasoningRequest(
                mode=entry["mode"],
                duration=4.0,
                user_intent=case["intent"],
                reference_count=len(roles),
                workflow_id=workflow_id,
                camera_motion=case["camera_motion"],
            )

            first = compiler.compile(request)
            second = compiler.compile(request)
            self.assertEqual(first["provider"], "OFFLINE_COMPILER", workflow_id)
            self.assertEqual(first["engine_mode"], "OFFLINE_COMPILER", workflow_id)
            self.assertTrue(first["validator_result"]["pass"], first)
            self.assertEqual(first["prompt"], second["prompt"], workflow_id)

            execution_prompt = apply_architecture_profile(
                first["prompt"], workflow_id)
            self.assertIn(case["camera_fragment"], execution_prompt, workflow_id)
            self.assertIn("integrated_multimodal_description:", execution_prompt)
            self.assertIn("overall_soundscape:", execution_prompt)
            self.assertIn("non_diegetic_music:", execution_prompt)

            references = [
                {
                    "asset_id": f"synthetic-{workflow_id}-{index}",
                    "project_id": "synthetic-study",
                    "role": role,
                    "approval_state": "APPROVED",
                    "sha256": hashlib.sha256(
                        f"{workflow_id}:{role}".encode("utf-8")).hexdigest(),
                    "path_or_ref": f"synthetic-{workflow_id}-{index}.png",
                }
                for index, role in enumerate(roles)
            ]
            binding_request = {
                "study_id": "synthetic-study",
                "reference_assets": references,
                "generation_parameters": {
                    "quality": "NATIVE_HIGH", "duration": 4.0,
                    "fps": 24, "seed": 42,
                },
                "prompt_payload": {"prompt": execution_prompt},
            }
            bound = bind_golden_workflow(binding_request, workflow_id)
            generation_nodes = [
                node for node in bound.values()
                if node.get("class_type") == "MiniMaxH3ImageToVideo"
            ]
            self.assertEqual(len(generation_nodes), 1, workflow_id)
            self.assertEqual(
                generation_nodes[0]["inputs"]["prompt"], execution_prompt,
                workflow_id,
            )

            second_bound = bind_golden_workflow(binding_request, workflow_id)
            self.assertEqual(
                canonical_payload_sha256(bound),
                canonical_payload_sha256(second_bound),
                workflow_id,
            )


if __name__ == "__main__":
    unittest.main()
