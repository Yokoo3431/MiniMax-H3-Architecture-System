# Changelog

All notable changes to the `MiniMax-H3-Architecture-System` project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.7.5] - 2026-08-12

### Added
- **Architecture Acceleration Skill (`runtime/acceleration/`)**: `acceleration_schema.py`, `vram_optimizer.py`, `timestep_optimizer.py`, `generation_profile_selector.py`.
- **Model Ecosystem Registry (`configs/model_registry.json`)**: Checkpoint, LoRA, camera motion, lighting style, and style pack registry.
- **Upgraded Workflow Execution Package (`runtime/workflow_intelligence/workflow_execution_package.py`)**: Added `acceleration_profile`, `model_package`, `optimization_strategy`.
- **Upgraded Runtime Orchestrator (`runtime/h3_orchestrator.py`)**: Returns structured execution payload with acceleration and model packages.
- **Documentation (`docs/V0.7.5_Acceleration_Report.md`, `V0.7.5_Model_Ecosystem_Report.md`)**.
- **Automated Unit Tests (`tests/test_acceleration_profile.py`, `test_model_registry.py`, `test_generation_strategy.py`)**: 59 unit test cases passing 100%.

## [0.7.4.1] - 2026-08-12

### Added
- **ComfyUI Workflow Adapter Engine (`runtime/execution/workflow_adapter.py`)**.
- **Execution Logging System (`runtime/execution/execution_logger.py`)**.
