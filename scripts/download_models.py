"""MiniMax H3 Model Downloader Script
Detects missing model weights, calculates storage requirements, and downloads official weights from Hugging Face / Mirror.
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
    """Return free storage space in GB for given directory path."""
    try:
        total, used, free = shutil.disk_usage(target_dir if target_dir.exists() else target_dir.parent)
        return round(free / (1024 ** 3), 2)
    except Exception:
        return 0.0

def download_models(check_only: bool = False, use_mirror: bool = True):
    if not CONFIG_FILE.is_file():
        raise FileNotFoundError(f"Model download config missing at {CONFIG_FILE}")

    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        dl_config = json.load(f)

    base_url = dl_config["sources"]["mirror_cn"] if use_mirror else dl_config["sources"]["official"]
    models = dl_config.get("models", {})
    
    missing_models = []
    total_needed_gb = 0.0

    print("=================================================================", flush=True)
    print("      MINIMAX H3 MODEL WEIGHTS AUTOMATED DOWNLOADER             ", flush=True)
    print("=================================================================", flush=True)
    print(f"Download Source Endpoint : {base_url}", flush=True)

    for key, spec in models.items():
        name = spec["name"]
        filename = spec["filename"]
        target_sub = spec["target_dir"]
        size_gb = spec["size_gb"]
        target_file = COMFY_ROOT / target_sub / filename

        if not target_file.is_file() and not (COMFY_ROOT / "models" / filename).is_file():
            missing_models.append((key, spec))
            total_needed_gb += size_gb
            print(f"[MISSING] {name:<42} | Size: {size_gb:5.2f} GB | Required", flush=True)
        else:
            print(f"[FOUND]   {name:<42} | Size: {size_gb:5.2f} GB | Verified", flush=True)

    free_gb = check_disk_storage(COMFY_ROOT)
    print(f"\nTarget Drive Free Storage : {free_gb} GB", flush=True)
    print(f"Total Missing Models Size : {total_needed_gb:.2f} GB", flush=True)

    if not missing_models:
        print("\n[SUCCESS] All MiniMax H3 model weights are already present! No download required.", flush=True)
        print("=================================================================", flush=True)
        return

    if check_only:
        print("\n[CHECK ONLY] Storage check complete. Run without --check-only to download missing files.", flush=True)
        print("=================================================================", flush=True)
        return

    if free_gb < total_needed_gb:
        print(f"\n[ERROR] Insufficient disk space! Required: {total_needed_gb:.2f} GB, Available: {free_gb} GB.", flush=True)
        print("Please free up space or adjust extra_model_paths.yaml to target a larger drive.", flush=True)
        print("=================================================================", flush=True)
        return

    print("\nStarting Download for Missing Models...", flush=True)
    for key, spec in missing_models:
        filename = spec["filename"]
        target_sub = spec["target_dir"]
        rel_url = spec.get("relative_url", filename)
        url = f"{base_url}/{rel_url}"
        dest = COMFY_ROOT / target_sub / filename
        dest.parent.mkdir(parents=True, exist_ok=True)

        print(f"--> Downloading {filename} from {url}...", flush=True)
        try:
            # Demonstration urllib fetch
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req) as resp, open(dest, "wb") as out_f:
                shutil.copyfileobj(resp, out_f)
            print(f"    [SUCCESS] Downloaded {filename}", flush=True)
        except Exception as e:
            print(f"    [DOWNLOAD NOTICE] Remote fetch error: {e}", flush=True)
            print(f"    You can download manually from: {url}", flush=True)

    print("\n=================================================================", flush=True)
    print("           MODEL DOWNLOAD PROCEDURE COMPLETED                     ", flush=True)
    print("=================================================================", flush=True)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MiniMax H3 Model Downloader")
    parser.add_argument("--check-only", action="store_true", help="Only check missing models and disk storage without downloading")
    parser.add_argument("--official-hf", action="store_true", help="Use official huggingface.co instead of mirror_cn")

    args = parser.parse_args()
    download_models(check_only=args.check_only, use_mirror=not args.official_hf)
