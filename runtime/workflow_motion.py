"""Workflow-specific camera-control normalization.

Natural-language intent is prompt content.  ``camera_motion`` is a structured
workflow control and must be selected from the frozen production registry
before a Job is created.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional


class WorkflowParameterError(ValueError):
    """A structured workflow control cannot satisfy its frozen contract."""

    code = "WORKFLOW_PARAMETER_ERROR"


_ROOT = Path(__file__).resolve().parents[1]
_REGISTRY = _ROOT / "configs" / "production_workflow_registry.json"


def _load_cameras() -> dict[str, tuple[str, ...]]:
    data = json.loads(_REGISTRY.read_text(encoding="utf-8"))
    return {
        workflow: tuple(entry.get("camera") or ())
        for workflow, entry in (data.get("workflows") or {}).items()
    }


WORKFLOW_CAMERAS = _load_cameras()

# Historical/semantic aliases are normalized only when they have an
# unambiguous workflow meaning.  The prompt remains natural language; this
# map controls only the structured runtime field.
_ALIASES = {
    "05_Slow_Walkthrough": {
        "slow_push": "walkthrough",
        "slow_walkthrough": "walkthrough",
        "walk": "walkthrough",
        "漫游": "walkthrough",
    },
}


def normalize_camera_motion(workflow: str, requested: Optional[str] = None) -> str:
    """Return an allowed motion for ``workflow`` or raise before Job creation."""
    allowed = WORKFLOW_CAMERAS.get(workflow)
    if not allowed:
        raise WorkflowParameterError(f"未知视频类型: {workflow}")
    value = (requested or "").strip()
    if not value:
        return allowed[0]
    value = _ALIASES.get(workflow, {}).get(value, value)
    if value not in allowed:
        raise WorkflowParameterError(
            f"{workflow} 的镜头动作不支持 {requested!r}，可用值: {list(allowed)}"
        )
    return value


def camera_contract(workflow: str) -> dict[str, object]:
    allowed = WORKFLOW_CAMERAS.get(workflow)
    if not allowed:
        raise WorkflowParameterError(f"未知视频类型: {workflow}")
    return {"workflow": workflow, "allowed": list(allowed), "default": allowed[0]}
