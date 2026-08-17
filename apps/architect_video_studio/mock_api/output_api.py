"""Output API (mock, contract-first).

Builds the Project/input|workflow|prompt|output|report package with provenance,
runtime info, reference hashes, and a frozen workflow copy. No real MP4.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from ._paths import REPO_ROOT
from .store import StudioStore

WORKFLOW_FILE_MAP = {
    "01_Exterior_Hero": "workflows/01_Exterior_Hero_NATIVE.json",
    "02_Day_Night_Transition": "workflows/02_Day_Night_Transition_NATIVE.json",
    "03_Material_Detail": "workflows/03_Material_Detail_NATIVE.json",
    "04_Drone_Aerial": "workflows/04_Drone_Aerial_NATIVE_GOLDEN.json",
    "05_Slow_Walkthrough": "workflows/05_Slow_Walkthrough_NATIVE.json",
}


class OutputAPI:
    def __init__(self, store: StudioStore) -> None:
        self.store = store

    def build_output_package(self, project_id: str,
                             job: Dict[str, Any]) -> Dict[str, Any]:
        project = self.store.load_project(project_id)
        prompt = self.store.load_prompt(project_id)
        intent = self.store.load_intent(project_id)
        refs = list(self.store.load_references(project_id).values())
        package = self.store.package_dir(project_id)
        self.store.clear_package(project_id)

        input_dir = package / "input"
        workflow_dir = package / "workflow"
        prompt_dir = package / "prompt"
        output_dir = package / "output"
        report_dir = package / "report"
        for d in (input_dir, workflow_dir, prompt_dir, output_dir, report_dir):
            d.mkdir(parents=True, exist_ok=True)

        # input/ — copy stored reference bytes; always write reference manifest
        for ref in refs:
            stored = Path(ref["stored_path"]) if ref.get("stored_path") else None
            if stored and stored.is_file():
                dest = input_dir / ref["filename"]
                dest.write_bytes(stored.read_bytes())
        (input_dir / "references.json").write_text(
            json.dumps(refs, indent=2, ensure_ascii=False), encoding="utf-8")

        # workflow/ — read-only copy of the frozen workflow JSON
        workflow_name = job.get("workflow") or prompt.get("workflow")
        frozen = REPO_ROOT / WORKFLOW_FILE_MAP.get(workflow_name, "")
        if frozen.is_file():
            (workflow_dir / frozen.name).write_text(
                frozen.read_text(encoding="utf-8"), encoding="utf-8")
            workflow_copied = frozen.name
        else:
            workflow_copied = None

        # prompt/
        (prompt_dir / "prompt.json").write_text(
            json.dumps(prompt, indent=2, ensure_ascii=False), encoding="utf-8")

        # output/ — placeholder MP4 (prototype only, no GPU)
        placeholder = (
            "MOCK OUTPUT PLACEHOLDER - Architect Video Studio PATCH2.6-B prototype.\n"
            "No real MP4 is generated in this phase. PATCH2.6-C connects the "
            "Native runtime to produce the actual video.\n"
            f"workflow={workflow_name} seed={job.get('seed')}\n"
        )
        (output_dir / "output.mp4").write_text(placeholder, encoding="utf-8")

        # report/
        provenance = (prompt or {}).get("provenance", {})
        (report_dir / "provenance.json").write_text(
            json.dumps(provenance, indent=2, ensure_ascii=False), encoding="utf-8")
        runtime_info = {
            "runtime": "MOCK_PROTOTYPE (no GPU)",
            "comfyui_invoked": False,
            "native_baseline": "ComfyUI v0.33.1 (frozen, not invoked)",
            "safe_load": "pread (frozen)",
            "model_load": False,
            "job_id": job.get("id"),
            "workflow": workflow_name,
            "seed": job.get("seed"),
        }
        (report_dir / "runtime_info.json").write_text(
            json.dumps(runtime_info, indent=2, ensure_ascii=False), encoding="utf-8")
        report = {
            "project_id": project_id,
            "project_name": project["name"],
            "job_id": job.get("id"),
            "workflow": workflow_name,
            "state": "COMPLETED",
            "reference_hashes": {r["filename"]: r.get("sha256") for r in refs},
            "intent": intent,
            "prompt_hash": prompt.get("prompt_hash"),
            "provenance": provenance,
            "audit_log": self.store.load_audit(project_id),
            "runtime_info": runtime_info,
            "workflow_file_copied": workflow_copied,
        }
        (report_dir / "report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        return self.manifest(project_id, job)

    def build_real_output_package(self, project_id: str, job: Dict[str, Any],
                                  output: Dict[str, Any],
                                  request: Any) -> Dict[str, Any]:
        """Assemble the unified package from a REAL runtime output."""
        import hashlib
        import shutil

        project = self.store.load_project(project_id)
        prompt = self.store.load_prompt(project_id)
        package = self.store.package_dir(project_id)
        self.store.clear_package(project_id)
        for sub in ("input", "workflow", "prompt", "output", "report"):
            (package / sub).mkdir(parents=True, exist_ok=True)

        # input/ — approved reference files + manifest
        refs = [r for r in self.store.load_references(project_id).values()
                if r["state"] == "APPROVED"]
        for ref in refs:
            src = Path(ref["stored_path"]) if ref.get("stored_path") else None
            if src and src.is_file():
                shutil.copy2(src, package / "input" / src.name)
        (package / "input" / "references.json").write_text(
            json.dumps(refs, indent=2, ensure_ascii=False), encoding="utf-8")

        # workflow/ — frozen asset copy (from workflow mapping YAML, read-only)
        import yaml
        mapping = yaml.safe_load(
            (REPO_ROOT / "runtime" / "contracts" / "workflow_mapping.yaml")
            .read_text(encoding="utf-8"))
        asset_rel = mapping["workflow_registry"][job.get("workflow")]["native_asset"]
        workflow_asset = REPO_ROOT / asset_rel
        if workflow_asset and workflow_asset.is_file():
            shutil.copy2(workflow_asset, package / "workflow" / workflow_asset.name)

        # prompt/
        prompt_record = {
            "study_id": project_id,
            "workflow_id": job.get("workflow"),
            "camera_motion": job.get("camera_motion"),
            "generation_parameters": job.get("generation_parameters"),
            "prompt_hash": (prompt or {}).get("prompt_hash"),
            "prompt": (prompt or {}).get("prompt"),
        }
        (package / "prompt" / "prompt.json").write_text(
            json.dumps(prompt_record, indent=2, ensure_ascii=False), encoding="utf-8")

        # output/
        video_path = Path(output["video_path"])
        if video_path.is_file():
            shutil.copy2(video_path, package / "output" / "video.mp4")
        else:
            (package / "output" / "video.mp4").write_text(
                f"MISSING REAL VIDEO: {video_path}", encoding="utf-8")

        # report/
        runtime_info = dict(output.get("runtime_info") or {})
        runtime_info.update({
            "comfyui_version": "0.33.1",
            "safe_load": "H3_WINDOWS_SAFE_LOAD=pread",
            "workflow_asset": workflow_asset.name if workflow_asset else None,
            "output_package": str(package),
        })
        (package / "report" / "runtime_info.json").write_text(
            json.dumps(runtime_info, indent=2, ensure_ascii=False), encoding="utf-8")
        provenance = {
            "workflow": job.get("workflow"),
            "mode": (prompt or {}).get("mode"),
            "prompt_hash": (prompt or {}).get("prompt_hash"),
            "reference_sha256": [r.get("sha256") for r in refs],
            "reference_approved": True,
            "seed": job.get("seed"),
            "official_skill_revision": "2026-07-29-main-reviewed",
            "runtime": "native",
        }
        (package / "report" / "provenance.json").write_text(
            json.dumps(provenance, indent=2, ensure_ascii=False), encoding="utf-8")
        generation_report = {
            "project_id": project_id,
            "project_name": project["name"],
            "job_id": job.get("id"),
            "workflow": job.get("workflow"),
            "seed": job.get("seed"),
            "camera_motion": job.get("camera_motion"),
            "generation_parameters": job.get("generation_parameters"),
            "prompt_hash": (prompt or {}).get("prompt_hash"),
            "runtime_info": runtime_info,
            "provenance": provenance,
            "status": "COMPLETED",
        }
        (package / "report" / "generation_report.json").write_text(
            json.dumps(generation_report, indent=2, ensure_ascii=False),
            encoding="utf-8")
        return self.manifest(project_id, job)

    def get_result(self, job_id: str) -> Dict[str, Any]:
        project_id, job = self.store.find_job(job_id)
        if job["state"] != "COMPLETED":
            raise ValueError(f"job {job_id} is {job['state']}; result available only when COMPLETED")
        return self.manifest(project_id, job)

    def get_report(self, job_id: str) -> Dict[str, Any]:
        project_id, job = self.store.find_job(job_id)
        report_path = self.store.package_dir(project_id) / "report" / "report.json"
        if not report_path.is_file():
            raise ValueError(f"report not built for job {job_id}")
        return json.loads(report_path.read_text(encoding="utf-8"))

    def list_outputs(self, project_id: str) -> List[Dict[str, Any]]:
        out = []
        for job in self.store.load_jobs(project_id).values():
            if job["state"] == "COMPLETED":
                out.append(self.manifest(project_id, job))
        return out

    def manifest(self, project_id: str, job: Dict[str, Any]) -> Dict[str, Any]:
        package = self.store.package_dir(project_id)
        return {
            "job_id": job["id"],
            "project_id": project_id,
            "workflow": job.get("workflow"),
            "package_root": str(package),
            "structure": {
                "input": [p.name for p in sorted((package / "input").iterdir())] if (package / "input").is_dir() else [],
                "workflow": [p.name for p in sorted((package / "workflow").iterdir())] if (package / "workflow").is_dir() else [],
                "prompt": [p.name for p in sorted((package / "prompt").iterdir())] if (package / "prompt").is_dir() else [],
                "output": [p.name for p in sorted((package / "output").iterdir())] if (package / "output").is_dir() else [],
                "report": [p.name for p in sorted((package / "report").iterdir())] if (package / "report").is_dir() else [],
            },
            "ffprobe": None,  # no real video in prototype
            "files": {
                "prompt_json": str(package / "prompt" / "prompt.json"),
                "provenance_json": str(package / "report" / "provenance.json"),
                "runtime_info_json": str(package / "report" / "runtime_info.json"),
                "report_json": str(package / "report" / "report.json"),
                "output_mp4_placeholder": str(package / "output" / "output.mp4"),
            },
        }
