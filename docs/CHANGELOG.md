# Changelog

All notable changes to the `MiniMax-H3-Architecture-System` project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.8.0-rc1] - 2026-08-12

### Added
- **Production Freeze Master Controller (`runtime/production_freeze/freeze_validator.py`)**: Runs 7 Production Freeze Validation Gates.
- **Workflow Node Auditor (`runtime/production_freeze/workflow_node_auditor.py`)**: Audits 5 frozen production workflows (`01_Exterior_Hero` ~ `05_Slow_Walkthrough`).
- **FFprobe Video Auditor (`runtime/production_freeze/ffprobe_video_auditor.py`)**: Validates real MP4 container and stream metadata.
- **Human Acceptance Logger (`runtime/production_freeze/human_acceptance_logger.py`)**: Logs non-programmer architect user workflow timings and 0-code metrics.
- **Human Acceptance Report (`docs/V0.8.0_RC1_Human_Acceptance_Report.md`)**.
- **V0.8.0 RC1 Readiness Report (`docs/V0.8.0_RC1_Readiness_Report.md`)**: Answers 7 core readiness questions and authorizes V0.8.0 Architect Production Ready status.

## [0.7.8.4] - 2026-08-12

### Added
- **7 Production Validation Gates Suite (`runtime/validation/`)**.
