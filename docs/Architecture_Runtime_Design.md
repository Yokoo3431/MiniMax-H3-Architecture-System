# MiniMax H3 Architecture Runtime System Design (V0.2)

> **Document Version**: `v0.2.0`
> **System Name**: MiniMax H3 Architecture System Runtime

---

## 1. System Architecture Diagram

```
                        ┌─────────────────────────────────────┐
                        │     AI Agent (Antigravity / Codex / │
                        │        Hermes / OpenClaw)           │
                        └──────────────────┬──────────────────┘
                                           │  User Task & Render Image
                                           ▼
┌───────────────────────────────────────────────────────────────────────────┐
│                      MINIMAX H3 TASK ROUTER (V0.2)                        │
│                                                                           │
│   ┌───────────────────────┐             ┌─────────────────────────────┐   │
│   │ 1. Task Understanding │ ──────────> │ 2. Workflow Registry Match  │   │
│   └───────────────────────┘             └──────────────┬──────────────┘   │
│                                                        │                  │
│   ┌───────────────────────┐             ┌──────────────▼──────────────┐   │
│   │ 4. Hardware Adapter   │ <────────── │ 3. Prompt Composition       │   │
│   │    (HAL Profile)      │             └─────────────────────────────┘   │
│   └───────────┬───────────┘                                               │
└───────────────┼───────────────────────────────────────────────────────────┘
                │ Adaptive Payload (Resolution, Steps, VRAM Mode)
                ▼
┌───────────────────────────────────────────────────────────────────────────┐
│                     COMFYUI ENGINE BACKEND (0.27.0)                       │
│                                                                           │
│   [LoadImage] -> [Qwen3-VL NVFP4] -> [DiT INT8 ConvRot] -> [VAE FP16 Decode] │
└───────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Component Layer Specifications

1. **Hardware Abstraction Layer (HAL)**: `hardware/detect_gpu.py` queries CUDA & `nvidia-smi` to classify GPU capabilities into `H3_LOW` (8GB), `H3_STANDARD` (12GB), or `H3_PRO` (24GB+).
2. **Workflow Registry System**: `configs/workflow_registry.json` acts as the single source of truth for workflow metadata, input schema, and quality levels.
3. **Model & Node Manifest System**: `model_manifest.json` and `node_manifest.json` guarantee 100% hash parity and dependency consistency across machines.
4. **Agent Integration Layer**: `agent_h3_video_api.py` exposes a clean Python API and CLI for programmatic video generation.
