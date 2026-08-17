"""Architect Video Studio mock API package (PATCH2.6-B).

Contract-first prototype: these APIs return mock data and NEVER call ComfyUI,
GPU, or the Native runtime. Prompt generation reuses the frozen
OfficialSkillAdapter/H3PromptBridge read-only (pure Python, no GPU).
"""
