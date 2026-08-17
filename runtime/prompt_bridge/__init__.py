"""Architect Production Layer prompt bridge package (RC3.3 PATCH2.5+).

Production chain:
    ArchitectIntent -> OfficialSkillAdapter -> H3PromptBridge -> OfficialH3Prompt

The RC3-era ``official_h3_prompt_adapter`` (manual-concatenation adapter) is
DEPRECATED and intentionally NOT exported from this package. Forensic tests may
still import the legacy module directly, but production code must never import
or call it (enforced by tests/test_patch25a_hardening.py).
"""
from .architect_h3_prompt_bridge import H3PromptBridge

__all__ = ["H3PromptBridge"]
