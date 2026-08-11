"""Task Planner Module
Parses natural language task descriptions from AI Agents (Antigravity, Codex, Hermes, OpenClaw).
Extracts intent, scene type (visualization vs analysis), and camera motion requirements.
"""

import json

class TaskPlanner:
    """Parses natural language task descriptions into structured execution intent."""

    def plan_task(self, task_description: str) -> dict:
        desc = task_description.lower()
        
        intent_type = "visualization"
        if any(kw in desc for kw in ["massing", "circulation", "exploded", "structure", "envelope", "diagram", "analysis"]):
            intent_type = "analysis"

        return {
            "raw_task": task_description,
            "intent_type": intent_type,
            "has_aerial_intent": "aerial" in desc or "drone" in desc or "masterplan" in desc,
            "has_night_intent": "night" in desc or "lighting" in desc or "sunset" in desc,
            "has_orbit_intent": "orbit" in desc or "rotation" in desc or "360" in desc
        }
