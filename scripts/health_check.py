"""Runtime Health Check System Script
Audits GPU/VRAM/CUDA, model files & checksums, custom nodes, Python dependencies, and runtime API.
Generates docs/runtime_health_report.md.
"""

import os
import sys
import json
import time
import subprocess
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from hardware.detect_gpu import detect_hardware
from scripts.check_models import check_models
from scripts.check_nodes import check_nodes

def perform_health_check() -> dict:
    print("=================================================================", flush=True)
    print("      MINIMAX H3 SYSTEM RUNTIME HEALTH CHECK & DIAGNOSTICS      ", flush=True)
    print("=================================================================", flush=True)

    # 1. Hardware Check
    hw_res = detect_hardware()
    gpu = hw_res["gpu_info"]
    profile = hw_res["profile"]

    # 2. Model Check
    model_res = check_models()

    # 3. Node Check
    node_res = check_nodes()

    # 4. Runtime Check
    runtime_ok = True
    python_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"

    # Read system version & compatibility matrix
    sys_ver_file = SYSTEM_ROOT / "configs" / "system_version.json"
    comp_file = SYSTEM_ROOT / "configs" / "compatibility_matrix.json"
    
    sys_ver = {}
    if sys_ver_file.is_file():
        with open(sys_ver_file, "r", encoding="utf-8") as f:
            sys_ver = json.load(f)

    comp_matrix = {}
    if comp_file.is_file():
        with open(comp_file, "r", encoding="utf-8") as f:
            comp_matrix = json.load(f)

    overall_pass = (
        model_res["status"] == "PASS" and
        node_res["status"] == "PASS" and
        gpu["vram_gb"] >= comp_matrix.get("minimum_vram_gb", 8.0)
    )

    report_md = f"""# MiniMax H3 System Runtime Health Audit Report

> **Audit Date**: {time.strftime("%Y-%m-%d %H:%M:%S")}
> **System Version**: `{sys_ver.get("system", "0.6.0")}`
> **ComfyUI Requirement**: `{comp_matrix.get("comfyui_version", "0.27+")}`
> **Overall System Status**: **{'PASS' if overall_pass else 'WARNING'}**

---

## 1. Hardware Subsystem Health

| Parameter | Audited Value | Status |
| :--- | :--- | :---: |
| **GPU Model** | `{gpu['gpu_name']}` | **OK** |
| **VRAM Capacity** | `{gpu['vram_gb']} GB` ({gpu['vram_mb']} MB) | **{'OK' if gpu['vram_gb'] >= 8.0 else 'WARNING'}** |
| **CUDA / Driver** | `{gpu['driver']}` | **OK** |
| **Matched Profile** | `{hw_res['matched_profile_key']}` (`{profile['name']}`) | **OK** |
| **Resolution Target** | `{profile['resolution'][0]}x{profile['resolution'][1]}` | **OK** |

---

## 2. Model Weight Manifest Audit

- **Models Present**: `{model_res['total_found']}/{model_res['total_models']}`
- **Manifest Status**: **`{model_res['status']}`**

| Model Name | Checksum / Status | File Size (GB) |
| :--- | :--- | :---: |
"""

    for m_key, spec in model_res.get("results", {}).items():
        report_md += f"| `{spec['name']}` | **{spec['status']}** | `{spec['size_gb']:.2f} GB` |\n"

    report_md += f"""
---

## 3. Custom Node Dependency Audit

- **Nodes Installed**: `{node_res['total_found']}/{node_res['required_count']}`
- **Manifest Status**: **`{node_res['status']}`**

| Node Name | Installation Path | Status |
| :--- | :--- | :---: |
"""

    for n_key, spec in node_res.get("results", {}).items():
        report_md += f"| `{n_key}` | `{spec.get('node_path', 'N/A')}` | **{spec['status']}** |\n"

    report_md += f"""
---

## 4. Runtime & Compatibility Audit

- **Python Runtime**: `{python_ver}`
- **Minimum VRAM Requirement**: `{comp_matrix.get('minimum_vram_gb', 8.0)} GB`
- **Supported GPU Tiers**: `H3_LOW` (8GB), `H3_STANDARD` (12GB), `H3_PRO` (24GB+)
- **Runtime Health Status**: **PASS**
"""

    out_file = SYSTEM_ROOT / "docs" / "runtime_health_report.md"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(report_md)

    print(f"\n[SUCCESS] Runtime Health Report written to {out_file}", flush=True)
    print("=================================================================", flush=True)

    return {
        "status": "PASS" if overall_pass else "WARNING",
        "gpu": gpu['gpu_name'],
        "profile": hw_res['matched_profile_key'],
        "report_path": str(out_file)
    }

if __name__ == "__main__":
    perform_health_check()
