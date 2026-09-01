"""Project API (mock, contract-first)."""

from __future__ import annotations

import copy
import shutil
from typing import Any, Dict, List

from .store import StudioStore
from .job_state import is_job_active

ALLOWED_PROJECT_TYPES = ("exterior", "interior", "material", "lighting", "aerial", "landscape", "mixed")
ALLOWED_BUILDING_STAGES = ("方案", "扩初", "报建", "展示", "concept", "schematic", "construction", "presentation")


class ProjectAPI:
    def __init__(self, store: StudioStore) -> None:
        self.store = store

    def create_project(self, name: str, project_type: str = "exterior",
                       building_stage: str = "方案") -> Dict[str, Any]:
        name = (name or "").strip()
        if not name:
            raise ValueError("project name is required")
        if project_type not in ALLOWED_PROJECT_TYPES:
            raise ValueError(f"project_type {project_type!r} not in {ALLOWED_PROJECT_TYPES}")
        if building_stage not in ALLOWED_BUILDING_STAGES:
            raise ValueError(f"building_stage {building_stage!r} not in {ALLOWED_BUILDING_STAGES}")
        pid = self.store.new_id("proj")
        project = {
            "id": pid,
            "name": name,
            "project_type": project_type,
            "building_stage": building_stage,
            "state": "CREATED",
            "created_at": self.store.timestamp(),
            "updated_at": self.store.timestamp(),
            "risk_reviewed": False,
            "intent_confirmed": False,
            "output_directory": str(self.store.default_output_directory({"name": name})),
        }
        self.store.save_project(project)
        self.store.append_audit(pid, {
            "actor": "architect",
            "event": "create_project",
            "from": "-",
            "to": "CREATED",
            "detail": {"name": name, "project_type": project_type, "building_stage": building_stage},
        })
        return project

    def get_project(self, project_id: str) -> Dict[str, Any]:
        return self.store.load_project(project_id)

    def get_project_detail(self, project_id: str) -> Dict[str, Any]:
        """Return the single canonical hydration contract used by Studio.

        The project record remains the domain source of truth.  This response
        is a read-only composition of that record and the same Study/asset/
        prompt/job services used by the individual endpoints, so the frontend
        cannot accidentally hydrate itself from a different state model.
        """
        project = self.store.load_project(project_id)
        from .reference_api import ReferenceAPI
        from .study_state import build_study_state
        build_study_state(self.store, project_id)

        references = ReferenceAPI(self.store).list_references(project_id)
        intent = self.store.load_intent(project_id)
        prompt = self.store.load_prompt(project_id)
        jobs = list(self.store.load_jobs(project_id).values())
        active = next((job for job in jobs if is_job_active(job)), None)
        study = build_study_state(self.store, project_id)
        return {
            **copy.deepcopy(project),
            "project": copy.deepcopy(project),
            "study": study,
            "references": references,
            "intent": copy.deepcopy(intent),
            "prompt": copy.deepcopy(prompt),
            "jobs": copy.deepcopy(jobs),
            "current_job": copy.deepcopy(active),
            "current_reference_asset_id": project.get("current_reference_asset_id"),
        }

    def list_projects(self) -> List[Dict[str, Any]]:
        return self.store.list_projects()

    def update_project(self, project_id: str, patch: Dict[str, Any]) -> Dict[str, Any]:
        project = self.store.load_project(project_id)
        for key in ("name", "project_type", "building_stage"):
            if key in patch:
                project[key] = patch[key]
        if "output_directory" in patch:
            output = str(patch.get("output_directory") or "").strip()
            if not output:
                raise ValueError("output_directory is required")
            project["output_directory"] = output
        self.store.save_project(project)
        return project

    def rename_project(self, project_id: str, name: str) -> Dict[str, Any]:
        name = (name or "").strip()
        if not name:
            raise ValueError("project name is required")
        return self.update_project(project_id, {"name": name})

    def duplicate_project(self, project_id: str, name: str | None = None) -> Dict[str, Any]:
        source = self.store.load_project(project_id)
        new_id = self.store.new_id("proj")
        source_dir = self.store.project_dir(project_id)
        target_dir = self.store.project_dir(new_id)
        if target_dir.exists():
            raise ValueError("duplicate project target already exists")
        shutil.copytree(source_dir, target_dir)
        project = copy.deepcopy(source)
        project["id"] = new_id
        project["name"] = (name or f"{source.get('name', 'Study')} Copy").strip()
        project["created_at"] = self.store.timestamp()
        project["updated_at"] = self.store.timestamp()
        self.store.save_project(project)
        self.store.append_audit(new_id, {
            "actor": "architect", "event": "duplicate_project",
            "from": project_id, "to": new_id,
        })
        return project

    def delete_project(self, project_id: str, *, confirm: bool = False,
                       delete_outputs: bool = False) -> Dict[str, Any]:
        if not confirm:
            raise ValueError("confirmation required before deleting a Study")
        project = self.store.load_project(project_id)
        from .study_state import build_study_state
        build_study_state(self.store, project_id)
        active = [job for job in self.store.load_jobs(project_id).values()
                  if is_job_active(job)]
        if active:
            raise ValueError("该项目仍有正在执行的任务，请先取消任务或选择取消任务并删除。")
        self.store.delete_project(project_id, delete_outputs=delete_outputs)
        return {"id": project_id, "deleted": True,
                "outputs_deleted": bool(delete_outputs)}
