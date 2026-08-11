"""Architectural Reasoning Engine Module.
Performs reasoning graph lookup mapping concepts -> meaning -> visual -> prompt expressions.
"""

import json
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent.parent
GRAPH_FILE = SYSTEM_ROOT / "configs" / "architecture_reasoning_graph.json"

class ArchitectureReasoningEngine:
    """Retrieves reasoning graph nodes for architectural intent enrichment."""

    def __init__(self):
        self.graph = self._load_graph()

    def _load_graph(self) -> dict:
        if GRAPH_FILE.is_file():
            try:
                with open(GRAPH_FILE, "r", encoding="utf-8") as f:
                    return json.load(f).get("nodes", {})
            except Exception:
                pass
        return {}

    def reason_about_text(self, text: str) -> dict:
        desc = text.lower()
        matched_nodes = []
        enriched_prompts = []

        if any(kw in desc for kw in ["安藤", "清水混凝土", "ando", "fair-faced concrete"]):
            node = self.graph.get("ando_concrete", {})
            matched_nodes.append(node)
            enriched_prompts.extend(node.get("prompt", []))
        if any(kw in desc for kw in ["粗野", "野兽派", "brutalist", "brutalism"]):
            node = self.graph.get("brutalist_monument", {})
            matched_nodes.append(node)
            enriched_prompts.extend(node.get("prompt", []))
        if any(kw in desc for kw in ["木", "北欧", "scandinavian", "timber"]):
            node = self.graph.get("scandinavian_timber", {})
            matched_nodes.append(node)
            enriched_prompts.extend(node.get("prompt", []))
        if any(kw in desc for kw in ["玻璃", "幕墙", "high-tech", "curtainwall"]):
            node = self.graph.get("hightech_glass_tower", {})
            matched_nodes.append(node)
            enriched_prompts.extend(node.get("prompt", []))
        if any(kw in desc for kw in ["日式", "庭院", "静谧", "zen", "courtyard"]):
            node = self.graph.get("zen_courtyard_house", {})
            matched_nodes.append(node)
            enriched_prompts.extend(node.get("prompt", []))

        return {
            "matched_reasoning_nodes": [n.get("concept") for n in matched_nodes if "concept" in n],
            "reasoning_prompts": list(set(enriched_prompts))
        }
