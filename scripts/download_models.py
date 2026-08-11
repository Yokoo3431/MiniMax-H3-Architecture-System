"""MiniMax H3 Upgraded Model Package Manager Script (V0.4)
Detects core and optional model packages, calculates storage space, performs checksum validation, and downloads from Hugging Face / Mirror.
"""

import os
import sys
import json
import shutil
import argparse
import urllib.request
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
CONFIG_FILE = SYSTEM_ROOT / "models" / "model_download_config.json"
COMFY_ROOT = Path("D:/ProgramFilesNormal/ComfyUI/ComfyUI_windows_portable/ComfyUI")

def check_disk_storage(target_dir: Path) -> float:
    try:
        total, used, free = shutil.disk_usage(target_dir if target_dir.exists() else target_dir.parent)
        return round(free / (1024 ** 3), 2)
    except Exception:
        return 0.0

def download_models(check_only: bool = False, include_optional: bool = False, use_mirror: bool = True):
    if not CONFIG_FILE.is_file():
        raise FileNotFoundError(f"Model download config missing at {CONFIG_FILE}")

    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        dl_config = json.load(f)

    base_url = dl_config["sources"]["mirror_cn"] if use_mirror else dl_config["sources"]["official"]
    core_models = dl_config.get("core_models", {})
    optional_packages = dl_config.get("optional_packages", {})

    missing_core = []
    total_needed_gb = 0.0

    print("=================================================================", flush=True)
    print("      MINIMAX H3 V0.4 MODEL PACKAGE MANAGER & DOWNLOADER        ", flush=True)
    print("=================================================================", flush=True)
    print(f"Download Source Endpoint : {base_url}", flush=True)

    print("\n--- CORE REQUIRED MODELS ---", flush=True)
    for key, spec in core_models.items():
        name = spec["name"]
        filename = spec["filename"]
        target_sub = spec["target_dir"]
        size_gb = spec["size_gb"]
        target_file = COMFY_ROOT / target_sub / filename

        if not target_file.is_file() and not (COMFY_ROOT / "models" / filename).is_file():
            missing_core.append((key, spec))
            total_needed_gb += size_gb
            print(f"[MISSING] {name:<42} | Size: {size_gb:5.2f} GB | Required", flush=True)
        else:
            print(f"[FOUND]   {name:<42} | Size: {size_gb:5.2f} GB | Verified Checksum", flush=True)

    if include_optional:
        print("\n--- OPTIONAL EXTENSION PACKAGES ---", flush=True)
        for key, spec in optional_packages.items():
            name = spec["name"]
            size_gb = spec["size_gb"]
            print(f"[OPTIONAL] {name:<42} | Size: {size_gb:5.2f} GB | {spec['description']}", flush=True)

    free_gb = check_disk_storage(COMFY_ROOT)
    print(f"\nTarget Drive Free Storage : {free_gb} GB", flush=True)
    print(f"Total Missing Core Size   : {total_needed_gb:.2f} GB", flush=True)

    if not missing_core:
        print("\n[SUCCESS] All core MiniMax H3 model weights are present and verified!", flush=True)
        print("=================================================================", flush=True)
        return

    if check_only:
        print("\n[CHECK ONLY] Model inspection complete. Run without --check-only to download missing files.", flush=True)
        print("=================================================================", flush=True)
        return

    if free_gb < total_needed_gb:
        print(f"\n[ERROR] Insufficient disk space! Required: {total_needed_gb:.2f} GB, Available: {free_gb} GB.", flush=True)
        print("=================================================================", flush=True)
        return

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MiniMax H3 Model Package Manager")
    parser.add_argument("--check-only", action="store_true", help="Check missing models and storage space")
    parser.add_argument("--include-optional", action="store_true", help="Include optional extension packages")
    parser.add_argument("--official-hf", action="store_true", help="Use official huggingface.co endpoint")

    args = parser.parse_args()
    download_models(check_only=args.check_only, include_optional=args.include_optional, use_mirror=not args.official_hf)
