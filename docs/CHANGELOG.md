# Changelog

All notable changes to the `MiniMax-H3-Architecture-System` project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.7.4] - 2026-08-12

### Added
- **ComfyUI Execution Runtime (`runtime/execution/`)**: Added `comfy_api_client.py`, `execution_schema.py`, `execution_manager.py`, `execution_monitor.py`.
- **Workflow Execution Package (`runtime/workflow_intelligence/workflow_execution_package.py`)**: Defined execution payload bridge.
- **Upgraded Agent Video API (`runtime/h3_orchestrator.py`)**: Added `generate_architecture_video()` high-level API.
- **Runtime Error Handling**: Added offline detection, queue timeouts, node error monitoring.
- **Documentation (`docs/V0.7.4_Execution_Runtime_Report.md`, `V0.7.4_User_Generation_Guide.md`)**.
- **Automated Unit Tests (`tests/test_execution_package.py`, `test_comfy_execution.py`, `test_agent_video_generation.py`)**: 48 unit test cases passing 100%.

## [0.7.3] - 2026-08-12

### Added
- **Architecture Vision Skill (`skills/architecture_vision/`)**.
- **Architecture Visual Schema (`configs/architecture_visual_schema.json`)**.
