# Multi-GPU Allocation & Degradation Strategy

## Overview

The MiniMax H3 Architecture System dynamically adapts to different hardware environments without requiring modifications to workflow JSON files.

---

## Hardware Profiles Matrix

| Parameter | `H3_LOW` (Entry) | `H3_STANDARD` (Standard) | `H3_PRO` (Professional) |
| :--- | :--- | :--- | :--- |
| **Target Hardware** | RTX 2060 Super 8GB / RTX 3060 12GB | RTX 5070 12GB / RTX 4070 12GB | RTX 5090 32GB / RTX 4090 24GB |
| **Min VRAM** | 6.0 GB - 10.0 GB | 10.0 GB - 16.0 GB | 16.0 GB - 96.0 GB |
| **Resolution** | **768 x 432** | **1280 x 720 (720p)** | **1920 x 1080 (1080p)** |
| **Denoising Steps** | 18 Steps | 25 Steps | 35 Steps |
| **FPS / Duration** | 20 FPS / 4.0s | 24 FPS / 4.0s | 24 FPS / 5.0s |
| **ComfyUI VRAM Flag** | `--lowvram` | `--lowvram` | `--normalvram` |
| **CPU Offload** | Enabled (`True`) | Enabled (`True`) | Disabled (`False`) |
| **Attention Kernel** | `--use-split-cross-attention` | `--use-split-cross-attention` | `--use-pytorch-cross-attention` |

---

## Degradation & Fail-Safe Mechanisms

1. **Automatic Tier Downgrade**: If VRAM allocation drops below 10GB during execution, HAL dynamically switches execution flags to `H3_LOW` to prevent Out-Of-Memory (OOM) crashes.
2. **Context Window Paging**: On 8GB cards, Qwen3-VL text encoder embeddings are offloaded to host RAM immediately after conditioning calculation.
