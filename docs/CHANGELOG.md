# Changelog

All notable changes to the `MiniMax-H3-Architecture-System` project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.7.8.2] - 2026-08-12

### Added
- **Official Source Validator (`runtime/audit/official_source_validator.py`)**: Validates official skill source URL, commit, and SHA256 hash.
- **Model Runtime Load Test (`runtime/audit/model_runtime_test.py`)**: Tests loader compatibility for checkpoints, text encoders, and VAEs.
- **ComfyUI End-to-End Smoke Test (`runtime/audit/comfy_runtime_smoke_test.py`)**: Runs end-to-end API smoke test.
- **Runtime Memory Probe (`runtime/audit/runtime_memory_probe.py`)**: Measures peak VRAM (7.4GB) and CPU offload timing.
- **Validation JSON Manifests (`configs/audit_*.json`)**.
- **Runtime Reality Validation Report (`docs/V0.7.8.2_Runtime_Validation_Report.md`)**: Complete PASS assessment across 4 runtime pillars.

## [0.7.8.1] - 2026-08-12

### Added
- **Environment Auditor (`runtime/audit/environment_auditor.py`)**.
- **Skill Auditor (`runtime/audit/skill_auditor.py`)**.
