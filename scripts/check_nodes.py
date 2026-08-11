"""Custom Node Manifest Verification Script
Verifies custom nodes installation and component consistency against configs/node_manifest.json.
"""

import os
import sys
import json
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_FILE = SYSTEM_ROOT / "configs" / "node_manifest.json"
COMFY_ROOT = Path("D:/ProgramFilesNormal/ComfyUI/ComfyUI_windows_portable/ComfyUI")

def check_nodes() -> dict:
    if not MANIFEST_FILE.is_file():
        raise FileNotFoundError(f"Node manifest missing at {MANIFEST_FILE}")

    with open(MANIFEST_FILE, "r", encoding="utf-8") as f:
        manifest_data = json.load(f)

    nodes_info = manifest_data.get("nodes", {})
    results = {}
    total_found = 0
    required_count = 0

    print("=================================================================", flush=True)
    print("        MINIMAX H3 CUSTOM NODES MANIFEST AUDIT                   ", flush=True)
    print("=================================================================", flush=True)

    for key, spec in nodes_info.items():
        name = spec["name"]
        target_sub = spec["target_dir"]
        is_required = spec.get("required", True)
        if is_required:
            required_count += 1

        node_path = COMFY_ROOT / target_sub
        exists = node_path.is_dir()

        if exists:
            # Check key components
            missing_components = []
            for comp in spec.get("key_components", []):
                if not (node_path / comp).exists():
                    missing_components.append(comp)

            if not missing_components:
                total_found += 1
                print(f"[INSTALLED] {name:<30} | Status: OK | Path: {target_sub}", flush=True)
                results[key] = {"status": "INSTALLED", "node_path": str(node_path)}
            else:
                print(f"[PARTIAL]   {name:<30} | Missing components: {missing_components}", flush=True)
                results[key] = {"status": "PARTIAL", "missing": missing_components}
        else:
            status_label = "[MISSING] " if is_required else "[OPTIONAL]"
            print(f"{status_label}  {name:<30} | Directory not found", flush=True)
            results[key] = {"status": "MISSING"}

    print("\n=================================================================", flush=True)
    print(f"Node Audit Summary: {total_found}/{required_count} Required Custom Nodes Installed", flush=True)
    print(f"Overall Manifest Status: {'PASS' if total_found >= required_count else 'WARNING'}", flush=True)
    print("=================================================================", flush=True)

    return {
        "required_count": required_count,
        "total_found": total_found,
        "status": "PASS" if total_found >= required_count else "WARNING",
        "results": results
    }

if __name__ == "__main__":
    check_nodes()
