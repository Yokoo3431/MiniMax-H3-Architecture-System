# MiniMax H3 Architecture Infrastructure System

[![Version](https://img.shields.io/badge/version-1.0.0-blue.svg)](docs/version.md)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![ComfyUI](https://img.shields.io/badge/ComfyUI-0.27.0-orange.svg)](https://github.com/comfyanonymous/ComfyUI)
[![Hardware](https://img.shields.io/badge/GPU-RTX%205070%2012GB-76B900.svg)](https://nvidia.com)

A professional, version-controlled, cross-machine, Agent-callable infrastructure layer for **MiniMax H3** architectural video generation workflows.

---

## 🌟 Key Features

1. **Asset Separation**: Workflows, prompt dictionaries, skills, and configuration files are isolated into a standalone Git repository, avoiding local ComfyUI folder lock-in.
2. **Model Path Abstraction (`configs/extra_model_paths.yaml`)**: Decouples 40GB model weights from code. Supports `D:\`, `E:\`, and `NAS` network shares without duplicating weight files across computers.
3. **Environment Restoration (`scripts/setup_environment.bat`)**: Automated 5-stage script to check dependencies, link custom nodes, and restore workflows into ComfyUI.
4. **Agent Integration Layer (`scripts/agent_h3_video_api.py`)**: Programmatic API for AI Agents (Antigravity, Codex, Hermes) to trigger video generation given natural language task prompts and rendering images.
5. **Version Control & Auditing**: Semantic versioning (`version.md`) and change tracking (`CHANGELOG.md`) with 100% hash parity validation.

---

## 📁 Repository Structure

```
MiniMax-H3-Architecture-System/
├── workflows/         # Production architectural workflow JSONs
│   ├── 1_建筑效果图_ImageToVideo.json
│   ├── 2_建筑鸟瞰动画_AerialView.json
│   └── 3_建筑夜景灯光变化_NightTransition.json
├── prompts/           # Structured architectural positive/negative prompt presets
│   └── architectural_animation_prompts.json
├── skills/            # Antigravity AI Agent Skill definition
│   └── minimax-h3-architectural-video/SKILL.md
├── configs/           # Path abstraction & system defaults
│   ├── extra_model_paths.yaml
│   └── system_config.json
├── scripts/           # Environment recovery, Agent API & sync simulation
│   ├── setup_environment.bat
│   ├── agent_h3_video_api.py
│   └── sync_test_simulation.py
└── docs/              # Version specs, changelog & infrastructure audit report
    ├── version.md
    ├── CHANGELOG.md
    └── MiniMax_H3_Architecture_Infrastructure_Report.md
```

---

## 🚀 Quick Start Guide

### 1. Clone Repository (Machine B)
```bash
git clone https://github.com/Yokoo3431/MiniMax-H3-Architecture-System.git
cd MiniMax-H3-Architecture-System
```

### 2. Environment Restoration
Double click `scripts/setup_environment.bat` or run:
```cmd
scripts\setup_environment.bat
```

### 3. Agent Programmatic Invocation
```python
from scripts.agent_h3_video_api import MiniMaxH3AgentAPI

api = MiniMaxH3AgentAPI()
result = api.generate_video(
    image_path="path/to/rendering.png",
    task_description="Modern glass villa evening lighting pan",
    workflow_name="1_建筑效果图_ImageToVideo.json"
)

print("Generated Video Path:", result["video_path"])
```

---

## 📄 License & Audit

For detailed infrastructure architecture documentation and audit metrics, see [docs/MiniMax_H3_Architecture_Infrastructure_Report.md](docs/MiniMax_H3_Architecture_Infrastructure_Report.md).
