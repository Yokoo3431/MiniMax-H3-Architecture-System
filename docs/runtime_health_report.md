# MiniMax H3 System Runtime Health Audit Report

> **Audit Date**: 2026-08-11 17:24:59
> **System Version**: `0.6.0`
> **ComfyUI Requirement**: `0.27+`
> **Overall System Status**: **PASS**

---

## 1. Hardware Subsystem Health

| Parameter | Audited Value | Status |
| :--- | :--- | :---: |
| **GPU Model** | `NVIDIA GeForce RTX 5070` | **OK** |
| **VRAM Capacity** | `11.94 GB` (12226.56 MB) | **OK** |
| **CUDA / Driver** | `CUDA 13.0` | **OK** |
| **Matched Profile** | `H3_STANDARD` (`H3_STANDARD (Standard Tier)`) | **OK** |
| **Resolution Target** | `1280x720` | **OK** |

---

## 2. Model Weight Manifest Audit

- **Models Present**: `4/4`
- **Manifest Status**: **`PASS`**

| Model Name | Checksum / Status | File Size (GB) |
| :--- | :--- | :---: |
| `MiniMax H3 DiT Model (INT8 ConvRot)` | **EXISTS** | `19.53 GB` |
| `Qwen3-VL 32B Text Encoder (NVFP4 AWQ)` | **EXISTS** | `14.61 GB` |
| `MiniMax H3 24-Channel Video VAE (FP16)` | **EXISTS** | `4.85 GB` |
| `MiniMax H3 Audio VAE (FP32)` | **EXISTS** | `0.56 GB` |

---

## 3. Custom Node Dependency Audit

- **Nodes Installed**: `2/2`
- **Manifest Status**: **`PASS`**

| Node Name | Installation Path | Status |
| :--- | :--- | :---: |
| `ComfyUI_RH_MinMaxH3` | `D:\ProgramFilesNormal\ComfyUI\ComfyUI_windows_portable\ComfyUI\custom_nodes\ComfyUI_RH_MinMaxH3` | **INSTALLED** |
| `ComfyUI-VideoHelperSuite` | `D:\ProgramFilesNormal\ComfyUI\ComfyUI_windows_portable\ComfyUI\custom_nodes\ComfyUI-VideoHelperSuite` | **INSTALLED** |
| `ComfyUI-Manager` | `N/A` | **PARTIAL** |

---

## 4. Runtime & Compatibility Audit

- **Python Runtime**: `3.13.12`
- **Minimum VRAM Requirement**: `8.0 GB`
- **Supported GPU Tiers**: `H3_LOW` (8GB), `H3_STANDARD` (12GB), `H3_PRO` (24GB+)
- **Runtime Health Status**: **PASS**
