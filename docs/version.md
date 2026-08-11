# MiniMax H3 Architecture Infrastructure Version Specification

## Current Release: `v1.0.0`

### Specification
- **Semantic Version**: `1.0.0`
- **Architecture Standard**: MiniMax H3 FL2VA / Ref2VA Quantized Pipeline
- **ComfyUI Requirement**: >= 0.27.0
- **Supported Dtypes**: `int8_convrot` (DiT), `nvfp4_awq` (Qwen3-VL), `fp16` (Video VAE), `fp32` (Audio VAE)

### File Hash Integrity
- `1_建筑效果图_ImageToVideo.json`: Tracked under Git
- `2_建筑鸟瞰动画_AerialView.json`: Tracked under Git
- `3_建筑夜景灯光变化_NightTransition.json`: Tracked under Git
- `prompts/architectural_animation_prompts.json`: Tracked under Git

### Cross-Machine Sync Protocol
```bash
# On Machine A after editing a workflow:
git add workflows/ prompts/ configs/
git commit -m "feat(workflow): update sampling steps and camera pan prompts"
git push origin main

# On Machine B:
git pull origin main
scripts/setup_environment.bat
```
