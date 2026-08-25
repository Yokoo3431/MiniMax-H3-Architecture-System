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
import shutil
from typing import Any, Callable, Dict, List, Optional
from pathlib import Path

from ..state_machine.machine import (
    JobStateMachine,
    ProjectStateMachine,
)
from .store import StudioStore
from .study_state import build_study_state
from runtime.adapters.runtime_paths import RuntimePathContract, RuntimePathError
from runtime.adapters.comfyui_client import ComfyUIOfflineError
from runtime.product_hardening import unique_comfy_filename
from runtime.product_hardening import estimate_eta
from runtime.h3_generation_parameters import normalize_generation_parameters
from runtime.workflow_motion import WorkflowParameterError, normalize_camera_motion

# rough expected real-run duration used to derive UI stages while executing
_EXPECTED_REAL_SECONDS = 900.0


class InputStagingError(FileNotFoundError):
    """The approved reference is not visible to the active ComfyUI input root."""


class JobAPI:
    def __init__(self, store: StudioStore, output_api=None,
                 clock: Callable[[], float] | None = None,
                 runtime_adapter=None,
                 allow_mock_jobs: bool = True,
                 comfy_input_dir: Optional[str] = None,
                 runtime_paths: Optional[RuntimePathContract] = None) -> None:
        self.store = store
        from .output_api import OutputAPI
        self.output_api = output_api or OutputAPI(store)
        self.clock = clock or time.time
        self.runtime_adapter = runtime_adapter  # Optional[RuntimeAdapter]
        self.allow_mock_jobs = bool(allow_mock_jobs)
        self.comfy_input_dir = comfy_input_dir
        self.runtime_paths = runtime_paths
        self._threads: Dict[str, threading.Thread] = {}

    # ------------------------------------------------------------------ #
    def submit_job(self, project_id: str, seed: int = 42,
                   risk_reviewed: bool = False,
                   generation_parameters: Optional[Dict[str, Any]] = None,
                   camera_motion: Optional[str] = None) -> Dict[str, Any]:
        if self.runtime_adapter is None and not self.allow_mock_jobs:
            raise ValueError(
                "REAL_RUNTIME_REQUIRED: 真实 ComfyUI 尚未就绪，当前不能开始生成；"
                "请等待服务启动或前往环境设置/修复。"
            )
        project = self.store.load_project(project_id)
        previous_project_state = project["state"]
        if project["state"] == "GPU_FAILED":
            study = build_study_state(self.store, project_id)
            if not study["generate_allowed"]:
                raise ValueError(
                    "submit_job requires Study gates; missing: "
                    + ", ".join(study["gate_reasons"])
                )
            machine = ProjectStateMachine(project["state"])
            machine.transition("retry_approved", actor="architect",
                               reason="retry after historical failed job")
            project["state"] = machine.state
            self.store.save_project(project)
        elif project["state"] == "QUALITY_FAILED":
            machine = ProjectStateMachine(project["state"])
            machine.transition("user_reviewed", actor="architect",
                               reason="retry after quality failure")
            project["state"] = machine.state
            self.store.save_project(project)
        elif project["state"] == "COMPLETED":
            study = build_study_state(self.store, project_id)
            if not study["generate_allowed"]:
                raise ValueError(
                    "submit_job requires Study gates; missing: "
                    + ", ".join(study["gate_reasons"])
                )
            machine = ProjectStateMachine(project["state"])
            machine.transition("start_new_generation", actor="architect",
                               reason="start another generation in completed Study")
            project["state"] = machine.state
            self.store.save_project(project)
        if project["state"] != "USER_CONFIRM":
            raise ValueError(
                f"submit_job requires USER_CONFIRM; project is {project['state']}"
            )
        if not risk_reviewed:
            raise ValueError("Risk Review Gate: risk must be reviewed before generate")
        if self.runtime_adapter is not None and self.runtime_paths is not None:
            self.runtime_paths.validate_for_job()

        approved = [r for r in self.store.load_references(project_id).values()
                    if r["state"] == "APPROVED"]
        if not approved:
            raise ValueError("Reference Approval Gate: no approved reference")

        prompt = self.store.load_prompt(project_id)
        if prompt is None:
            raise ValueError("Prompt Gate: generate_prompt first")
        if not (prompt.get("verified") or {}).get("pass"):
            raise ValueError("Prompt Gate: official structure verification failed")

        try:
            normalized_motion = normalize_camera_motion(prompt["workflow"], camera_motion)
        except WorkflowParameterError as exc:
            raise ValueError(f"{exc.code}: 参数配置错误。{exc}") from exc

        # The live ComfyUI registry is checked before a Job record is created.
        # This prevents missing model-path/workflow bindings from becoming a
        # misleading GPU_FAILED job and never submits /prompt.
        if self.runtime_adapter is not None and hasattr(self.runtime_adapter, "preflight"):
            try:
                self.runtime_adapter.preflight()
            except Exception as exc:  # noqa: BLE001
                raise ValueError(f"MODEL_PATH_ERROR: 模型路径或工作流绑定未通过预检。{exc}") from exc

        try:
            params = normalize_generation_parameters(generation_parameters, seed=int(seed))
        except ValueError as exc:
            raise ValueError(f"参数不符合 H3 生成契约: {exc}") from exc

        now = self.clock()
        job_id = self.store.new_id("job")
        job = {
            "id": job_id,
            "project_id": project_id,
            "workflow": prompt["workflow"],
            "state": "PREPARING",
            "seed": int(seed),
            "camera_motion": normalized_motion,
            "generation_parameters": params,
            "runtime": "native" if self.runtime_adapter else "mock",
            "created_at": self.store.timestamp(),
            "started_at": now,
            "elapsed": 0.0,
            "stages": ["PREPARING"],
            "package_built": False,
            "output_path": "",
            "source_output_path": "",
            "failure_reason": "",
            "prompt_hash": prompt["prompt_hash"],
            "cancelled": False,
            "progress": 0.0,
            "current_stage": "准备参考图",
            "step": None,
            "total_steps": None,
            "eta_seconds": None,
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
            "from": previous_project_state,
            "to": "GPU_RUNNING",
            "detail": {"job_id": job_id, "seed": seed, "risk_reviewed": True,
                       "runtime": job["runtime"]},
        })

        if self.runtime_adapter:
            request = self._build_request(project_id, project, prompt, approved,
                                          params, normalized_motion)
            self.runtime_adapter.progress_callback = lambda event: self._record_progress(
                project_id, job_id, event)
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
        if job.get("runtime") == "mock" and not self.allow_mock_jobs:
            return _decorate_job(_mock_runtime_blocked_job(job))
        if job.get("runtime") == "native":
            if job["state"] in ("COMPLETED", "FAILED", "GPU_FAILED", "CANCELLED"):
                if job["state"] == "COMPLETED" and not _real_output_exists(
                        self.store, project_id, job):
                    return _decorate_job(_real_output_missing_job(
                        self.store, project_id, job))
                return _decorate_job(job)
            elapsed = max(0.0, self.clock() - float(job["started_at"]))
            job["elapsed"] = round(elapsed, 3)
            # Runtime events, not elapsed wall-clock thresholds, own the
            # current stage.  If Comfy has not supplied an authoritative
            # event yet, keep the last durable state.
            return _decorate_job(job)
        elapsed = max(0.0, self.clock() - float(job["started_at"]))
        return _decorate_job(self._apply_elapsed(project_id, job, elapsed))

    def get_job_detail(self, job_id: str) -> Dict[str, Any]:
        project_id, job = self.store.find_job(job_id)
        project = self.store.load_project(project_id)
        refs = [r for r in self.store.load_references(project_id).values()
                if r.get("state") == "APPROVED"]
        prompt = self.store.load_prompt(project_id) or {}
        detail = (_decorate_job(_mock_runtime_blocked_job(job))
                  if job.get("runtime") == "mock" and not self.allow_mock_jobs
                  else _decorate_job(job))
        if job.get("runtime") == "native" and job.get("state") == "COMPLETED" \
                and not _real_output_exists(self.store, project_id, job):
            detail = _decorate_job(_real_output_missing_job(
                self.store, project_id, job))
        detail.update({
            "project": {"id": project_id, "name": project.get("name", "")},
            "reference": ({
                "asset_id": refs[0].get("id"),
                "filename": refs[0].get("filename"),
                "preview_url": f"/api/assets/{refs[0].get('id')}/content?v={refs[0].get('sha256') or refs[0].get('version', 1)}",
            } if refs else None),
            "prompt_summary": str(prompt.get("prompt", ""))[:280],
            "parameters": dict(job.get("generation_parameters") or {}),
            "technical_details": {
                "failure_code": detail.get("failure_code", ""),
                "failure_reason": detail.get("technical_details", detail.get("failure_reason", "")),
                "runtime": detail.get("runtime", ""),
                "workflow": detail.get("workflow", ""),
                "output_path": detail.get("output_path", ""),
                "source_output_path": detail.get("source_output_path", ""),
            },
        })
        return detail

    def retry_job(self, job_id: str) -> Dict[str, Any]:
        project_id, job = self.store.find_job(job_id)
        effective_state = job.get("state")
        if (job.get("runtime") == "mock" and not self.allow_mock_jobs
                and effective_state == "COMPLETED"):
            effective_state = "FAILED"
        if effective_state not in ("FAILED", "GPU_FAILED", "CANCELLED"):
            raise ValueError("只有已结束的失败任务可以重试")
        params = dict(job.get("generation_parameters") or {})
        return self.submit_job(
            project_id,
            seed=int(job.get("seed", params.get("seed", 42))),
            risk_reviewed=True,
            generation_parameters=params,
            camera_motion=job.get("camera_motion"),
        )

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
        if job["state"] in ("COMPLETED", "FAILED", "GPU_FAILED", "CANCELLED"):
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
            camera_motion=camera_motion or normalize_camera_motion(prompt["workflow"]),
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
            output_spec={"container": "mp4", "codec": "h264", "fps": params["fps"],
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
            self._stage_refs_to_comfy_input(project_id, request)
            snapshot = self.runtime_adapter.generate(request)
            # re-read the latest record: user may have cancelled mid-run
            job = self.store.load_jobs(project_id).get(job_id) or job
            if job.get("cancelled") or job["state"] == "CANCELLED":
                return
            output = self.runtime_adapter.get_output(snapshot["job_id"])
            self.output_api.build_real_output_package(
                project_id, job, output, request)
            package_video = self.store.package_dir(project_id) / "output" / "video.mp4"
            job["output_path"] = str(package_video)
            job["source_output_path"] = str(output.get("video_path", ""))
            job["state"] = "COMPLETED"
            job["progress"] = 100.0
            job["current_stage"] = "保存视频"
            job["eta_seconds"] = 0.0
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
            message = str(exc).lower()
            runtime_mismatch = "missing_node_type" in message or "node type" in message and "not found" in message
            category, friendly = _classify_failure(exc, runtime_mismatch=runtime_mismatch)
            job["state"] = "GPU_FAILED" if category == "GPU_ERROR" else "FAILED"
            job["failure_code"] = category
            job["error_category"] = category
            job["user_message"] = friendly
            job["technical_details"] = f"{type(exc).__name__}: {exc}"
            if category == "COMFYUI_CRASHED":
                job["technical_details"] = (
                    "COMFYUI_NATIVE_CRASH: " + job["technical_details"]
                )
            # Keep the persisted technical reason for diagnostics/backward
            # compatibility; normal UI reads friendly_reason instead.
            job["failure_reason"] = job["technical_details"]
            job["stages"].append(job["state"])
            self._save_job(project_id, job)
            self._sync_project_failed(project_id, job, job["technical_details"])

    def _record_progress(self, project_id: str, job_id: str,
                         event: Dict[str, Any]) -> None:
        job = self.store.load_jobs(project_id).get(job_id)
        if not job or job.get("state") in ("FAILED", "GPU_FAILED", "CANCELLED", "COMPLETED"):
            return
        job["current_stage"] = event.get("stage") or job.get("current_stage", "执行工作流")
        state = {"准备参考图": "PREPARING", "加载 H3 模型": "LOADING_MODEL",
                 "视频采样": "SAMPLING", "视频解码": "DECODING",
                 "保存视频": "EXPORTING", "生成失败": "FAILED"}.get(
                     job["current_stage"], "LOADING_MODEL")
        if state not in ("FAILED",) and job.get("state") not in ("PREPARING", state):
            job["state"] = state
            if state not in job["stages"]:
                job["stages"].append(state)
        job["step"] = event.get("step")
        job["total_steps"] = event.get("total_steps")
        if event.get("progress") is not None:
            job["progress"] = round(float(event["progress"]), 2)
            job["eta_seconds"] = estimate_eta(float(job.get("elapsed") or 0), job["progress"])
        self._save_job(project_id, job)

    def _stage_refs_to_comfy_input(self, project_id: str, request: Any) -> Dict[str, str]:
        """Stage only the request's approved references into active ComfyUI input.

        Studio keeps the original upload in its project store for preview and
        audit.  ComfyUI, however, accepts an input filename relative to its
        own input root.  Use a deterministic ASCII filename and verify both
        the local destination and the live ComfyUI view endpoint before the
        request reaches ``/prompt``.  This avoids Unicode/path mismatches and
        prevents a misleading GPU/Comfy execution failure.
        """
        if not self.comfy_input_dir:
            raise InputStagingError("ComfyUI input root is not configured")
        dest_dir = Path(self.comfy_input_dir)
        if "<NATIVE_ROOT>" in str(dest_dir):
            raise RuntimePathError(f"未解析的 ComfyUI input 路径: {dest_dir}")
        dest_dir.mkdir(parents=True, exist_ok=True)

        stored_refs = self.store.load_references(project_id)
        request_refs = (request.reference_assets if hasattr(request, "reference_assets")
                        else request.get("reference_assets") or [])
        staged: Dict[str, str] = {}
        for request_ref in request_refs:
            asset_id = str(request_ref.get("asset_id") or "").strip()
            ref = stored_refs.get(asset_id) if asset_id else None
            if not ref or ref.get("state") != "APPROVED":
                raise InputStagingError(
                    f"approved reference is unavailable: {asset_id or request_ref}")
            src = Path(ref["stored_path"]) if ref.get("stored_path") else None
            if src is None or not src.is_file():
                raise InputStagingError(
                    f"approved reference file missing: {src or ref.get('filename')}")

            suffix = Path(ref.get("filename") or src.name).suffix.lower()
            if not suffix:
                suffix = src.suffix.lower() or ".png"
            staged_name = unique_comfy_filename(ref, src)
            destination = dest_dir / staged_name
            shutil.copy2(src, destination)
            if not destination.is_file() or destination.stat().st_size <= 0:
                raise InputStagingError(
                    f"reference staging produced no readable file: {destination}")

            checker = getattr(getattr(self.runtime_adapter, "client", None),
                              "input_file_available", None)
            if checker is not None and not checker(staged_name):
                raise InputStagingError(
                    f"ComfyUI cannot see staged reference {staged_name} in {dest_dir}")

            request_ref["path_or_ref"] = staged_name
            staged[asset_id] = staged_name
        return staged

    # ------------------------------------------------------------------ #
    def _apply_elapsed(self, project_id: str, job: Dict[str, Any],
                       elapsed: float) -> Dict[str, Any]:
        if job["state"] in ("COMPLETED", "FAILED", "GPU_FAILED", "CANCELLED"):
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
        # A Job failure is historical Job state.  It must not poison the
        # editable Study or block a new intent/reference/prompt cycle.
        approved = any(r.get("state") == "APPROVED"
                       for r in self.store.load_references(project_id).values())
        intent = self.store.load_intent(project_id)
        prompt = self.store.load_prompt(project_id)
        if approved and prompt and prompt.get("verified", {}).get("pass"):
            project["state"] = "USER_CONFIRM"
        elif approved and intent:
            project["state"] = "PROMPT_REVIEW"
        elif approved:
            project["state"] = "REFERENCE_APPROVED"
        self.store.save_project(project)
        self.store.append_audit(project_id, {
            "actor": "runtime", "event": "job_failed_study_preserved",
            "from": "GPU_RUNNING", "to": project.get("state"),
            "detail": {"job_id": job["id"], "reason": reason,
                        "job_state_only": True},
        })

    def _save_job(self, project_id: str, job: Dict[str, Any]) -> None:
        jobs = self.store.load_jobs(project_id)
        jobs[job["id"]] = job
        self.store.save_jobs(project_id, jobs)


def _real_output_exists(store: Any, project_id: str,
                        job: Dict[str, Any]) -> bool:
    """Return whether a persisted native completion has a real MP4 artifact."""
    candidate = str(job.get("output_path") or "").strip()
    path = Path(candidate) if candidate else (
        store.package_dir(project_id) / "output" / "video.mp4")
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def _real_output_missing_job(store: Any, project_id: str,
                             job: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize an invalid persisted native completion for public APIs."""
    out = dict(job)
    output_path = str(job.get("output_path") or (
        store.package_dir(project_id) / "output" / "video.mp4"))
    out["state"] = "FAILED"
    out["failure_code"] = "OUTPUT_ERROR"
    out["error_category"] = "OUTPUT_ERROR"
    out["user_message"] = "视频输出不存在或无效，任务未完成。"
    out["technical_details"] = (
        "OUTPUT_ERROR: persisted COMPLETED state has no non-empty real MP4: "
        + output_path
    )
    out["failure_reason"] = out["technical_details"]
    out["package_built"] = False
    out["output_path"] = output_path
    return out


def _mock_runtime_blocked_job(job: Dict[str, Any]) -> Dict[str, Any]:
    """Expose legacy setup/mock records as non-generation results.

    Older setup-mode records may say COMPLETED even though they only contain a
    textual placeholder.  Do not rewrite user history here; normalize the
    public record so the UI cannot offer a fake output or call it a success.
    """
    out = dict(job)
    if out.get("state") == "COMPLETED":
        out["state"] = "FAILED"
        out["failure_code"] = "REAL_RUNTIME_REQUIRED"
        out["error_category"] = "ENVIRONMENT_ERROR"
        out["user_message"] = "当前任务未执行真实视频生成，请先启动 Native ComfyUI。"
        out["technical_details"] = (
            "This job was created in setup/mock mode; no real MP4 was generated."
        )
        out["failure_reason"] = out["technical_details"]
    return out


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


def _classify_failure(exc: Exception, *, runtime_mismatch: bool = False) -> tuple[str, str]:
    """Map execution failures to product categories and readable messages."""
    if isinstance(exc, RuntimePathError) or runtime_mismatch:
        return "ENVIRONMENT_ERROR", "运行环境路径无效，请前往环境修复。"
    if isinstance(exc, FileNotFoundError):
        return "INPUT_ERROR", "参考图文件不可用，请重新上传并批准参考图。"
    if isinstance(exc, ComfyUIOfflineError):
        return "COMFYUI_CRASHED", "生成引擎意外退出，请重新启动服务。"
    if isinstance(exc, WorkflowParameterError):
        return "WORKFLOW_PARAMETER_ERROR", "参数配置错误，请检查当前视频类型的设置。"
    name = type(exc).__name__.lower()
    message = str(exc).lower()
    if ("camera_motion" in message or "not supported" in message
            or "parameter" in message or "invalid" in message):
        return "WORKFLOW_PARAMETER_ERROR", "参数配置错误，请检查当前视频类型的设置。"
    if "workflow" in message or "workflow" in name:
        return "WORKFLOW_ERROR", "工作流文件不可用，请前往环境修复。"
    if "model" in message and ("load" in message or "missing" in message):
        return "MODEL_ERROR", "模型组件不可用，请前往环境修复。"
    if "cuda" in message or "out of memory" in message or "oom" in message:
        return "GPU_ERROR", "GPU 执行失败，请检查显存和硬件支持。"
    if "comfyui" in message or "prompt_id" in message or "offline" in message:
        return "COMFYUI_ERROR", "ComfyUI 执行失败，请查看任务详情。"
    # A runtime exception with no filesystem/signature evidence remains a
    # genuine execution failure; keep the historical GPU_FAILED lifecycle only
    # for this final unknown-runtime category.
    return "GPU_ERROR", "GPU 执行失败，请查看任务详情。"


def _decorate_job(job: Dict[str, Any]) -> Dict[str, Any]:
    """Add stable UI fields without changing the persisted lifecycle enum."""
    out = dict(job)
    category = out.get("error_category") or out.get("failure_code", "")
    if not category and "FileNotFoundError" in str(out.get("failure_reason", "")):
        category = "ENVIRONMENT_ERROR"
    out["error_category"] = category
    out["status_label"] = {
        "COMPLETED": "完成", "PREPARING": "准备中", "LOADING_MODEL": "加载模型",
        "SAMPLING": "生成中", "ENCODING": "编码中", "DECODING": "视频解码",
        "EXPORTING": "导出中",
        "FAILED": "生成失败", "GPU_FAILED": "生成失败", "CANCELLED": "已取消",
    }.get(out.get("state"), "生成中")
    if out.get("user_message"):
        out["friendly_reason"] = out["user_message"]
    elif category == "ENVIRONMENT_ERROR":
        out["friendly_reason"] = "运行环境路径错误"
    elif category == "INPUT_ERROR":
        out["friendly_reason"] = "参考图不可用"
    elif category == "GPU_ERROR":
        out["friendly_reason"] = "显存或 GPU 执行失败"
    elif category:
        out["friendly_reason"] = {
            "WORKFLOW_ERROR": "工作流不可用", "MODEL_ERROR": "模型不可用",
        "COMFYUI_ERROR": "ComfyUI 执行失败", "COMFYUI_CRASHED": "生成引擎意外退出",
        "OUTPUT_ERROR": "输出失败", "WORKFLOW_PARAMETER_ERROR": "参数配置错误",
        }.get(category, "生成失败")
    else:
        out["friendly_reason"] = ""
    return out
