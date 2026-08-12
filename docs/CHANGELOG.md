# Changelog

All notable changes to the `MiniMax-H3-Architecture-System` project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.7.6] - 2026-08-12

### Added
- **Architectural Critic Core (`runtime/critic/`)**: `critic_schema.py`, `architecture_critic.py`, `failure_classifier.py`, `recommendation_engine.py`, `critic_pipeline.py`.
- **Memory Feedback Integration (`runtime/feedback/prompt_revision.py`)**: Upgraded to support Critic feedback iteration.
- **Model Registry Upgrade (`configs/model_registry.json`)**: Added `usage_history`, `quality_score`, `failure_cases`.
- **50 Critic Examples Dataset (`configs/critic_examples.json`)**: Architectural failure and fix dataset across 8 typologies.
- **Upgraded Runtime Orchestrator (`runtime/h3_orchestrator.py`)**: Added `critic_generation_result()` evaluation API.
- **Documentation (`docs/V0.7.6_Architectural_Critic_Report.md`, `V0.7.6_Critic_User_Guide.md`)**.
- **Automated Unit Tests (`tests/test_critic_schema.py`, `test_failure_classifier.py`, `test_recommendation_engine.py`, `test_critic_pipeline.py`)**: 66 unit test cases passing 100%.

## [0.7.5] - 2026-08-12

### Added
- **Architecture Acceleration Skill (`runtime/acceleration/`)**.
- **Model Ecosystem Registry (`configs/model_registry.json`)**.
