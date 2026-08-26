"""Offline-first universal H3 Prompt Engine contracts."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from runtime.h3_prompt_engine import (
    H3PromptValidator,
    OfflineH3Compiler,
    OpenAICompatibleProvider,
    PromptReasoningRequest,
    UniversalPromptEngine,
    discover_providers,
)


class UniversalH3PromptEngineTests(unittest.TestCase):
    def request(self, mode: str, count: int) -> PromptReasoningRequest:
        return PromptReasoningRequest(
            mode=mode, duration=5, reference_count=count,
            workflow_id="fixture", camera_motion="walkthrough",
            user_intent="从室内缓慢走向水池边，在蓝调时刻停留",
        )

    def test_offline_compiles_all_five_modes(self):
        compiler = OfflineH3Compiler()
        for mode, count in (("T2VA", 0), ("I2VA", 1), ("FL2VA", 2), ("L2VA", 1), ("Ref2VA", 1)):
            result = compiler.compile(self.request(mode, count))
            self.assertTrue(result["validator_result"]["pass"], result)
            self.assertEqual(result["engine_mode"], "OFFLINE_COMPILER")
            self.assertFalse(result["skill_execution"])

    def test_offline_does_not_claim_image_understanding_or_custom_field(self):
        result = OfflineH3Compiler().compile(self.request("I2VA", 1))
        self.assertIn("H3", result["skill_source"])
        self.assertNotIn("User intent focus:", result["prompt"])
        self.assertNotIn("Picture 2", result["prompt"])
        self.assertFalse(result["multimodal_capable"])

    def test_validator_rejects_bad_order_and_placeholder(self):
        validator = H3PromptValidator()
        result = validator.validate(
            "overall_soundscape: [TODO]\n\n"
            "integrated_multimodal_description: [Shot 1]\n\n"
            "non_diegetic_music: N/A",
            mode="T2VA", duration=5,
        )
        self.assertFalse(result["pass"])
        self.assertTrue(any("order" in error for error in result["errors"]))
        self.assertTrue(any("placeholder" in error for error in result["errors"]))

    def test_provider_failure_falls_back_to_offline(self):
        class BrokenProvider:
            provider = "TEXT_REASONING_H3"
            multimodal_capable = False

            def generate(self, request, bundle):
                raise TimeoutError("fixture timeout")

        engine = UniversalPromptEngine({"BROKEN": BrokenProvider()})
        result = engine.generate(self.request("I2VA", 1), provider="BROKEN")
        self.assertTrue(result["fallback"])
        self.assertEqual(result["engine_mode"], "OFFLINE_COMPILER")
        self.assertTrue(result["validator_result"]["pass"])
        self.assertIn("TimeoutError", result["fallback_reason"])

    def test_openai_compatible_fixture_and_remote_image_consent(self):
        def transport(_url, payload, _headers, _timeout):
            self.assertEqual(payload["temperature"], 0)
            return {"choices": [{"message": {"content": OfflineH3Compiler().compile(self.request("I2VA", 1))["prompt"]}}]}

        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "reference.png"
            image.write_bytes(b"not a real image fixture")
            provider = OpenAICompatibleProvider(
                "http://127.0.0.1:9999", "fixture", multimodal_capable=True,
                transport=transport,
            )
            with self.assertRaises(PermissionError):
                provider.generate(
                    PromptReasoningRequest("I2VA", 5, "walk", reference_count=1,
                                           reference_image_path=str(image), image_consent=False),
                    {"source": "fixture"},
                )
            result = provider.generate(
                PromptReasoningRequest("I2VA", 5, "walk", reference_count=1,
                                       reference_image_path=str(image), image_consent=True),
                {"source": "fixture"},
            )
            self.assertEqual(result["provider"], "OPENAI_COMPATIBLE_HTTP")
            self.assertTrue(result["multimodal_capable"])

    def test_provider_discovery_never_invokes_provider(self):
        providers = discover_providers()
        self.assertEqual(providers[0]["provider"], "OFFLINE_COMPILER")
        self.assertTrue(providers[0]["selected_by_default"])


if __name__ == "__main__":
    unittest.main()
