# Changelog

All notable changes to the `MiniMax-H3-Architecture-System` project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.6.5] - 2026-08-11

### Verified & Audited
- **Infrastructure Freeze & Production Deployment Audit**: Completed 9-Phase Deployment & Migration Audit (`scripts/audit_deployment.py` -> `docs/V0.6.5_Deployment_Audit_Report.md`).
- **Fresh PC Installation Audit**: Verified `launcher/Install_H3.bat` (`docs/deployment_install_report.md`).
- **Model Path Decoupling Audit**: Verified 40GB model weight mapping across `D:\`, `E:\`, and `NAS` paths (`docs/model_migration_report.md`).
- **Userdata Protection & Update Sync Audit**: Verified `launcher/Update_H3.bat` core update and data isolation (`docs/userdata_protection_report.md`).
- **ComfyUI Version Compatibility Matrix**: Added `configs/comfyui_compatibility.json` defining stable (`0.27.x`) and custom node versions.
- **Release Archive Package**: Generated `release/MiniMax-H3-Architecture-System-v0.6.5.zip` (88 files, 0.08 MB).
- **V0.7 Transition Ready**: Production deployment readiness confirmed **PASS**.

## [0.6.0] - 2026-08-11

### Added
- **Automated Test Framework (`tests/`)**: 7 test modules / 12 unit tests passing 100%.
- **GitHub Actions CI/CD (`.github/workflows/`)**: `test.yml`, `release.yml`, `diagnostic.yml`.
- **Runtime Health Check System (`scripts/health_check.py`)**: `docs/runtime_health_report.md`.
- **Compatibility Matrix (`configs/compatibility_matrix.json`)**.

## [0.5.0] - 2026-08-11

### Added
- **Core & Userdata Separation**: `core/` and `userdata/`.
- **Modular Agent Engine (`runtime/`)**.
- **Plugin Architecture (`plugins/`)**.

## [0.4.0] - 2026-08-11

### Added
- **Launcher Suite (`launcher/`)**.
- **Asset Lifecycle Sync (`sync/`)**.

## [0.3.0] - 2026-08-11

### Added
- **One-Click Installer & Updater**.
