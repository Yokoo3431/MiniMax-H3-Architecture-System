# MiniMax H3 Cross-Machine Migration Guide

## Quick Deployment Steps for Machine B / Audit Environment

### Step 1: Clone Git Repository
```bash
git clone https://github.com/Yokoo3431/MiniMax-H3-Architecture-System.git
cd MiniMax-H3-Architecture-System
```

### Step 2: Configure Model Paths
Edit `configs/extra_model_paths.yaml` to point to local model storage drive (e.g. `D:\`, `E:\`, or `NAS` share path):

```yaml
comfyui_local:
  base_path: E:/ComfyUI/models
  diffusion_models: diffusion_models
  text_encoders: text_encoders
  vae: vae
```

### Step 3: Run Automated Environment Restoration
```cmd
scripts\setup_environment.bat
```

The script will automatically detect local GPU (`H3_LOW` / `H3_STANDARD` / `H3_PRO`), verify model and custom node integrity, and synchronize workflows into ComfyUI.
