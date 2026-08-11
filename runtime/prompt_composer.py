"""Prompt Composer Module
Composes positive and negative architectural prompts based on task keywords and prompt library presets.
"""

import json
from pathlib import Path

class PromptComposer:
    """Combines natural language tasks with positive/negative prompt dictionary presets."""

    def __init__(self, prompt_file: Path):
        self.prompt_file = prompt_file
        self.library = self._load_library()

    def _load_library(self) -> dict:
        if self.prompt_file.is_file():
            try:
                with open(self.prompt_file, "r", encoding="utf-8") as f:
                    return json.load(f).get("prompt_templates", {})
            except Exception:
                pass
        return {}

    def compose_prompt(self, task_description: str, prompt_key: str) -> tuple[str, str]:
        preset = self.library.get(prompt_key, {})
        default_pos = preset.get("default_positive", "cinematic architectural animation of modern building, pristine facade, 4k ultra detailed")
        default_neg = preset.get("default_negative", "warped architecture, flickering, low resolution, artifacting")

        positive = f"{task_description}, {default_pos}"
        return positive, default_neg
