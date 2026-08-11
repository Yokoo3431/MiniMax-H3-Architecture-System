# Changelog

All notable changes to the `MiniMax-H3-Architecture-System` project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] - 2026-08-11

### Added
- **One-Click Installer (`installer/install.bat`)**: Fresh PC 10-stage automated installer (Windows, NVIDIA GPU, CUDA, ComfyUI, custom nodes, `extra_model_paths.yaml`, Python dependencies, workflows, prompts, skills).
- **Automated Model Downloader (`scripts/download_models.py`)**: Checks missing weight files, calculates disk storage requirements (~39.55 GB), and downloads from official Hugging Face mirror endpoints (`hf-mirror.com`).
- **One-Click Updater (`updater/update.bat`)**: Existing installation 8-stage updater (`git pull` -> version check -> asset sync -> node & model validation).
- **System Version Specification (`configs/system_version.json`)**: Pinned system manifest (`v0.3.0`).
- **Comprehensive Documentation Suite (`docs/`)**: Added `Installation_Guide.md`, `User_Update_Guide.md`, `GitHub_Distribution_Guide.md`, `Model_Download_Guide.md`, `Version_Control_Strategy.md`, and `MiniMax_H3_Architecture_System_V0.3_Deployment_Report.md`.

## [0.2.0] - 2026-08-11

### Added
- **Hardware Abstraction Layer (HAL)**: Added `hardware/detect_gpu.py` with GPU auto-detection and profile matching (`H3_LOW` 8GB, `H3_STANDARD` 12GB, `H3_PRO` 24GB+).
- **Model Integrity Manifest**: Added `configs/model_manifest.json` and `scripts/check_models.py`.
- **Custom Node Manifest**: Added `configs/node_manifest.json` and `scripts/check_nodes.py`.
- **Workflow Registry**: Added `configs/workflow_registry.json`.
- **H3 Task Router**: Upgraded `scripts/agent_h3_video_api.py` with dynamic task understanding, workflow routing, and hardware adaptation.

## [1.0.0] - 2026-08-11

### Added
- **Asset Separation**: Isolated `workflows/`, `prompts/`, `skills/`, `configs/`, `scripts/`, and `docs/`.
- **Model Path Abstraction**: Added `configs/extra_model_paths.yaml` supporting multi-drive (`D:`, `E:`, `NAS`) mapping.
