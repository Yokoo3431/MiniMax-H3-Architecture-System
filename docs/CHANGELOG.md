# Changelog

All notable changes to the `MiniMax-H3-Architecture-System` project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.7.8.1] - 2026-08-12

### Added
- **Environment Auditor (`runtime/audit/environment_auditor.py`)**: Audits ComfyUI installation, CUDA/GPU, VRAM, and H3 model assets.
- **Skill Auditor (`runtime/audit/skill_auditor.py`)**: Audits MiniMax H3 official skill definitions and prompt rules.
- **Model Ecosystem Auditor (`runtime/audit/model_registry_auditor.py`)**: Audits required models, LoRAs, and asset paths.
- **Acceleration Auditor (`runtime/audit/acceleration_auditor.py`)**: Audits INT8 quantization, CPU offloading, attention memory, and VRAM profiles.
- **Audit JSON Manifests (`configs/audit_*.json`)**.
- **Prompt Pipeline Test (`tests/test_official_prompt_pipeline.py`)**.
- **Foundation Audit Report (`docs/V0.7.8.1_Foundation_Audit_Report.md`)**: Complete PASS assessment across 6 foundation pillars.

## [0.7.8] - 2026-08-12

### Added
- **Architect Request & Response Schemas (`runtime/interface/`)**.
- **Architect Video Presets (`configs/user_video_presets.json`)**.
