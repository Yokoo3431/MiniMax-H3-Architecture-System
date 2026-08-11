# MiniMax H3 Automated Test Framework (`tests/`)

## Overview
This directory contains automated unit and integration tests for the MiniMax H3 Architecture System platform.

## Test Suites

1. `test_install.py`: Validates installation launcher script and directory structure.
2. `test_update.py`: Validates updater flow, migration rules, and sync manifest.
3. `test_userdata_protection.py`: Critical test ensuring `userdata/` custom assets are preserved across updates.
4. `test_plugin_loading.py`: Validates plugin discovery and `plugin.json` schema.
5. `test_workflow_registry.py`: Validates `workflow_registry.json` categories and workflow availability.
6. `test_agent_router.py`: Validates `H3Orchestrator` execution pipeline.
7. `test_hardware_adapter.py`: Validates HAL GPU profile selection (`H3_LOW`, `H3_STANDARD`, `H3_PRO`).

## Running Tests

Run with pytest:
```bash
pytest tests/
```

Or via Python unittest:
```bash
python -m unittest discover tests
```
