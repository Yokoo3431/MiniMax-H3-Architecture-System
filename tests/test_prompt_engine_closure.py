"""Regression tests for the real Prompt Engine closure path."""

from __future__ import annotations

import json
import unittest
from unittest import mock

from runtime.h3_prompt_engine import (
    CLIReasoningProvider,
    OfflineH3Compiler,
    PromptReasoningRequest,
    UniversalPromptEngine,
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
        provider = CLIReasoningProvider(r"C:\Users\Pondsi\AppData\Local\agy\bin\agy.exe", provider_name="ANTIGRAVITY")
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


if __name__ == "__main__":
    unittest.main()
