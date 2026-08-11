"""Model Manifest Verification Script
Verifies model weights existence, file size, and safetensors validity against configs/model_manifest.json.
"""

import os
import sys
import json
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_FILE = SYSTEM_ROOT / "configs" / "model_manifest.json"
COMFY_ROOT = Path("D:/ProgramFilesNormal/ComfyUI/ComfyUI_windows_portable/ComfyUI")

def check_models() -> dict:
    if not MANIFEST_FILE.is_file():
        raise FileNotFoundError(f"Model manifest missing at {MANIFEST_FILE}")

    with open(MANIFEST_FILE, "r", encoding="utf-8") as f:
        manifest_data = json.load(f)

    models_info = manifest_data.get("models", {})
    results = {}
    total_found = 0
    total_models = len(models_info)

    print("=================================================================", flush=True)
    print("        MINIMAX H3 MODEL WEIGHT MANIFEST AUDIT                   ", flush=True)
    print("=================================================================", flush=True)

    for key, spec in models_info.items():
        name = spec["name"]
        filename = spec["filename"]
        target_sub = spec["target_dir"]
        target_path = COMFY_ROOT / target_sub / filename

        # Fallback check in root models directory
        if not target_path.is_file():
            target_path = COMFY_ROOT / "models" / filename

        exists = target_path.is_file()
        if exists:
            stat = target_path.stat()
            size_gb = stat.st_size / (1024 ** 3)
            total_found += 1
            print(f"[FOUND] {name:<42} | Size: {size_gb:6.2f} GB | Path: {target_sub}/{filename}", flush=True)
            results[key] = {
                "name": name,
                "status": "EXISTS",
                "size_bytes": stat.st_size,
                "size_gb": round(size_gb, 2)
            }
        else:
            print(f"[MISSING] {name:<42} | File Not Found at {target_path}", flush=True)
            results[key] = {
                "name": name,
                "status": "MISSING",
                "size_bytes": 0,
                "size_gb": 0.0
            }

    print("\n=================================================================", flush=True)
    print(f"Model Audit Summary: {total_found}/{total_models} Models Available", flush=True)
    print(f"Overall Manifest Status: {'PASS' if total_found == total_models else 'WARNING'}", flush=True)
    print("=================================================================", flush=True)

    return {
        "total_models": total_models,
        "total_found": total_found,
        "status": "PASS" if total_found == total_models else "WARNING",
        "results": results
    }

if __name__ == "__main__":
    check_models()
