---
name: minimax-h3-architectural-video
description: Antigravity AI Agent Skill for triggering and managing MiniMax H3 architectural video generation workflows. Use when generating architectural rendering animations, aerial drone views, or night lighting transitions.
---

# MiniMax H3 Architectural Video Generation Skill

This skill allows Antigravity AI Agents to programmatically generate cinematic architectural videos from rendering images using the MiniMax H3 infrastructure.

## Available Workflows

1. **`1_建筑效果图_ImageToVideo.json`**:
   - Primary workflow for single rendering image to smooth video animation.
   - Ideal for modern villa facade, street level perspective, landscape panning.

2. **`2_建筑鸟瞰动画_AerialView.json`**:
   - Aerial perspective drone flight animation for large master plans or building complexes.

3. **`3_建筑夜景灯光变化_NightTransition.json`**:
   - Golden hour to evening sunset and interior light illumination transition.

## Python API Usage

Agents can call `scripts/agent_h3_video_api.py` directly:

```python
from scripts.agent_h3_video_api import MiniMaxH3AgentAPI

api = MiniMaxH3AgentAPI(
    comfy_url="http://127.0.0.1:8188",
    system_root="d:\\AntigravityWorkspace\\Minimax H3-Comfyui Configuration\\MiniMax-H3-Architecture-System"
)

result = api.generate_video(
    image_path="path/to/architectural_render.png",
    task_description="Modern glass villa sunset lighting camera pan",
    workflow_name="1_建筑效果图_ImageToVideo.json",
    duration_seconds=4.0
)

print(f"Generated Video Path: {result['video_path']}")
```

## CLI Invocation

```bash
python scripts/agent_h3_video_api.py --image "input.png" --task "aerial view of hospital complex" --workflow "2_建筑鸟瞰动画_AerialView.json"
```
