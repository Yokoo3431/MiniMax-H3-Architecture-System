"""Personal Workspace Manager for Architect Daily Usage (V0.8.0 RC2).
Auto-initializes input_images/, generated_prompts/, selected_workflows/, outputs/, and reports/ folders.
"""

import os
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent.parent
USERDATA_WORKSPACE = SYSTEM_ROOT / "userdata" / "personal_workspace"
TESTS_WORKSPACE = SYSTEM_ROOT / "tests" / "personal_workspace"

SUBDIRS = [
    "input_images",
    "generated_prompts",
    "selected_workflows",
    "outputs",
    "reports"
]

def initialize_personal_workspace(base_dir: Path = None) -> dict:
    if base_dir is None:
        base_dir = USERDATA_WORKSPACE

    created_dirs = []
    for sub in SUBDIRS:
        p = base_dir / sub
        p.mkdir(parents=True, exist_ok=True)
        created_dirs.append(str(p))

    return {
        "status": "initialized",
        "workspace_root": str(base_dir),
        "created_directories": created_dirs
    }

if __name__ == "__main__":
    res = initialize_personal_workspace(USERDATA_WORKSPACE)
    initialize_personal_workspace(TESTS_WORKSPACE)
    print(res)
