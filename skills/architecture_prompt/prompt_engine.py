"""Main Architecture Prompt Skill Engine Entrance (V0.7.2 Upgraded).
Integrates IntentParser -> ReasoningEngine -> MemoryRetriever -> WorkflowSelector -> PromptBuilder -> QualityEvaluator.
"""

from pathlib import Path
from skills.architecture_prompt.intent_parser import IntentParser
from skills.architecture_prompt.knowledge_mapper import KnowledgeMapper
from skills.architecture_prompt.reasoning_engine import ArchitectureReasoningEngine
from skills.architecture_prompt.memory_retriever import MemoryRetriever
from runtime.workflow_intelligence.workflow_selector import WorkflowIntelligenceSelector
from skills.architecture_prompt.prompt_builder import PromptBuilder
from runtime.prompt_quality import PromptQualityEvaluator

class ArchitecturePromptEngine:
    """Core Prompt Intelligence Skill Engine."""

    def __init__(self):
        self.parser = IntentParser()
        self.mapper = KnowledgeMapper()
        self.reasoning = ArchitectureReasoningEngine()
        self.retriever = MemoryRetriever()
        self.workflow_selector = WorkflowIntelligenceSelector()
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

        # 5. Workflow Intelligence Selection
        wf_package = self.workflow_selector.select_intelligence_workflow(intent.scene_type, text)

        # 6. Prompt Building
        pos_prompt, neg_prompt = self.builder.build_prompts(intent, text)
        extra_keywords = list(set(
            km_res["mapped_keywords"] +
            reasoning_res["reasoning_prompts"] +
            [memory_strategy["recommended_camera"], memory_strategy["recommended_light"]]
        ))
        if extra_keywords:
            pos_prompt = f"{pos_prompt}, {', '.join(extra_keywords)}"

        # 7. Quality Evaluation with Improvement Loop
        quality_res = self.evaluator.evaluate(pos_prompt, intent.to_dict())

        return {
            "intent": intent.to_dict(),
            "workflow": wf_package.to_dict(),
            "prompt": {
                "positive": pos_prompt,
                "negative": neg_prompt
            },
            "parameters": {
                "quality_score": quality_res["quality_score"],
                "preset_id": wf_package.preset_id,
                "quality_profile": wf_package.quality_profile
            },
            "intent_schema": intent.to_dict(),
            "knowledge_mapping": km_res,
            "reasoning_graph": reasoning_res,
            "memory_strategy": memory_strategy,
            "positive_prompt": pos_prompt,
            "negative_prompt": neg_prompt,
            "quality_score": quality_res["quality_score"],
            "quality_evaluation": quality_res,
            "recommended_workflow": wf_package.workflow_id,
            "recommended_profile": wf_package.quality_profile
        }
