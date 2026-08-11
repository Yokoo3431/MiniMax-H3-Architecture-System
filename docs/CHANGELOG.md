# Changelog

All notable changes to the `MiniMax-H3-Architecture-System` project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.7.2] - 2026-08-11

### Added
- **Workflow Intelligence Engine (`runtime/workflow_intelligence/`)**: `workflow_schema.py`, `workflow_matcher.py`, `workflow_parameter_mapper.py`, `workflow_selector.py`.
- **Semantic Workflow Registry (`configs/workflow_registry.json`)**: Upgraded to semantic workflow database.
- **Architecture Video Preset System (`configs/video_presets.json`)**: Added Exterior Hero, Walkthrough, Aerial Drone, Day Night Transition, and Architecture Analysis presets.
- **ComfyUI Workflow Parameter Adapter (`runtime/comfy_workflow_adapter.py`)**: Parameter and node payload injector.
- **Documentation (`docs/V0.7.2_Workflow_Intelligence_Report.md`, `V0.7.2_User_Workflow_Guide.md`)**.
- **Automated Unit Tests (`tests/test_workflow_selector.py`, `test_workflow_matching.py`, `test_video_preset.py`, `test_comfy_adapter.py`)**: 39 unit test cases passing 100%.

## [0.7.1.7] - 2026-08-11

### Added
- **Architecture Memory Schema & Database (`configs/architecture_memory_schema.json`, `architecture_memory.json`)**.
- **Semantic Memory Retriever Engine (`skills/architecture_prompt/memory_retriever.py`)**.

## [0.7.1.6] - 2026-08-11

### Added
- **Architectural Reasoning Schema & Graph (`configs/architecture_reasoning_schema.json`, `architecture_reasoning_graph.json`)**.
