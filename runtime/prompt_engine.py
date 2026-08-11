"""Runtime Prompt Engine Module (V0.7.1)
Wraps skills.architecture_prompt.prompt_engine for runtime orchestration.
"""

import sys
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from skills.architecture_prompt.prompt_engine import ArchitecturePromptEngine

class RuntimePromptEngine:
    """Runtime interface for Architecture Prompt Skill Engine."""

    def __init__(self):
        self.engine = ArchitecturePromptEngine()

    def generate_prompt_and_intent(self, text: str) -> dict:
        return self.engine.process_request(text)
