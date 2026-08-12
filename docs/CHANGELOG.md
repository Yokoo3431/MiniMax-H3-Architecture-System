# Changelog

All notable changes to the `MiniMax-H3-Architecture-System` project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.8.0-rc3.1] - 2026-08-12

### Added / Fixed
- **Launcher Git Auto-Detection (`launcher/Start_MiniMax_H3_Architect.bat`)**: Auto-detects Git executable, sets `GIT_PYTHON_GIT_EXECUTABLE` to resolve ComfyUI-Manager startup error.
- **Workflow Deployer Script (`scripts/deploy_workflows.py`)**: Copies 5 production workflows to `ComfyUI/user/default/workflows/ARCHITECTURE_PRODUCTION/` and archives old workflows to `ARCHIVE_RC2/`.
- **Workflow Validation Report (`configs/workflow_validation_report.json`)**: Verifies 0 missing nodes across all 5 production workflows.
- **V0.8.0 RC3.1 Integration Fix Report (`docs/V0.8.0_RC3.1_Integration_Fix_Report.md`)**.
- **Integration Fix Unit Tests (`tests/test_v080_rc31_integration.py`)**.

## [0.8.0-rc3] - 2026-08-12

### Added
- **5 Real Independent Local Production Workflows (`workflows/`)**.
