"""Hardware Abstraction Layer (HAL) - GPU Auto Detection & Profiler
Detects local GPU hardware, VRAM capacity, CUDA capabilities, and matches hardware profile (H3_LOW / H3_STANDARD / H3_PRO).
"""

import os
import sys
import json
import subprocess
import argparse
from pathlib import Path

HARDWARE_DIR = Path(__file__).resolve().parent
PROFILES_FILE = HARDWARE_DIR / "hardware_profiles.json"
MACHINE_PROFILE_FILE = HARDWARE_DIR / "machine_profile.json"

def query_nvidia_smi() -> dict:
    """Query nvidia-smi for GPU name and total VRAM."""
    try:
        res = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader,nounits"],
            text=True
        ).strip()
        if res:
            first_line = res.splitlines()[0]
            parts = [x.strip() for x in first_line.split(",")]
            gpu_name = parts[0]
            vram_mb = float(parts[1])
            driver = parts[2] if len(parts) > 2 else "Unknown"
            return {
                "gpu_name": gpu_name,
                "vram_mb": vram_mb,
                "vram_gb": round(vram_mb / 1024.0, 2),
                "driver": driver,
                "detected_via": "nvidia-smi"
            }
    except Exception:
        pass
    return None

def query_pytorch_cuda() -> dict:
    """Query PyTorch CUDA subsystem if available."""
    try:
        import torch
        if torch.cuda.is_available():
            gpu_name = torch.cuda.get_device_name(0)
            vram_bytes = torch.cuda.get_device_properties(0).total_memory
            vram_gb = round(vram_bytes / (1024 ** 3), 2)
            return {
                "gpu_name": gpu_name,
                "vram_mb": round(vram_bytes / (1024 ** 2), 2),
                "vram_gb": vram_gb,
                "driver": f"CUDA {torch.version.cuda}",
                "detected_via": "pytorch"
            }
    except Exception:
        pass
    return None

def match_hardware_profile(gpu_info: dict, profiles_data: dict) -> tuple[str, dict]:
    """Match GPU capabilities against H3_LOW, H3_STANDARD, and H3_PRO tiers."""
    vram_gb = gpu_info["vram_gb"]
    profiles = profiles_data.get("profiles", {})

    if vram_gb < 10.0:
        profile_key = "H3_LOW"
    elif vram_gb < 16.0:
        profile_key = "H3_STANDARD"
    else:
        profile_key = "H3_PRO"

    selected_profile = profiles.get(profile_key, profiles.get("H3_STANDARD", {}))
    return profile_key, selected_profile

def detect_hardware(simulate_name: str = None, simulate_vram_gb: float = None) -> dict:
    """Main hardware detection function."""
    with open(PROFILES_FILE, "r", encoding="utf-8") as f:
        profiles_data = json.load(f)

    if simulate_name and simulate_vram_gb is not None:
        gpu_info = {
            "gpu_name": simulate_name,
            "vram_mb": round(simulate_vram_gb * 1024.0, 2),
            "vram_gb": simulate_vram_gb,
            "driver": "Simulated Driver",
            "detected_via": "simulation"
        }
    else:
        gpu_info = query_pytorch_cuda() or query_nvidia_smi() or {
            "gpu_name": "Generic CPU / Unknown GPU",
            "vram_mb": 4096.0,
            "vram_gb": 4.0,
            "driver": "N/A",
            "detected_via": "fallback"
        }

    profile_key, matched_profile = match_hardware_profile(gpu_info, profiles_data)

    result = {
        "system_name": "MiniMax H3 Machine Profile",
        "gpu_info": gpu_info,
        "matched_profile_key": profile_key,
        "profile": matched_profile
    }

    # Save to machine_profile.json if not simulation
    if not simulate_name:
        with open(MACHINE_PROFILE_FILE, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

    return result

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MiniMax H3 Hardware Detector")
    parser.add_argument("--simulate-gpu", default=None, help="Simulate a GPU model name, e.g. 'NVIDIA GeForce RTX 2060 Super'")
    parser.add_argument("--simulate-vram", type=float, default=None, help="Simulate VRAM size in GB, e.g. 8.0")

    args = parser.parse_args()

    res = detect_hardware(simulate_name=args.simulate_gpu, simulate_vram_gb=args.simulate_vram)
    print("=================================================================")
    print("     MINIMAX H3 HARDWARE ABSTRACTION LAYER (HAL) AUDIT          ")
    print("=================================================================")
    print(f"Detected GPU       : {res['gpu_info']['gpu_name']}")
    print(f"VRAM Capacity      : {res['gpu_info']['vram_gb']} GB ({res['gpu_info']['vram_mb']} MB)")
    print(f"Detection Method   : {res['gpu_info']['detected_via']}")
    print(f"Matched Profile    : {res['matched_profile_key']} ({res['profile']['name']})")
    print(f"Target Resolution  : {res['profile']['resolution'][0]}x{res['profile']['resolution'][1]}")
    print(f"Target Steps / FPS : {res['profile']['steps']} steps / {res['profile']['fps']} fps")
    print(f"ComfyUI Flag       : {res['profile']['vram_allocation_mode']}")
    print("=================================================================")
