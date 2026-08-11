# MiniMax H3 Architecture System V0.3 One-Click Installation Guide

## For End-Users (Non-Technical)

### 1. Download Repository
Download or clone the project from GitHub:
```bash
git clone https://github.com/Yokoo3431/MiniMax-H3-Architecture-System.git
cd MiniMax-H3-Architecture-System
```

### 2. Run One-Click Installer
Double click `installer/install.bat`.
The installer will automatically:
- Audit Windows OS and NVIDIA Driver
- Detect GPU hardware profile (`H3_LOW` / `H3_STANDARD` / `H3_PRO`)
- Verify or install required custom nodes
- Link `extra_model_paths.yaml` into ComfyUI
- Synchronize workflows, prompt templates, and AI Agent skills

---

## For Developers & Power Users

### Manual Environment Verification
```bash
# Check hardware HAL profile
python hardware/detect_gpu.py

# Check model weights
python scripts/check_models.py

# Check custom nodes
python scripts/check_nodes.py
```
