# Changelog

All notable changes to the `MiniMax-H3-Architecture-System` project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.7.8.3] - 2026-08-12

### Added
- **5 Architect UAT Cases Manifest (`tests/assets/architect_cases/cases_manifest.json`)**: Exterior Hero, Day Night Transition, Material Detail, Drone Aerial, Slow Walkthrough.
- **Architect Intent Acceptance Auditor (`runtime/critic/architect_acceptance.py`)**: Audits user intent, prompt completeness, and workflow matching.
- **Architectural Fidelity Checker (`runtime/critic/architecture_fidelity_checker.py`)**: Checks structural geometry preservation and visual quality.
- **Architect Acceptance Unit Tests (`tests/test_architect_acceptance.py`)**: Runs all 5 UAT cases.
- **Architect Production Acceptance Report (`docs/V0.7.8.3_Architect_Production_Acceptance_Report.md`)**: Complete PASS assessment.

## [0.7.8.2] - 2026-08-12

### Added
- **Official Source Validator (`runtime/audit/official_source_validator.py`)**.
- **Model Runtime Load Test (`runtime/audit/model_runtime_test.py`)**.
