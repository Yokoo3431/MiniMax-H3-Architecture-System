"""Project API (mock, contract-first)."""

from __future__ import annotations

from typing import Any, Dict, List

from .store import StudioStore

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

    def list_projects(self) -> List[Dict[str, Any]]:
        return self.store.list_projects()

    def update_project(self, project_id: str, patch: Dict[str, Any]) -> Dict[str, Any]:
        project = self.store.load_project(project_id)
        for key in ("name", "project_type", "building_stage"):
            if key in patch:
                project[key] = patch[key]
        self.store.save_project(project)
        return project
