# Changelog

All notable changes to the `MiniMax-H3-Architecture-System` project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.7.7] - 2026-08-12

### Added
- **Closed Loop Controller (`runtime/feedback_loop/`)**: `loop_schema.py`, `feedback_controller.py`, `revision_executor.py` (max_iterations=2 safety bound).
- **Workflow Adjustment Layer (`runtime/workflow_intelligence/workflow_revision.py`)**: Dynamically adjusts camera speed, motion strength, steps, lighting, and geometry weights.
- **Comparison Engine (`runtime/critic/comparison_engine.py`)**: Evaluates score deltas across 5 dimensions.
- **Experience Memory Storage (`configs/architecture_memory.json`)**: Added structured `experiences` storage.
- **30 Feedback Loop Examples Dataset (`configs/feedback_loop_examples.json`)**.
- **Upgraded Runtime Orchestrator (`runtime/h3_orchestrator.py`)**: Added `run_feedback_loop()` closed-loop API.
- **Documentation (`docs/V0.7.7_Closed_Loop_Report.md`, `V0.7.7_User_Feedback_Loop_Guide.md`)**.
- **Automated Unit Tests (`tests/test_feedback_controller.py`, `test_revision_executor.py`, `test_comparison_engine.py`, `test_closed_loop_pipeline.py`)**: 70 unit test cases passing 100%.

## [0.7.6] - 2026-08-12

### Added
- **Architectural Critic Core (`runtime/critic/`)**.
- **Model Registry Upgrade (`configs/model_registry.json`)**.
