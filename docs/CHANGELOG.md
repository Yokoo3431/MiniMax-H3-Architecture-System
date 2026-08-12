# Changelog

All notable changes to the `MiniMax-H3-Architecture-System` project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.7.8.4] - 2026-08-12

### Added
- **100-Point Architect Quality Scoring System (`configs/architect_quality_score.json`)**: Production threshold $\ge$ 85/100.
- **Architect Outputs Dataset Manifest (`tests/assets/architect_outputs/outputs_manifest.json`)**.
- **Visual Quality Validator Engine (`runtime/critic/visual_quality_validator.py`)**: Audits Geometry (30), Camera (20), Material (20), Lighting (15), Presentation (15).
- **Visual Quality Unit Tests (`tests/test_visual_quality_validation.py`)**.
- **Architectural Visual Quality Report (`docs/V0.7.8.4_Architectural_Visual_Quality_Report.md`)**: Complete PASS assessment.

## [0.7.8.3] - 2026-08-12

### Added
- **5 Architect UAT Cases Manifest (`tests/assets/architect_cases/cases_manifest.json`)**.
- **Architect Intent Acceptance Auditor (`runtime/critic/architect_acceptance.py`)**.
