"""JSON-file store for the Architect Video Studio prototype.

Persists projects, references, intent, prompt, jobs, audit log, and the output
package under ``data_root/projects/<project_id>/``.
"""

from __future__ import annotations

import json
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


class StudioStore:
    def __init__(self, data_root: Path) -> None:
        self.data_root = Path(data_root)
        self.projects_root = self.data_root / "projects"
        self.projects_root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ #
    # low-level
    # ------------------------------------------------------------------ #
    def project_dir(self, project_id: str) -> Path:
        d = (self.projects_root / project_id).resolve()
        if not str(d).startswith(str(self.projects_root.resolve())):
            raise ValueError(f"unsafe project id: {project_id}")
        return d

    def save_json(self, path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def load_json(self, path: Path, default: Any = None) -> Any:
        if not path.is_file():
            return default
        return json.loads(path.read_text(encoding="utf-8"))

    def append_jsonl(self, path: Path, record: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    # ------------------------------------------------------------------ #
    # ids / timestamps
    # ------------------------------------------------------------------ #
    @staticmethod
    def new_id(prefix: str) -> str:
        return f"{prefix}-{uuid.uuid4().hex[:12]}"

    @staticmethod
    def timestamp() -> str:
        return _now()

    # ------------------------------------------------------------------ #
    # projects
    # ------------------------------------------------------------------ #
    def project_file(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "project.json"

    def list_projects(self) -> List[Dict[str, Any]]:
        out = []
        for d in sorted(self.projects_root.iterdir()):
            p = self.load_json(d / "project.json")
            if p:
                out.append(p)
        return out

    def load_project(self, project_id: str) -> Dict[str, Any]:
        p = self.load_json(self.project_file(project_id))
        if not p:
            raise KeyError(f"project not found: {project_id}")
        return p

    def save_project(self, project: Dict[str, Any]) -> Dict[str, Any]:
        project["updated_at"] = self.timestamp()
        self.save_json(self.project_file(project["id"]), project)
        return project

    # ------------------------------------------------------------------ #
    # references
    # ------------------------------------------------------------------ #
    def references_file(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "references.json"

    def load_references(self, project_id: str) -> Dict[str, Dict[str, Any]]:
        return self.load_json(self.references_file(project_id), {})

    def save_references(self, project_id: str,
                        refs: Dict[str, Dict[str, Any]]) -> None:
        self.save_json(self.references_file(project_id), refs)

    def input_dir(self, project_id: str) -> Path:
        d = self.project_dir(project_id) / "input"
        d.mkdir(parents=True, exist_ok=True)
        return d

    # ------------------------------------------------------------------ #
    # intent / prompt
    # ------------------------------------------------------------------ #
    def intent_file(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "intent.json"

    def load_intent(self, project_id: str) -> Optional[Dict[str, Any]]:
        return self.load_json(self.intent_file(project_id))

    def save_intent(self, project_id: str, intent: Dict[str, Any]) -> None:
        self.save_json(self.intent_file(project_id), intent)

    def prompt_file(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "prompt.json"

    def load_prompt(self, project_id: str) -> Optional[Dict[str, Any]]:
        return self.load_json(self.prompt_file(project_id))

    def save_prompt(self, project_id: str, prompt: Dict[str, Any]) -> None:
        self.save_json(self.prompt_file(project_id), prompt)

    # ------------------------------------------------------------------ #
    # jobs
    # ------------------------------------------------------------------ #
    def jobs_file(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "jobs.json"

    def load_jobs(self, project_id: str) -> Dict[str, Dict[str, Any]]:
        return self.load_json(self.jobs_file(project_id), {})

    def save_jobs(self, project_id: str,
                  jobs: Dict[str, Dict[str, Any]]) -> None:
        self.save_json(self.jobs_file(project_id), jobs)

    def find_job(self, job_id: str) -> tuple[str, Dict[str, Any]]:
        for d in self.projects_root.iterdir():
            jobs = self.load_json(d / "jobs.json", {})
            if job_id in jobs:
                return d.name, jobs[job_id]
        raise KeyError(f"job not found: {job_id}")

    # ------------------------------------------------------------------ #
    # audit log
    # ------------------------------------------------------------------ #
    def audit_file(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "audit_log.jsonl"

    def append_audit(self, project_id: str, record: Dict[str, Any]) -> None:
        record.setdefault("at", self.timestamp())
        self.append_jsonl(self.audit_file(project_id), record)

    def load_audit(self, project_id: str) -> List[Dict[str, Any]]:
        path = self.audit_file(project_id)
        out = []
        if path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    out.append(json.loads(line))
        return out

    # ------------------------------------------------------------------ #
    # output package
    # ------------------------------------------------------------------ #
    def package_dir(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "output_package"

    def clear_package(self, project_id: str) -> None:
        d = self.package_dir(project_id)
        if d.is_dir():
            shutil.rmtree(d)
