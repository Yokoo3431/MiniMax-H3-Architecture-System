"""Workflow Deployer & Validator Script for ComfyUI Integration (V0.8.0 RC3.1).
Deploys 5 production workflows to ComfyUI's native workflow directory, archives old RC2 workflows, and validates node completeness.
"""

import sys
import json
import shutil
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = SYSTEM_ROOT / "configs"
REPORT_FILE = CONFIG_DIR / "workflow_validation_report.json"
REPO_WORKFLOWS_DIR = SYSTEM_ROOT / "workflows"

COMFYUI_WORKFLOWS_DIR = Path("D:/ProgramFilesNormal/ComfyUI/ComfyUI_windows_portable/ComfyUI/user/default/workflows/ARCHITECTURE_PRODUCTION")
ARCHIVE_DIR = COMFYUI_WORKFLOWS_DIR / "ARCHIVE_RC2"

PRODUCTION_WORKFLOW_FILES = [
    "01_Exterior_Hero.json",
    "02_Day_Night_Transition.json",
    "03_Material_Detail.json",
    "04_Drone_Aerial.json",
    "05_Slow_Walkthrough.json"
]

OLD_WORKFLOW_FILES = [
    "1_建筑效果图_ImageToVideo.json",
    "2_建筑鸟瞰动画_AerialView.json",
    "3_建筑夜景灯光变化_NightTransition.json"
]

REQUIRED_NODE_TYPES = [
    "LoadImage",
    "RHMiniMaxH3ModelLoader",
    "RHMiniMaxH3TextEncoderLoader",
    "RHMiniMaxH3VAELoader",
    "RHMiniMaxH3T2VATextEncode",
    "RHMiniMaxH3DualSigmaSampler",
    "RHMiniMaxH3DecodeAV",
    "VHS_VideoCombine"
]

def deploy_and_validate_workflows() -> dict:
    COMFYUI_WORKFLOWS_DIR.mkdir(parents=True, exist_ok=True)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Move old workflows to ARCHIVE_RC2
    archived_files = []
    for old_file in OLD_WORKFLOW_FILES:
        src = COMFYUI_WORKFLOWS_DIR / old_file
        if src.is_file():
            dst = ARCHIVE_DIR / old_file
            shutil.move(str(src), str(dst))
            archived_files.append(old_file)

    # 2. Copy 5 production workflows
    deployed_files = []
    validation_details = []
    all_workflows_valid = True

    for wf_file in PRODUCTION_WORKFLOW_FILES:
        src = REPO_WORKFLOWS_DIR / wf_file
        dst = COMFYUI_WORKFLOWS_DIR / wf_file

        if src.is_file():
            shutil.copy2(str(src), str(dst))
            deployed_files.append(wf_file)

            # Validate nodes
            with open(src, "r", encoding="utf-8") as f:
                wf_json = json.load(f)

            nodes = wf_json.get("nodes", [])
            node_types = [n.get("type") for n in nodes]
            missing_required_nodes = [r for r in REQUIRED_NODE_TYPES if r not in node_types]

            wf_valid = len(missing_required_nodes) == 0
            if not wf_valid:
                all_workflows_valid = False

            validation_details.append({
                "workflow": wf_file,
                "deployed_to": str(dst),
                "total_nodes": len(nodes),
                "missing_nodes_count": 0 if wf_valid else len(missing_required_nodes),
                "status": "PASS" if wf_valid else "FAIL"
            })
        else:
            all_workflows_valid = False
            validation_details.append({
                "workflow": wf_file,
                "status": "FILE_NOT_FOUND"
            })

    report = {
        "auditor_version": "1.0.0",
        "deployment_target": str(COMFYUI_WORKFLOWS_DIR),
        "archive_directory": str(ARCHIVE_DIR),
        "archived_old_workflows": archived_files,
        "deployed_production_workflows": deployed_files,
        "validation_results": validation_details,
        "zero_missing_nodes_verified": all_workflows_valid,
        "status": "PASS" if all_workflows_valid else "FAIL"
    }

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with open(REPORT_FILE, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

    return report

if __name__ == "__main__":
    res = deploy_and_validate_workflows()
    print("\n=======================================================")
    print(f"Workflow Deployment Status: {res['status']}")
    print(f"Deployed Workflows: {len(res['deployed_production_workflows'])} files")
    print("=======================================================\n")
    print(json.dumps(res, indent=2, ensure_ascii=False))
