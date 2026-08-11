# Changelog

All notable changes to the `MiniMax-H3-Architecture-System` project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.7.1.5] - 2026-08-11

### Added
- **MiniMax H3 Prompt Rule Engine (`skills/architecture_prompt/h3_rules/`)**: `geometry_lock.yaml`, `camera_motion.yaml`, `lighting_transition.yaml`, `architectural_material.yaml`, `negative_prompt.yaml`.
- **Architectural Knowledge Base (`configs/architecture_knowledge.json`)**: Architectural Concept -> Visual Meaning -> Prompt Expression database.
- **Knowledge Mapper Engine (`skills/architecture_prompt/knowledge_mapper.py`)**: Concept mapping engine.
- **Prompt Quality Evaluator (`runtime/prompt_quality.py`)**: Scores generated prompts on completeness & architectural accuracy (0-100).
- **100-Example Architecture Dataset (`configs/architecture_prompt_examples.json`)**: Expanded dataset with quality scores.
- **Automated Unit Tests (`tests/test_h3_rules.py`, `test_architecture_knowledge.py`, `test_prompt_quality.py`)**: 25 unit test cases passing 100%.

## [0.7.1] - 2026-08-11

### Added
- **Architecture Prompt Skill Engine (`skills/architecture_prompt/`)**.
- **Architecture Intent Schema (`configs/architecture_intent_schema.json`)**.
- **Architectural Vocabulary System (`configs/architecture_vocabulary.json`)**.

## [0.6.5] - 2026-08-11

### Verified & Audited
- **Infrastructure Freeze & Production Deployment Audit**: Completed 9-Phase Deployment Audit.
