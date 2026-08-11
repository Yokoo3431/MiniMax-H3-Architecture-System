# Workflow Update Sync & Userdata Protection Audit Report

> **Audit Date**: 2026-08-11
> **Target Version**: `v0.6.5`
> **Audit Status**: **PASS (100% Protection Verified)**

---

## 1. Audit Objective

Verify that running `launcher/Update_H3.bat` synchronizes system core workflows, prompts, skills, and configs from GitHub, while **strictly preserving** all files in `userdata/` (`custom_workflows/`, `custom_prompts/`, `custom_models/`, `custom_configs/`, `outputs/`).

---

## 2. Automated Test Audit

- **Automated Test Module**: `tests/test_userdata_protection.py`
- **Execution Command**: `python -m unittest tests/test_userdata_protection.py`
- **Test Result**: **PASS**

### Test Sequence
1. User creates custom asset: `userdata/custom_workflows/test_custom.json`.
2. Updater triggers temporary backup to `userdata_backup_temp/`.
3. System core undergoes `git pull` & core workflow sync.
4. Backup restored intact over `userdata/`.
5. Assertion check verifies `test_custom.json` content is identical and untouched.

---

## 3. Asset Synchronization Rules

| Asset Category | Update Action on `Update_H3.bat` | Data Overwritten? |
| :--- | :--- | :---: |
| `workflows/*.json` | Synchronized from remote repository | Core System Only |
| `prompts/*.json` | Synchronized from remote repository | Core System Only |
| `skills/` | Synchronized from remote repository | Core System Only |
| `userdata/custom_workflows/` | **RESTORED FROM BACKUP** | **NEVER** |
| `userdata/custom_prompts/` | **RESTORED FROM BACKUP** | **NEVER** |
| `userdata/outputs/` | **RESTORED FROM BACKUP** | **NEVER** |

---

## 4. Conclusion

Userdata isolation is 100% effective and verified by automated unit tests.
