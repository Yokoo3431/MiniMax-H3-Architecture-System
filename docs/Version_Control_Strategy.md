# Version Control & Asset Sync Strategy

## Git Tracking Principles
1. **Code & Config Only**: Workflows, prompts, skills, HAL configs, scripts, and documentation are 100% version-controlled.
2. **No Model Weights in Git**: 40GB model weights are excluded via `.gitignore` and handled via `extra_model_paths.yaml` or `download_models.py`.
3. **No Generated Outputs in Git**: `.mp4` video files are kept in local `ComfyUI/output`.
