# Changelog

All notable changes to the `MiniMax-H3-Architecture-System` project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.8.0-rc3] - 2026-08-12

### Added
- **5 Real Independent Local Production Workflows (`workflows/`)**: `01_Exterior_Hero.json` ~ `05_Slow_Walkthrough.json` adapted to local ComfyUI model directories (`models/diffusion_models/`, `models/text_encoders/`, `models/vae/`).
- **RC3 Environment Reality Checker (`runtime/validation/rc3_environment_checker.py`)**: Hardware, CUDA, PyTorch, model paths, ffmpeg, ffprobe validation (Status: READY).
- **Chinese/English Prompt Adapter Bridge (`runtime/prompt_bridge/official_h3_prompt_adapter.py`)**.
- **Architect RC3 Test Guide (`docs/Architect_RC3_Test_Guide.md`)**.
- **V0.8.0 RC3 Technical Report (`docs/V0.8.0_RC3_Adaptation_Report.md`)**.
- **Local Adaptation Unit Tests (`tests/test_v080_rc3_local_adaptation.py`)**.

## [0.8.0-rc2] - 2026-08-12

### Added
- **Architect Personal Workspace (`userdata/personal_workspace/`)**.
