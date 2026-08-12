# Changelog

All notable changes to the `MiniMax-H3-Architecture-System` project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.7.8.4] - 2026-08-12

### Added
- **Production Ready Gate Manifest (`configs/production_ready_gate.json`)**: Production gate rules for V0.8.0 Architect Production Ready authorization.
- **Real Architect Outputs Dataset Package (`tests/assets/architect_outputs/real_cases_pack.json`)**: Contains input images, workflow JSONs, generated H3 prompts, MP4 metadata, and representative frames.
- **Production Gate Validator Engine (`runtime/critic/production_gate_validator.py`)**: Checks workflow execution, MP4 metadata, resolution ($\ge 1280 \times 720$), and structural deformation limits.
- **Production Gate Unit Tests (`tests/test_production_ready_gate.py`)**.
- **V0.7.8.4 Real Production Validation Report (`docs/V0.7.8.4_Real_Production_Validation_Report.md`)**: Evaluates and authorizes V0.8.0 Architect Production Ready status.

## [0.7.8.3] - 2026-08-12

### Added
- **5 Architect UAT Cases Manifest (`tests/assets/architect_cases/cases_manifest.json`)**.
