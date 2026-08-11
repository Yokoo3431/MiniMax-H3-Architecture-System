# Changelog

All notable changes to the `MiniMax-H3-Architecture-System` project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-08-11

### Added
- **Asset Separation**: Isolated `workflows/`, `prompts/`, `skills/`, `configs/`, `scripts/`, and `docs/` from local ComfyUI folders into `MiniMax-H3-Architecture-System`.
- **Model Path Abstraction**: Added `configs/extra_model_paths.yaml` supporting multi-drive (`D:`, `E:`, `NAS`) mapping without duplicating 40GB model weights.
- **Environment Restoration**: Added `scripts/setup_environment.bat` for automated dependency check, folder link restoration, and custom node audit.
- **Agent API Layer**: Added `scripts/agent_h3_video_api.py` enabling Antigravity, Codex, and Hermes AI agents to trigger programmatic video generation.
- **Multi-PC Sync Simulation**: Added `scripts/sync_test_simulation.py` to verify hash parity between PC-A and PC-B workspace updates.
- **Documentation**: Initialized `version.md`, `CHANGELOG.md`, and `MiniMax_H3_Architecture_Infrastructure_Report.md`.
