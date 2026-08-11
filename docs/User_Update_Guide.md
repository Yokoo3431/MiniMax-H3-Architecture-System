# MiniMax H3 User Update Guide

## How to Keep Workflows & Assets Continuously Updated

### One-Click Update (Recommended)
Double click `updater/update.bat`.

The updater automatically:
1. Pulls the latest commits from `origin/main`
2. Re-synchronizes JSON workflows to `ComfyUI/user/default/workflows/`
3. Updates `prompts/architectural_animation_prompts.json`
4. Updates AI Agent skill definitions
5. Audits custom nodes and model weight integrity
