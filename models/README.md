# MiniMax H3 Model Weights Deployment Guide

> [!IMPORTANT]
> **Weight Storage Policy**: Model weights (~39.55 GB total) are **NOT stored directly in GitHub** due to repository size limits.
> Instead, they are downloaded from official Hugging Face repositories using `scripts/download_models.py` or configured via `configs/extra_model_paths.yaml`.

---

## 1. Official Model Weight Sources

- **Official Hugging Face Repository**: [MiniMaxAI/MiniMax-H3](https://huggingface.co/MiniMaxAI/MiniMax-H3)
- **High-Speed Mirror (China)**: [hf-mirror.com/MiniMaxAI/MiniMax-H3](https://hf-mirror.com/MiniMaxAI/MiniMax-H3)

---

## 2. Required Weights & File Sizes

| Weight File | Target Directory | Size | Precision | Purpose |
| :--- | :--- | :---: | :---: | :--- |
| `minimax_h3_fl2va_pruned_int8_convrot.safetensors` | `models/diffusion_models` | 19.53 GB | `INT8 ConvRot` | DiT Transformer Denoising |
| `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors` | `models/text_encoders` | 14.61 GB | `NVFP4 AWQ` | Text & Image Encoder |
| `minimax_h3_video_vae_fp16.safetensors` | `models/vae` | 4.85 GB | `FP16` | 24-Channel Video VAE Decode |
| `minimax_h3_audio_vae_fp32.safetensors` | `models/vae` | 0.56 GB | `FP32` | Audio VAE Decode |

---

## 3. Automated Download Command

Run the python downloader script:

```bash
python scripts/download_models.py
```

To test storage checks without downloading:
```bash
python scripts/download_models.py --check-only
```
