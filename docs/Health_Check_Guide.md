# Runtime Health Check System Guide

## Overview

The runtime health check system (`scripts/health_check.py`) performs self-diagnostics on hardware, models, nodes, and runtime components.

---

## Execution Command

```bash
python scripts/health_check.py
```

Outputs: `docs/runtime_health_report.md`

## Audit Criteria
- **Hardware**: GPU VRAM >= 8.0 GB (`H3_LOW` / `H3_STANDARD` / `H3_PRO`).
- **Models**: 4/4 weights verified (`minimax_h3_fl2va_pruned_int8_convrot.safetensors`, `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors`, `minimax_h3_video_vae_fp16.safetensors`, `minimax_h3_audio_vae_fp32.safetensors`).
- **Nodes**: 2/2 required custom nodes installed (`ComfyUI_RH_MinMaxH3`, `ComfyUI-VideoHelperSuite`).
