# MiniMax H3 Production Runtime Architecture (V0.5)

> **Document Version**: `v0.5.0`
> **System Target**: Production-Grade Extensible AI Architecture Video Platform

---

## 1. System Architecture Diagram

```
                        ┌─────────────────────────────────────┐
                        │     AI Agent (Antigravity / Codex / │
                        │        Hermes / OpenClaw)           │
                        └──────────────────┬──────────────────┘
                                           │  User Task & Rendering Image
                                           ▼
┌───────────────────────────────────────────────────────────────────────────┐
│                    MINIMAX H3 RUNTIME ENGINE (V0.5)                       │
│                                                                           │
│   [TaskPlanner] ----> [WorkflowSelector] ----> [PromptComposer]           │
│                             │                                             │
│                             ▼                                             │
│                     [HardwareAdapter] ----> [ComfyExecutor]               │
└─────────────────────────────┬─────────────────────────────────────────────┘
                              │ Payload Execution
                              ▼
┌───────────────────────────────────────────────────────────────────────────┐
│                     COMFYUI BACKEND ENGINE (0.27.0)                       │
│                                                                           │
│   [LoadImage] -> [Qwen3-VL NVFP4] -> [DiT INT8 ConvRot] -> [VAE FP16 Decode] │
└───────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Directory Isolation Architecture

- **`core/`**: Version-controlled core system assets.
- **`userdata/`**: Protected user assets (custom workflows, prompts, models, configs, outputs). Guaranteed never to be overwritten during updates.
- **`runtime/`**: Modular Python Agent execution engine.
- **`plugins/`**: Third-party plugin bundles (`architecture_visualization`, `architecture_analysis`).
- **`release/`**: Automated zip packager (`MiniMax-H3-Architecture-System-v0.5.0.zip`).
