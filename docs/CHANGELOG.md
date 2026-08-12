# Changelog

All notable changes to the `MiniMax-H3-Architecture-System` project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.8.0-rc3.2] - 2026-08-12

### Reconstructed / Fixed
- **Complete Removal of RunningHub Node Dependencies**: Purged all RunningHub nodes (`RHMiniMaxH3ModelLoader`, `RHMiniMaxH3FL2VA`, `RHMiniMaxH3VAELoader`, `RHMiniMaxH3T2VATextEncode`) across all 5 production workflows.
- **Native ComfyUI Nodes Reconstruction (`workflows/`)**: Reconstructed `01_Exterior_Hero.json` ~ `05_Slow_Walkthrough.json` using native ComfyUI nodes (`UNETLoader`, `CLIPLoader`, `VAELoader`, `CLIPTextEncode`, `KSampler`, `VAEDecode`, `VHS_VideoCombine`).
- **Target Deployment & Archive (`scripts/deploy_workflows.py`)**: Deploys to `ComfyUI/user/default/workflows/ARCHITECTURE_PRODUCTION/` and archives old workflows into `ARCHIVE_RC2/`.
- **Health Check Polling Launcher (`launcher/Start_MiniMax_H3_Architect.bat`)**: Replaced fixed browser delays with live API health polling on `http://127.0.0.1:8188/system_stats`.
- **FFmpeg & FFprobe Auto-Configuration**.
- **V0.8.0 RC3.2 Technical Report (`docs/V0.8.0_RC3.2_Runtime_Reconstruction_Report.md`)**.
- **Native Reconstruction Unit Tests (`tests/test_v080_rc32_native_reconstruction.py`)**.

## [0.8.0-rc3.1] - 2026-08-12

### Added / Fixed
- **Launcher Git Auto-Detection (`launcher/Start_MiniMax_H3_Architect.bat`)**.
