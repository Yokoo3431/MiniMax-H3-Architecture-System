# Changelog

All notable changes to the `MiniMax-H3-Architecture-System` project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.0] - 2026-08-11

### Added
- **Launcher Suite (`launcher/`)**: Added desktop launchers `Install_H3.bat` (10-stage fresh PC setup), `Start_H3.bat` (Runtime WebUI launcher), `Update_H3.bat` (Asset updater), and `Diagnose_H3.bat` (System diagnostic generator).
- **Asset Lifecycle Management (`sync/`)**: Added `asset_registry.json`, `sync_manifest.json`, and `migration_rules.json` tracking asset versions, authors, updated dates, and safe migration rules.
- **Categorized Workflow Registry (`configs/workflow_registry.json`)**: Extended registry categorized into **Architecture Visualization** (ImageToVideo, AerialView, NightTransition, CameraOrbit, Walkthrough) and **Architecture Analysis** (Massing Evolution, Circulation, Exploded Axon, Structure, Envelope Analysis).
- **Model Package Manager Upgrade (`scripts/download_models.py`)**: Added support for optional packages (LoRA Pack, Camera Motion Pack, Lighting Enhancement Pack) and storage checks.
- **Diagnostic Inspection (`scripts/generate_diagnostics.py`)**: Automated system diagnostics writing `docs/diagnostic_report.md`.
- **GitHub Release Strategy (`docs/GitHub_Release_Strategy.md`)**: Roadmap defining v0.4.0, v0.5.0, and v1.0.0.

## [0.3.0] - 2026-08-11

### Added
- **One-Click Installer & Updater**: Added `installer/install.bat` and `updater/update.bat`.
- **Model Downloader**: Added `scripts/download_models.py`.

## [0.2.0] - 2026-08-11

### Added
- **Hardware Abstraction Layer (HAL)**: Added `hardware/detect_gpu.py` (`H3_LOW`, `H3_STANDARD`, `H3_PRO`).
- **Model & Node Manifests**: Added `model_manifest.json` and `node_manifest.json`.

## [1.0.0] - 2026-08-11

### Added
- **Asset Separation**: Isolated `workflows/`, `prompts/`, `skills/`, `configs/`, `scripts/`, and `docs/`.
