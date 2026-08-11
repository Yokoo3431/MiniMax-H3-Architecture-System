# Production Testing & QA Framework Guide (`tests/`)

## Overview

The MiniMax H3 Architecture System includes an automated unit and integration testing framework using `unittest` and `pytest`.

---

## Test Modules Matrix

| Module | Target Subsystem | Critical Validation |
| :--- | :--- | :--- |
| `test_install.py` | Launcher Installer | Validates `Install_H3.bat` and directory structure |
| `test_update.py` | Updater Engine | Validates `Update_H3.bat` and sync manifest |
| `test_userdata_protection.py` | **UserData Isolation** | **Critical**: Verifies `userdata/` custom files are NEVER overwritten |
| `test_plugin_loading.py` | Plugin System | Validates `plugins/*/plugin.json` schemas |
| `test_workflow_registry.py` | Workflow Registry | Validates `workflow_registry.json` categories |
| `test_agent_router.py` | Agent Runtime | Validates `H3Orchestrator` execution pipeline |
| `test_hardware_adapter.py` | Hardware HAL | Validates `H3_LOW`, `H3_STANDARD`, `H3_PRO` profiles |

---

## Execution Command

```bash
python -m unittest discover -s tests -p "test_*.py"
```
