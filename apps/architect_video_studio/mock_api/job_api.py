"""Job API (PATCH2.7-D: UI -> Runtime binding).

Endpoint contract unchanged. Internal execution switches from clock-based mock
simulation to the real RuntimeAdapter when one is configured:

    submit_job -> builds VideoGenerationRequest -> adapter thread (async)
    get_job    -> poll current state (mock thresholds or real stage mapping)
    cancel     -> terminal CANCELLED, no auto retry

The UI never builds a ComfyUI payload; only the RuntimeAdapter does.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, List, Optional

from ..state_machine.machine import (
    JobStateMachine,
    ProjectStateMachine,
)
from .store import StudioStore

# rough expected real-run duration used to derive UI stages while executing
_EXPECTED_REAL_SECONDS = 900.0


class JobAPI:
    def __init__(self, store: StudioStore, output_api=None,
                 clock: Callable[[], float] | None = None,
                 runtime_adapter=None,
                 comfy_input_dir: Optional[str] = None) -> None:
        self.store = store
        from .output_api import OutputAPI
        self.output_api = output_api or OutputAPI(store)
        self.clock = clock or time.time
        self.runtime_adapter = runtime_adapter  # Optional[RuntimeAdapter]
        self.comfy_input_dir = comfy_input_dir
        self._threads: Dict[str, threading.Thread] = {}

    # ------------------------------------------------------------------ #
    def submit_job(self, project_id: str, seed: int = 42,
                   risk_reviewed: bool = False,
                   generation_parameters: Optional[Dict[str, Any]] = None,
                   camera_motion: Optional[str] = None) -> Dict[str, Any]:
        project = self.store.load_project(project_id)
        if project["state"] != "USER_CONFIRM":
            raise ValueError(
                f"submit_job requires USER_CONFIRM; project is {project['state']}"
            )
        if not risk_reviewed:
            raise ValueError("Risk Review Gate: risk must be reviewed before generate")

        approved = [r for r in self.store.load_references(project_id).values()
                    if r["state"] == "APPROVED"]
        if not approved:
            raise ValueError("Reference Approval Gate: no approved reference")

        prompt = self.store.load_prompt(project_id)
        if prompt is None:
            raise ValueError("Prompt Gate: generate_prompt first")
        if not (prompt.get("verified") or {}).get("pass"):
            raise ValueError("Prompt Gate: official structure verification failed")

        params = {
            "resolution": "1344x768",
            "fps": 24,
            "duration": 4.0,
            "quality": "diagnostic",
            "seed": int(seed),
        }
        if generation_parameters:
            params.update({k: v for k, v in generation_parameters.items()
                           if k in ("resolution", "fps", "duration", "quality")})
            params["seed"] = int(seed)

        now = self.clock()
        job_id = self.store.new_id("job")
        job = {
            "id": job_id,
            "project_id": project_id,
            "workflow": prompt["workflow"],
            "state": "PREPARING",
            "seed": int(seed),
            "camera_motion": camera_motion,
            "generation_parameters": params,
            "runtime": "native" if self.runtime_adapter else "mock",
            "created_at": self.store.timestamp(),
            "started_at": now,
            "elapsed": 0.0,
            "stages": ["PREPARING"],
            "package_built": False,
            "failure_reason": "",
            "prompt_hash": prompt["prompt_hash"],
            "cancelled": False,
        }
        jobs = self.store.load_jobs(project_id)
        jobs[job_id] = job
        self.store.save_jobs(project_id, jobs)

        machine = ProjectStateMachine(project["state"])
        machine.transition("confirm_generate", actor="architect",
                           reason=f"submit job {job_id}")
        project["state"] = machine.state
        self.store.save_project(project)
        self.store.append_audit(project_id, {
            "actor": "architect",
            "event": "confirm_generate",
            "from": "USER_CONFIRM",
            "to": "GPU_RUNNING",
            "detail": {"job_id": job_id, "seed": seed, "risk_reviewed": True,
                       "runtime": job["runtime"]},
        })

        if self.runtime_adapter:
            request = self._build_request(project_id, project, prompt, approved,
                                          params, camera_motion)
            thread = threading.Thread(
                target=self._run_real_job,
                args=(project_id, job_id, request),
                daemon=True,
            )
            self._threads[job_id] = thread
            thread.start()
        return self.get_job(job_id)

    # ------------------------------------------------------------------ #
    def get_job(self, job_id: str) -> Dict[str, Any]:
        project_id, job = self.store.find_job(job_id)
        if job.get("runtime") == "native":
            if job["state"] in ("COMPLETED", "GPU_FAILED", "CANCELLED"):
                return job
            elapsed = max(0.0, self.clock() - float(job["started_at"]))
            job["elapsed"] = round(elapsed, 3)
            job["state"] = _real_stage(elapsed)
            if job["state"] not in job["stages"]:
                job["stages"].append(job["state"])
            return job
        elapsed = max(0.0, self.clock() - float(job["started_at"]))
        return self._apply_elapsed(project_id, job, elapsed)

    def list_jobs(self, project_id: str) -> List[Dict[str, Any]]:
        out = []
        for job in self.store.load_jobs(project_id).values():
            out.append(self.get_job(job["id"]))
        return sorted(out, key=lambda j: j["created_at"], reverse=True)

    def advance(self, job_id: str, elapsed_seconds: float) -> Dict[str, Any]:
        """Explicit deterministic progression (mock tests only)."""
        project_id, job = self.store.find_job(job_id)
        return self._apply_elapsed(project_id, job, float(elapsed_seconds))

    def fail_job(self, job_id: str, reason: str = "mock GPU failure") -> Dict[str, Any]:
        project_id, job = self.store.find_job(job_id)
        if job["state"] in ("COMPLETED", "GPU_FAILED", "CANCELLED"):
            raise ValueError(f"job already in terminal state {job['state']}")
        job["state"] = "GPU_FAILED"
        job["failure_reason"] = reason
        self._save_job(project_id, job)
        self._sync_project_failed(project_id, job, reason)
        return job

    def cancel(self, job_id: str) -> Dict[str, Any]:
        project_id, job = self.store.find_job(job_id)
        if job["state"] in ("COMPLETED", "GPU_FAILED", "CANCELLED"):
            raise ValueError(f"job already in terminal state {job['state']}")
        job["state"] = "CANCELLED"
        job["cancelled"] = True
        job["failure_reason"] = "cancelled by user"
        job["stages"].append("CANCELLED")
        self._save_job(project_id, job)
        self.store.append_audit(project_id, {
            "actor": "architect", "event": "cancel_job",
            "from": "GPU_RUNNING", "to": "GPU_FAILED",
            "detail": {"job_id": job_id},
        })
        return job

    # ------------------------------------------------------------------ #
    def _build_request(self, project_id: str, project: dict, prompt: dict,
                       approved_refs: List[dict], params: dict,
                       camera_motion: Optional[str]) -> Any:
        from runtime.adapters.runtime_adapter import VideoGenerationRequest
        intent = self.store.load_intent(project_id) or {}
        refs = [{
            "asset_id": r["id"],
            "role": r.get("role", "first_frame"),
            "path_or_ref": r.get("stored_path") or r.get("filename", "ref.png"),
            "sha256": r.get("sha256"),
        } for r in approved_refs]
        return VideoGenerationRequest(
            study_id=project_id,
            reference_assets=refs,
            workflow_id=prompt["workflow"],
            camera_motion=camera_motion or "slow_push",
            generation_parameters=params,
            prompt_payload={
                "mode": prompt.get("mode", "I2VA"),
                "prompt": prompt["prompt"],
                "alignment": prompt.get("alignment", ""),
                "integrated_multimodal_description": prompt.get(
                    "integrated_multimodal_description", ""),
                "overall_soundscape": prompt.get("overall_soundscape", ""),
                "non_diegetic_music": "N/A",
                "prompt_hash": prompt["prompt_hash"],
            },
            output_spec={"container": "mp4", "codec": "h264", "fps": 24,
                         "resolution": params.get("resolution", "1344x768"),
                         "report_format": "json"},
            gates={"reference_approved": True, "intent_confirmed": True,
                   "prompt_verified": True, "risk_reviewed": True},
        )

    def _run_real_job(self, project_id: str, job_id: str, request: Any) -> None:
        job = self.store.load_jobs(project_id).get(job_id)
        if job is None:
            return
        try:
            self._stage_refs_to_comfy_input(project_id, job)
            snapshot = self.runtime_adapter.generate(request)
            # re-read the latest record: user may have cancelled mid-run
            job = self.store.load_jobs(project_id).get(job_id) or job
            if job.get("cancelled") or job["state"] == "CANCELLED":
                return
            output = self.runtime_adapter.get_output(snapshot["job_id"])
            self.output_api.build_real_output_package(
                project_id, job, output, request)
            job["state"] = "COMPLETED"
            job["stages"].append("COMPLETED")
            job["package_built"] = True
            self._save_job(project_id, job)
            self._sync_project_complete(project_id, job)
            self.store.append_audit(project_id, {
                "actor": "runtime", "event": "job_completed",
                "from": "GPU_RUNNING", "to": "COMPLETED",
                "detail": {"job_id": job_id,
                           "prompt_id": snapshot.get("prompt_id")},
            })
        except Exception as exc:  # noqa: BLE001
            job["state"] = "GPU_FAILED"
            job["failure_reason"] = f"{type(exc).__name__}: {exc}"
            job["stages"].append("GPU_FAILED")
            self._save_job(project_id, job)
            self._sync_project_failed(project_id, job, job["failure_reason"])

    def _stage_refs_to_comfy_input(self, project_id: str, job: dict) -> None:
        if not self.comfy_input_dir:
            return
        import shutil
        from pathlib import Path
        dest_dir = Path(self.comfy_input_dir)
        for ref in self.store.load_references(project_id).values():
            if ref["state"] != "APPROVED":
                continue
            src = Path(ref["stored_path"]) if ref.get("stored_path") else None
            if src and src.is_file():
                shutil.copy2(src, dest_dir / src.name)

    # ------------------------------------------------------------------ #
    def _apply_elapsed(self, project_id: str, job: Dict[str, Any],
                       elapsed: float) -> Dict[str, Any]:
        if job["state"] in ("COMPLETED", "GPU_FAILED", "CANCELLED"):
            return job
        target = JobStateMachine.state_for_elapsed(elapsed)
        if target != job["state"]:
            job["state"] = target
            job["elapsed"] = round(elapsed, 3)
            if target not in job["stages"]:
                job["stages"].append(target)
            self._save_job(project_id, job)
            self._sync_project(project_id, job)
        return job

    def _sync_project(self, project_id: str, job: Dict[str, Any]) -> None:
        project = self.store.load_project(project_id)
        if project["state"] == "GPU_RUNNING" and job["state"] == "COMPLETED":
            machine = ProjectStateMachine("GPU_RUNNING")
            machine.transition("succeeded", actor="runtime",
                               reason=f"job {job['id']} completed")
            machine.transition("quality_pass", actor="system",
                               reason="mock quality check passed")
            project["state"] = machine.state
            self.store.save_project(project)
            self.store.append_audit(project_id, {
                "actor": "runtime", "event": "job_completed",
                "from": "GPU_RUNNING", "to": "COMPLETED",
                "detail": {"job_id": job["id"]},
            })
            if job.get("runtime") != "native":
                self.output_api.build_output_package(project_id, job)
                job["package_built"] = True

    def _sync_project_complete(self, project_id: str, job: Dict[str, Any]) -> None:
        self._sync_project(project_id, job)

    def _sync_project_failed(self, project_id: str, job: Dict[str, Any],
                             reason: str) -> None:
        project = self.store.load_project(project_id)
        machine = ProjectStateMachine(project["state"])
        machine.transition("failed", actor="runtime", reason=reason)
        project["state"] = machine.state
        self.store.save_project(project)
        self.store.append_audit(project_id, {
            "actor": "runtime", "event": "job_failed",
            "from": "GPU_RUNNING", "to": "GPU_FAILED",
            "detail": {"job_id": job["id"], "reason": reason},
        })

    def _save_job(self, project_id: str, job: Dict[str, Any]) -> None:
        jobs = self.store.load_jobs(project_id)
        jobs[job["id"]] = job
        self.store.save_jobs(project_id, jobs)


def _real_stage(elapsed: float) -> str:
    """Map elapsed time to UI stages for a real run (~900s expected)."""
    frac = elapsed / _EXPECTED_REAL_SECONDS
    if frac < 0.05:
        return "PREPARING"
    if frac < 0.15:
        return "LOADING_MODEL"
    if frac < 0.90:
        return "SAMPLING"
    if frac < 0.98:
        return "ENCODING"
    return "EXPORTING"
