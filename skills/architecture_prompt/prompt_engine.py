"""Main Architecture Prompt Skill Engine Entrance (V0.7.1.7 Upgraded).
Integrates IntentParser -> KnowledgeMapper -> ReasoningEngine -> MemoryRetriever -> PromptBuilder -> QualityEvaluator.
"""

from pathlib import Path
from skills.architecture_prompt.intent_parser import IntentParser
from skills.architecture_prompt.knowledge_mapper import KnowledgeMapper
from skills.architecture_prompt.reasoning_engine import ArchitectureReasoningEngine
from skills.architecture_prompt.memory_retriever import MemoryRetriever
from skills.architecture_prompt.prompt_builder import PromptBuilder
from runtime.prompt_quality import PromptQualityEvaluator

class ArchitecturePromptEngine:
    """Core Prompt Intelligence Skill Engine."""

    def __init__(self):
        self.parser = IntentParser()
        self.mapper = KnowledgeMapper()
        self.reasoning = ArchitectureReasoningEngine()
        self.retriever = MemoryRetriever()
        self.builder = PromptBuilder()
        self.evaluator = PromptQualityEvaluator()

    def process_request(self, text: str) -> dict:
        # 1. Intent Parsing with Reasoning Dimensions
        intent = self.parser.parse(text)

        # 2. Knowledge Mapping
        km_res = self.mapper.map_text_to_keywords(text)

        # 3. Architecture Reasoning Graph Lookup
        reasoning_res = self.reasoning.reason_about_text(text)

        # 4. Semantic Memory Retrieval Strategy
        memory_strategy = self.retriever.suggest_prompt_strategy(text)

        # 5. Prompt Building
        pos_prompt, neg_prompt = self.builder.build_prompts(intent, text)
        extra_keywords = list(set(
            km_res["mapped_keywords"] +
            reasoning_res["reasoning_prompts"] +
            [memory_strategy["recommended_camera"], memory_strategy["recommended_light"]]
        ))
        if extra_keywords:
            pos_prompt = f"{pos_prompt}, {', '.join(extra_keywords)}"

        # 6. Quality Evaluation with Improvement Loop
        quality_res = self.evaluator.evaluate(pos_prompt, intent.to_dict())

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
            "knowledge_mapping": km_res,
            "reasoning_graph": reasoning_res,
            "memory_strategy": memory_strategy,
            "positive_prompt": pos_prompt,
            "negative_prompt": neg_prompt,
            "quality_score": quality_res["quality_score"],
            "quality_evaluation": quality_res,
            "recommended_workflow": rec_wf,
            "recommended_profile": "H3_STANDARD"
        }
