"""Main Architecture Prompt Skill Engine Entrance.
Integrates IntentParser, PromptBuilder, and Workflow matching.
"""

from pathlib import Path
from skills.architecture_prompt.intent_parser import IntentParser
from skills.architecture_prompt.prompt_builder import PromptBuilder

class ArchitecturePromptEngine:
    """Core Prompt Intelligence Skill Engine."""

    def __init__(self):
        self.parser = IntentParser()
        self.builder = PromptBuilder()

    def process_request(self, text: str) -> dict:
        intent = self.parser.parse(text)
        pos_prompt, neg_prompt = self.builder.build_prompts(intent, text)

        # Map scene_type -> recommended workflow ID
        workflow_mapping = {
            "exterior": "1_image_to_video",
            "aerial": "2_aerial_view",
            "night_transition": "3_night_transition",
            "interior": "5_walkthrough",
            "massing_evolution": "6_massing_evolution",
            "circulation_analysis": "7_circulation_diagram",
            "exploded_axon": "8_exploded_axon",
            "structure_animation": "9_structure_animation",
            "facade_analysis": "10_envelope_analysis"
        }

        rec_wf = workflow_mapping.get(intent.scene_type, "1_image_to_video")

        return {
            "intent_schema": intent.to_dict(),
            "positive_prompt": pos_prompt,
            "negative_prompt": neg_prompt,
            "recommended_workflow": rec_wf,
            "recommended_profile": "H3_STANDARD"
        }
