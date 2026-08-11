# Changelog

All notable changes to the `MiniMax-H3-Architecture-System` project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.7.1.7] - 2026-08-11

### Added
- **Architecture Memory Schema (`configs/architecture_memory_schema.json`)**: Project info, intent, prompt data, evaluation fields.
- **Architecture Memory Database (`configs/architecture_memory.json`)**: 30 high-quality historical architectural case memories across 8 topologies.
- **Semantic Memory Retriever Engine (`skills/architecture_prompt/memory_retriever.py`)**: `retrieve_similar_case()`, `compare_architectural_intent()`, `suggest_prompt_strategy()`.
- **Quality Improvement Loop Generator (`runtime/prompt_quality.py`)**: `improvement_generator()` producing score, issues, and actionable suggestions.
- **Prompt Revision Integration (`runtime/feedback/prompt_revision.py`)**: Integrated memory revision strategy.
- **Automated Unit Tests (`tests/test_memory_retrieval.py`, `test_prompt_improvement.py`, `test_memory_schema.py`)**: 35 unit test cases passing 100%.

## [0.7.1.6] - 2026-08-11

### Added
- **Architectural Reasoning Schema (`configs/architecture_reasoning_schema.json`)**.
- **Architecture Reasoning Graph (`configs/architecture_reasoning_graph.json`)**.
- **5-Dimension Quality Evaluator (`runtime/prompt_quality.py`)**.

## [0.7.1.5] - 2026-08-11

### Added
- **MiniMax H3 Prompt Rule Engine (`skills/architecture_prompt/h3_rules/`)**.
- **Architectural Knowledge Base (`configs/architecture_knowledge.json`)**.
