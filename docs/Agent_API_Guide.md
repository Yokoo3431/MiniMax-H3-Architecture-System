# MiniMax H3 Agent API & Task Router Integration Guide

> **Supported Agents**: Antigravity, Codex, Hermes, OpenClaw

---

## Programmatic Python API Usage

AI Agents can import `MiniMaxH3TaskRouter` directly:

```python
from scripts.agent_h3_video_api import MiniMaxH3TaskRouter

# Initialize router (automatically runs HAL GPU auto-detection)
router = MiniMaxH3TaskRouter()

# Execute task with natural language description
result = router.route_and_execute(
    image_path="architectural_rendering.png",
    task_description="Breathtaking aerial drone view of modern hospital complex masterplan"
)

print("Execution Status :", result["status"])
print("Selected Workflow:", result["workflow_selected"])
print("Hardware Profile :", result["hardware_profile"])
print("Output Video Path:", result["video_path"])
```

---

## Agent Invocation Flow

1. **Antigravity Agent**: Supervized architectural design & video generation pipeline.
2. **Codex Agent**: Automated workflow testing, manifest audits, and batch rendering tasks.
3. **Hermes Agent**: Conversational user interaction & natural language task parsing.
4. **OpenClaw Agent**: Cross-machine orchestration and job scheduling.
