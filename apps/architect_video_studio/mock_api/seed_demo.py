"""Seed demo studies for the prototype UI (PATCH2.6-D.2, neutral names).

Creates four studies with neutral demo names (no real project names):
  A. Walkthrough Study   - 05 Slow Walkthrough, COMPLETED job + output package
  B. Facade Motion Study - 01 Exterior Hero, prompt generated (USER_CONFIRM)
  C. Material Study      - 03 Material Detail, reference approved (no intent)
  D. Draft Study 001     - 05 Slow Walkthrough, reference PENDING (fresh task)
"""

from __future__ import annotations

import base64
import argparse
from pathlib import Path
from typing import Dict

from ._paths import REPO_ROOT
from .job_api import JobAPI
from .project_api import ProjectAPI
from .prompt_api import PromptAPI
from .reference_api import ReferenceAPI
from .store import StudioStore

SAMPLE_DIR = REPO_ROOT / "samples"
_SAFE_SAMPLE_FILES = {
    "01_Exterior_Hero.png": "01_Exterior_Hero.png",
    "05_Slow_Walkthrough.png": "05_Slow_Walkthrough.png",
}
_MOCK_OUTPUT_LABEL = "仅用于本地演示（不写入用户目录）"


def _read_image(name: str) -> bytes:
    sample_name = _SAFE_SAMPLE_FILES.get(Path(name).name)
    path = SAMPLE_DIR / sample_name if sample_name else None
    if path is not None and path.is_file():
        return path.read_bytes()
    # deterministic placeholder PNG (1x1) so previews still render
    import zlib

    def chunk(tag: bytes, data: bytes) -> bytes:
        import struct
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(b"\x00\xff\xff\xff"))
            + chunk(b"IEND", b""))


def _create_demo_project(project_api: ProjectAPI, store: StudioStore,
                         name: str, project_type: str,
                         building_stage: str) -> dict:
    """Create a demo Study without retaining a host Documents path."""
    project = project_api.create_project(name, project_type, building_stage)
    project["output_directory"] = _MOCK_OUTPUT_LABEL
    store.save_project(project)
    return project


def seed_demo(data_root: Path,
              clock_seconds: float = 999.0) -> Dict[str, str]:
    """Seed neutral demo data in a caller-selected isolated directory.

    The data root is mandatory so demo projects cannot silently accumulate in
    the application data directory. Reference images are restricted to the
    repository's tracked synthetic samples; adjacent owner media is ignored.
    """
    store = StudioStore(data_root)
    project_api = ProjectAPI(store)
    reference_api = ReferenceAPI(store)
    prompt_api = PromptAPI(store)

    # ---- Task A: Walkthrough Study (05), completed job ----
    a = _create_demo_project(
        project_api, store, "Walkthrough Study", "exterior", "方案")
    ref_a = reference_api.upload_reference(
        a["id"], "05_Slow_Walkthrough.png", role="first_frame",
        data_base64=base64.b64encode(_read_image("05_Slow_Walkthrough.png")).decode(),
    )
    reference_api.approve_reference(a["id"], ref_a["id"])
    from .intent_api import IntentAPI
    intent_api_a = IntentAPI(store)
    ia = intent_api_a.analyze_intent(
        a["id"], "做一个入口缓慢推进的视频，突出建筑尺度感")
    if ia["requires_user_confirmation"]:
        intent_api_a.confirm_workflow(a["id"], ia["candidate_workflows"][0])
    prompt_api.generate_prompt(a["id"])

    job_api = JobAPI(store, clock=lambda: 0.0)
    job_a = job_api.submit_job(a["id"], seed=20260815, risk_reviewed=True)
    job_api.advance(job_a["id"], clock_seconds)
    job_a = job_api.get_job(job_a["id"])

    # ---- Task B: Facade Motion Study (01), at USER_CONFIRM (no job) ----
    b = _create_demo_project(
        project_api, store, "Facade Motion Study", "exterior", "展示")
    ref_b = reference_api.upload_reference(
        b["id"], "01_Exterior_Hero.png", role="first_frame",
        data_base64=base64.b64encode(_read_image("01_Exterior_Hero.png")).decode(),
    )
    reference_api.approve_reference(b["id"], ref_b["id"])
    intent_api_b = IntentAPI(store)
    ib = intent_api_b.analyze_intent(b["id"], "做一个建筑外观主视角展示视频")
    if ib["requires_user_confirmation"]:
        intent_api_b.confirm_workflow(b["id"], ib["candidate_workflows"][0])
    prompt_api.generate_prompt(b["id"])

    # ---- Study C: Material Study (03), reference approved, no intent ----
    c = _create_demo_project(
        project_api, store, "Material Study", "material", "展示")
    ref_c = reference_api.upload_reference(
        c["id"], "01_Exterior_Hero.png", role="first_frame",
        data_base64=base64.b64encode(_read_image("01_Exterior_Hero.png")).decode(),
    )
    reference_api.approve_reference(c["id"], ref_c["id"])

    # ---- Study D: Draft Study 001 (05), reference pending (fresh task) ----
    d = _create_demo_project(
        project_api, store, "Draft Study 001", "mixed", "方案")
    reference_api.upload_reference(
        d["id"], "05_Slow_Walkthrough.png", role="first_frame",
        data_base64=base64.b64encode(_read_image("05_Slow_Walkthrough.png")).decode(),
    )

    return {
        "project_a": a["id"],
        "job_a": job_a["id"],
        "project_b": b["id"],
        "project_c": c["id"],
        "project_d": d["id"],
    }


if __name__ == "__main__":
    import json
    parser = argparse.ArgumentParser(description="Seed neutral Studio demo data.")
    parser.add_argument(
        "--data", type=Path, required=True,
        help="explicit isolated directory for disposable demo data",
    )
    args = parser.parse_args()
    result = seed_demo(args.data)
    print(json.dumps(result, indent=2))
