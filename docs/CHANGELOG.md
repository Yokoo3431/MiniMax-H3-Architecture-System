# Changelog

All notable changes to the `MiniMax-H3-Architecture-System` project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.7.8] - 2026-08-12

### Added
- **Architect Request & Response Schemas (`runtime/interface/`)**: `architect_request.py`, `architect_response.py`.
- **Architect Video Presets (`configs/user_video_presets.json`)**: `Exterior Hero`, `Slow Walkthrough`, `Drone Aerial`, `Day Night Transition`, `Material Detail`.
- **Web UI Prototype (`interface/web/app.py`)**: Local Web UI script connecting front-end inputs to `H3Orchestrator`.
- **Upgraded Runtime Orchestrator (`runtime/h3_orchestrator.py`)**: Added `generate_from_architect_request()` API.
- **Documentation (`docs/V0.7.8_Architect_User_Guide.md`, `V0.7.8_Interface_Report.md`)**.
- **Automated Unit Tests (`tests/test_architect_request.py`, `test_user_interface.py`, `test_generation_api.py`)**: 75 unit test cases passing 100%.

## [0.7.7] - 2026-08-12

### Added
- **Closed Loop Controller (`runtime/feedback_loop/`)**.
- **Workflow Adjustment Layer (`runtime/workflow_intelligence/workflow_revision.py`)**.
