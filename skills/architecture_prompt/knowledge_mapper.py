"""Architectural Knowledge Mapper Engine.
Maps architectural concepts (building types, spatial concepts, materials, design intents) to visual prompt keywords.
"""

import json
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent.parent
KNOWLEDGE_FILE = SYSTEM_ROOT / "configs" / "architecture_knowledge.json"

class KnowledgeMapper:
    """Maps architectural natural language concepts to visual prompt keywords."""

    def __init__(self):
        self.knowledge = self._load_knowledge()

    def _load_knowledge(self) -> dict:
        if KNOWLEDGE_FILE.is_file():
            try:
                with open(KNOWLEDGE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def map_text_to_keywords(self, text: str) -> dict:
        desc = text.lower()
        mapped_keywords = []

        # Map Spatial Concepts
        if "庭院" in desc or "courtyard" in desc:
            c_data = self.knowledge.get("spatial_concepts", {}).get("courtyard", {})
            mapped_keywords.extend(c_data.get("prompt_keywords", []))
        if "中庭" in desc or "atrium" in desc:
            a_data = self.knowledge.get("spatial_concepts", {}).get("atrium", {})
            mapped_keywords.extend(a_data.get("prompt_keywords", []))

        # Map Materials
        if "混凝土" in desc or "concrete" in desc:
            m_data = self.knowledge.get("materials", {}).get("exposed_concrete", {})
            mapped_keywords.extend(m_data.get("prompt_keywords", []))
        if "玻璃" in desc or "幕墙" in desc or "glass" in desc or "curtainwall" in desc:
            g_data = self.knowledge.get("materials", {}).get("glass_curtain_wall", {})
            mapped_keywords.extend(g_data.get("prompt_keywords", []))
        if "木" in desc or "格栅" in desc or "timber" in desc or "louver" in desc:
            t_data = self.knowledge.get("materials", {}).get("timber", {})
            mapped_keywords.extend(t_data.get("prompt_keywords", []))

        # Map Building Types
        if "博物馆" in desc or "museum" in desc:
            b_data = self.knowledge.get("building_types", {}).get("museum", {})
            mapped_keywords.extend(b_data.get("prompt_keywords", []))
        elif "别墅" in desc or "villa" in desc:
            v_data = self.knowledge.get("building_types", {}).get("residential", {})
            mapped_keywords.extend(v_data.get("prompt_keywords", []))

        return {
            "mapped_keywords": list(set(mapped_keywords)),
            "concept_count": len(mapped_keywords)
        }
