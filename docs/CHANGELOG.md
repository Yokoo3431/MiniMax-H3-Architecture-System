# Changelog

All notable changes to the `MiniMax-H3-Architecture-System` project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.7.1.6] - 2026-08-11

### Added
- **Architectural Reasoning Schema (`configs/architecture_reasoning_schema.json`)**: Design language, spatial character, material expression, emotional target.
- **Architecture Reasoning Graph (`configs/architecture_reasoning_graph.json`)**: Concept -> Meaning -> Visual -> Prompt Language graph.
- **Reasoning Engine (`skills/architecture_prompt/reasoning_engine.py`)**: Knowledge graph lookup engine.
- **Upgraded Intent Parser (`skills/architecture_prompt/intent_parser.py`)**: Extracted reasoning dimensions.
- **5-Dimension Quality Evaluator (`runtime/prompt_quality.py`)**: Scores `architectural_accuracy`, `camera_quality`, `lighting_quality`, `material_quality`, `constraint_compliance`.
- **Feedback Interface (`runtime/feedback/`)**: Added `feedback_schema.py` & `prompt_revision.py`.
- **50 Reasoning Examples Dataset (`configs/architecture_prompt_examples.json`)**.
- **Automated Unit Tests (`tests/test_reasoning_graph.py`, `test_intent_reasoning.py`, `test_feedback_interface.py`)**: 30 unit test cases passing 100%.

## [0.7.1.5] - 2026-08-11

### Added
- **MiniMax H3 Prompt Rule Engine (`skills/architecture_prompt/h3_rules/`)**.
- **Architectural Knowledge Base (`configs/architecture_knowledge.json`)**.
- **100-Example Dataset (`configs/architecture_prompt_examples.json`)**.

## [0.7.1] - 2026-08-11

### Added
- **Architecture Prompt Skill Engine (`skills/architecture_prompt/`)**.
