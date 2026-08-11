# Changelog

All notable changes to the `MiniMax-H3-Architecture-System` project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.7.1] - 2026-08-11

### Added
- **Architecture Prompt Skill Engine (`skills/architecture_prompt/`)**: Added `intent_parser.py`, `intent_schema.py`, `prompt_builder.py`, `prompt_engine.py`, vocabulary dictionary (`architecture`, `camera`, `lighting`, `material`), and YAML templates (`exterior`, `interior`, `aerial`, `night_transition`, `walkthrough`, `analysis`).
- **Architecture Intent Schema (`configs/architecture_intent_schema.json`)**: Formatted architectural generation requirements schema.
- **Architectural Vocabulary System (`configs/architecture_vocabulary.json`)**: Building types, spatial concepts, design actions, camera language, and lighting language.
- **Runtime Prompt Engine (`runtime/prompt_engine.py`)**: Natural language -> Intent JSON -> Prompt transformation engine.
- **30-Example Architecture Dataset (`configs/architecture_prompt_examples.json`)**: Categorized visualization & analysis dataset.
- **Automated Unit Tests (`tests/test_prompt_engine.py`, `test_intent_parser.py`, `test_workflow_matching.py`)**: 20 unit test cases passing 100%.

## [0.6.5] - 2026-08-11

### Verified & Audited
- **Infrastructure Freeze & Production Deployment Audit**: Completed 9-Phase Deployment Audit.
- **ComfyUI Version Compatibility Matrix**: Added `configs/comfyui_compatibility.json`.

## [0.6.0] - 2026-08-11

### Added
- **Automated Test Framework (`tests/`)**.
- **GitHub Actions CI/CD (`.github/workflows/`)**.

## [0.5.0] - 2026-08-11

### Added
- **Core & Userdata Separation**: `core/` and `userdata/`.
- **Modular Agent Engine (`runtime/`)**.
