# Changelog

All notable changes to the `MiniMax-H3-Architecture-System` project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.7.3] - 2026-08-12

### Added
- **Architecture Vision Skill (`skills/architecture_vision/`)**: `SKILL.md`, `vision_schema.py`, `architectural_feature_extractor.py`, `image_analyzer.py`, `vision_intent_bridge.py`.
- **Architecture Visual Schema (`configs/architecture_visual_schema.json`)**: Visual feature schema.
- **50 Architecture Image Analysis Examples (`configs/architecture_vision_examples.json`)**.
- **Upgraded Workflow Matcher (`runtime/workflow_intelligence/workflow_matcher.py`)**: Supports visual matching.
- **Upgraded Runtime Orchestrator (`runtime/h3_orchestrator.py`)**: Integrates Vision Intelligence into the end-to-end request pipeline.
- **Documentation (`docs/V0.7.3_Vision_Intelligence_Report.md`, `V0.7.3_Image_Workflow_User_Guide.md`)**.
- **Automated Unit Tests (`tests/test_vision_schema.py`, `test_image_analysis.py`, `test_vision_workflow_bridge.py`)**: 44 unit test cases passing 100%.

## [0.7.2] - 2026-08-11

### Added
- **Workflow Intelligence Engine (`runtime/workflow_intelligence/`)**.
- **Semantic Workflow Registry (`configs/workflow_registry.json`)**.
