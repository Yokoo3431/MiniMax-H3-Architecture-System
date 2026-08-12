# Changelog

All notable changes to the `MiniMax-H3-Architecture-System` project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.8.0-rc2] - 2026-08-12

### Added
- **Architect Personal Workspace (`userdata/personal_workspace/`)**: Auto-initializes `input_images/`, `generated_prompts/`, `selected_workflows/`, `outputs/`, `reports/`.
- **One-Click Architect Launcher (`launcher/Start_MiniMax_H3_Architect.bat`)**: Environment check, ComfyUI server launch, API health polling, and browser auto-launch.
- **Workflow Catalog Manifest (`configs/workflow_catalog.json`)**: Formally maps and indexes 5 frozen workflows.
- **Official H3 Prompt Adapter (`runtime/prompt_bridge/official_h3_prompt_adapter.py`)**: Converts natural language into H3 structured prompts.
- **Architect Quick Start Guide (`docs/Architect_Quick_Start.md`)**.
- **V0.8.0 RC2 Technical Report (`docs/V0.8.0_RC2_Architect_Daily_Usage_Report.md`)**.
- **Daily Usage Unit Tests (`tests/test_architect_daily_usage.py`)**.

## [0.8.0-rc1] - 2026-08-12

### Added
- **Production Freeze Master Controller (`runtime/production_freeze/freeze_validator.py`)**.
