"""Isolated Advanced A1 GPU acceptance runner.

This module is intentionally not imported by the production selector.  It
reuses the native adapter's transport, observation, output validation, Job
state transitions, and handoff snapshot while allowing one explicitly chosen
EXPERIMENTAL_V2 graph to be exercised for acceptance evidence.
"""

from __future__ import annotations

import copy
import hashlib
import re
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Mapping

from apps.architect_video_studio.mock_api.job_api import JobAPI
from apps.architect_video_studio.mock_api.output_api import OutputAPI
from apps.architect_video_studio.mock_api.store import StudioStore
from apps.architect_video_studio.state_machine.machine import ProjectStateMachine
from runtime.advanced_workflows import (
    ADVANCED_API_PATH,
    ADVANCED_WORKFLOW_ID,
    canonical_advanced_workflow_sha256,
    load_advanced_api_workflow,
    validate_advanced_workflow,
)
from runtime.adapters.comfyui_client import ComfyUIClient
from runtime.adapters.native_runtime_adapter import NativeRuntimeAdapter, length_for
from runtime.adapters.runtime_adapter import VideoGenerationRequest
from runtime.adapters.runtime_paths import RuntimePathContract
from runtime.generation_capabilities import estimate_generation_range


class AdvancedAcceptanceError(RuntimeError):
    """Raised when the bounded A1 acceptance setup is not safe to run."""


def _managed_ffmpeg_path(runtime_paths: RuntimePathContract) -> str | None:
    """Resolve the bundled validator without relying on host PATH."""
    if runtime_paths.ffmpeg and runtime_paths.ffmpeg.is_file():
        return str(runtime_paths.ffmpeg)
    embedded = getattr(runtime_paths, "embedded_python", None)
    if embedded and Path(embedded).is_file():
        try:
            result = subprocess.run(
                [str(embedded), "-c", "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"],
                capture_output=True, text=True, timeout=15,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            candidate = (result.stdout or "").strip().splitlines()[-1]
            if result.returncode == 0 and Path(candidate).is_file():
                return candidate
        except (OSError, subprocess.SubprocessError, IndexError):
            pass
    return None


class AdvancedAcceptanceRuntimeAdapter(NativeRuntimeAdapter):
    """Native transport with an explicit, non-production V2 binder."""

    def preflight(self) -> dict[str, Any]:
        if self.runtime_paths is not None:
            self.runtime_paths.validate_for_job()
        health = self.client.health_check()
        object_info = self.client.object_info()
        validation = validate_advanced_workflow(object_info=object_info)
        if not validation["ready"]:
            raise AdvancedAcceptanceError(
                "advanced workflow preflight failed: "
                + "; ".join(validation["errors"])
            )
        return {"ready": True, "health": health, "workflow": validation}

    def prepare(self, request: Any) -> Dict[str, Any]:
        data = request.to_dict() if isinstance(request, VideoGenerationRequest) else dict(request)
        if data.get("workflow_id") != ADVANCED_WORKFLOW_ID:
            raise AdvancedAcceptanceError("acceptance runner only accepts the V2 workflow")
        refs = data.get("reference_assets") or []
        if len(refs) != 1 or not refs[0].get("path_or_ref"):
            raise AdvancedAcceptanceError("V2 I2VA acceptance requires one staged reference")
        params = dict(data.get("generation_parameters") or {})
        resolution = str(params.get("resolution") or "1344x768")
        try:
            width, height = (int(part) for part in resolution.lower().split("x", 1))
            duration = float(params.get("duration", 4.0))
            fps = int(params.get("fps", 24))
            steps = int(params.get("steps", 50))
            seed = int(params.get("seed", 42))
        except (TypeError, ValueError) as exc:
            raise AdvancedAcceptanceError("invalid bounded acceptance parameters") from exc
        if fps != 24 or not 4.0 <= duration <= 15.0 or steps <= 0:
            raise AdvancedAcceptanceError("acceptance parameters are outside the H3 contract")

        payload = copy.deepcopy(load_advanced_api_workflow())
        payload["1"]["inputs"]["image"] = str(refs[0]["path_or_ref"])
        payload["6"]["inputs"].update({
            "prompt": str((data.get("prompt_payload") or {}).get("prompt") or ""),
            "width": width,
            "height": height,
            "length": length_for(duration, fps),
        })
        payload["8"]["inputs"]["steps"] = steps
        payload["9"]["inputs"]["noise_seed"] = seed
        payload["14"]["inputs"]["fps"] = float(fps)
        payload["15"]["inputs"]["filename_prefix"] = (
            "video/06_Advanced_Architecture_Camera_V2_B"
        )
        live = self.client.object_info()
        validation = validate_advanced_workflow(object_info=live)
        if not validation["ready"]:
            raise AdvancedAcceptanceError("advanced workflow became invalid during bind")
        digest = canonical_advanced_workflow_sha256(payload)
        return {
            "job_id": f"advanced-{uuid.uuid4().hex[:12]}",
            "study_id": data["study_id"],
            "workflow_id": ADVANCED_WORKFLOW_ID,
            "workflow_asset": str(ADVANCED_API_PATH),
            "translated_payload": payload,
            "execution_workflow_sha256": digest,
            "binding": {
                "source_of_truth": str(ADVANCED_API_PATH),
                "classification": "EXPERIMENTAL_V2",
                "production_selector_enabled": False,
            },
            "control": {
                "submit_timeout_seconds": 60.0,
                "poll_interval_seconds": 5.0,
                "history_timeout_seconds": 1800.0,
            },
        }


def _new_job(store: StudioStore, project_id: str,
             request: VideoGenerationRequest, source_job: Mapping[str, Any]) -> dict[str, Any]:
    params = dict(request.generation_parameters)
    now = time.time()
    job_id = store.new_id("job")
    job = {
        "id": job_id,
        "project_id": project_id,
        "workflow": ADVANCED_WORKFLOW_ID,
        "state": "PREPARING",
        "seed": int(params["seed"]),
        "camera_motion": request.camera_motion,
        "generation_parameters": params,
        "runtime": "native",
        "created_at": store.timestamp(),
        "started_at": now,
        "elapsed": 0.0,
        "estimated_time": estimate_generation_range(
            store.load_jobs(project_id).values(),
            workflow_id=ADVANCED_WORKFLOW_ID,
            duration=params["duration"], fps=params["fps"],
            resolution=params["resolution"], steps=params["steps"], cold_start=True,
        ),
        "stages": ["PREPARING"],
        "package_built": False,
        "output_path": "",
        "source_output_path": "",
        "runtime_output_path": "",
        "final_output_path": "",
        "failure_reason": "",
        "prompt_hash": request.prompt_payload["prompt_hash"],
        "cancelled": False,
        "progress": None,
        "current_stage": "准备参考图",
        "step": None,
        "total_steps": None,
        "eta_seconds": None,
        "prompt_id": None,
        "submission_state": "NOT_STARTED",
        "execution_workflow_sha256": None,
        "lifecycle_state": "CREATED",
        "progress_message": "准备参考图",
        "acceptance_arm": "B",
        "acceptance_source_job_id": str(source_job.get("id") or ""),
    }
    jobs = store.load_jobs(project_id)
    jobs[job_id] = job
    store.save_jobs(project_id, jobs)
    project = store.load_project(project_id)
    if project.get("state") == "COMPLETED":
        machine = ProjectStateMachine("COMPLETED")
        machine.transition("start_new_generation", actor="architect",
                           reason="start isolated A1 V2 B-arm acceptance")
        project["state"] = machine.state
    if project.get("state") != "USER_CONFIRM":
        raise AdvancedAcceptanceError(
            f"acceptance requires USER_CONFIRM or COMPLETED Study, got {project.get('state')}"
        )
    machine = ProjectStateMachine("USER_CONFIRM")
    machine.transition("confirm_generate", actor="architect",
                       reason=f"submit isolated A1 B-arm job {job_id}")
    project["state"] = machine.state
    store.save_project(project)
    store.append_audit(project_id, {
        "actor": "architect", "event": "advanced_a1_b_arm_started",
        "from": "USER_CONFIRM", "to": "GPU_RUNNING",
        "detail": {"job_id": job_id, "workflow": ADVANCED_WORKFLOW_ID,
                    "arm": "B", "source_job_id": str(source_job.get("id") or "")},
    })
    return job


def run_advanced_b_arm(*, data_root: Path, project_id: str,
                       source_job_id: str, runtime_paths: RuntimePathContract,
                       client: ComfyUIClient | None = None) -> dict[str, Any]:
    """Run exactly one V2 B-arm job and return only sanitized evidence."""
    store = StudioStore(Path(data_root))
    project = store.load_project(project_id)
    jobs = store.load_jobs(project_id)
    source = jobs.get(source_job_id)
    if not source or source.get("state") != "COMPLETED" or source.get("runtime") != "native":
        raise AdvancedAcceptanceError("A source job must be an existing native completed Job")
    ref_id = project.get("current_reference_asset_id")
    ref = store.load_references(project_id).get(ref_id)
    if not ref or ref.get("state") != "APPROVED":
        raise AdvancedAcceptanceError("current reference must be approved")
    params = dict(source.get("generation_parameters") or {})
    params.update({"seed": int(source.get("seed", params.get("seed", 42)))})
    static_prompt = load_advanced_api_workflow()["6"]["inputs"]["prompt"]
    prompt_hash = hashlib.sha256(static_prompt.encode("utf-8")).hexdigest()
    request = VideoGenerationRequest(
        study_id=project_id,
        reference_assets=[{
            "asset_id": ref["id"], "role": ref.get("role", "first_frame"),
            "path_or_ref": ref.get("stored_path") or ref.get("filename", "ref.png"),
            "sha256": ref.get("sha256"),
        }],
        workflow_id=ADVANCED_WORKFLOW_ID,
        camera_motion="slow_push",
        generation_parameters=params,
        prompt_payload={
            "mode": "I2VA", "prompt": static_prompt,
            "prompt_hash": prompt_hash,
        },
        output_spec={"container": "mp4", "codec": "h264", "fps": params["fps"],
                     "resolution": params["resolution"], "report_format": "json"},
        gates={"reference_approved": True, "intent_confirmed": True,
               "prompt_verified": True, "risk_reviewed": True},
    )
    comfy = client or ComfyUIClient(
        output_root=str(runtime_paths.output_root), strict_output=True,
        ffmpeg_path=_managed_ffmpeg_path(runtime_paths),
        health_timeout=5.0, submission_timeout=60.0, metadata_timeout=10.0,
        observation_timeout=15.0, output_timeout=30.0,
    )
    adapter = AdvancedAcceptanceRuntimeAdapter(
        client=comfy, comfy_input_dir=str(runtime_paths.input_root),
        production_binding=False, runtime_paths=runtime_paths,
    )
    adapter.preflight()
    output_api = OutputAPI(store, allow_mock_outputs=False, runtime_paths=runtime_paths)
    job_api = JobAPI(store, output_api=output_api, runtime_adapter=adapter,
                     allow_mock_jobs=False, comfy_input_dir=str(runtime_paths.input_root),
                     runtime_paths=runtime_paths)
    job = _new_job(store, project_id, request, source)
    job_id = job["id"]
    adapter.progress_callback = lambda event: job_api._record_progress(project_id, job_id, event)
    adapter.submission_callback = lambda info: job_api._record_submission(project_id, job_id, info)
    job_api._run_real_job(project_id, job_id, request)
    final_job = store.load_jobs(project_id)[job_id]
    if final_job.get("state") != "COMPLETED" or final_job.get("lifecycle_state") != "SUCCEEDED":
        raise AdvancedAcceptanceError("B-arm did not reach COMPLETED/SUCCEEDED")
    manifest = output_api.get_result(job_id)
    return {
        "job_id": job_id,
        "workflow": ADVANCED_WORKFLOW_ID,
        "arm": "B",
        "state": final_job.get("state"),
        "lifecycle_state": final_job.get("lifecycle_state"),
        "delivery_state": final_job.get("delivery_state"),
        "prompt_id": final_job.get("prompt_id"),
        "snapshot_id": final_job.get("workflow_snapshot_id"),
        "workflow_hash": final_job.get("workflow_hash"),
        "execution_workflow_sha256": final_job.get("execution_workflow_sha256"),
        "parameters": {
            key: params.get(key)
            for key in ("duration", "fps", "resolution", "steps", "seed", "quality")
        },
        "output": {
            "available": manifest["output"]["available"],
            "mime_type": manifest["output"]["mime_type"],
            "size_bytes": manifest["output"]["size_bytes"],
            "ffprobe": manifest.get("ffprobe"),
        },
    }


def finalize_reconciled_b_arm(*, data_root: Path, project_id: str,
                              job_id: str, runtime_paths: RuntimePathContract,
                              client: ComfyUIClient | None = None) -> dict[str, Any]:
    """Finish the already-submitted B Job after an observation timeout.

    This function is deliberately recovery-only: it requires a persisted
    prompt id from the original Job and never calls ``/prompt``.
    """
    store = StudioStore(Path(data_root))
    project_id_found, job = store.find_job(job_id)
    if project_id_found != project_id or job.get("acceptance_arm") != "B":
        raise AdvancedAcceptanceError("job is not the bounded A1 B-arm Job")
    if job.get("state") == "COMPLETED":
        return {"job_id": job_id, "state": "COMPLETED", "recovered": False}
    prompt_id = str(job.get("prompt_id") or "")
    if not prompt_id:
        prompt_id = re.search(
            r"prompt_id ([0-9a-f-]+)", str(job.get("technical_details") or "")
        ).group(1) if re.search(
            r"prompt_id ([0-9a-f-]+)", str(job.get("technical_details") or "")
        ) else ""
    if not prompt_id:
        raise AdvancedAcceptanceError("recovery requires the original prompt id")
    comfy = client or ComfyUIClient(
        output_root=str(runtime_paths.output_root), strict_output=True,
        ffmpeg_path=_managed_ffmpeg_path(runtime_paths),
        health_timeout=5.0, submission_timeout=60.0, metadata_timeout=10.0,
        observation_timeout=15.0, output_timeout=30.0,
    )
    history = comfy.get_history(prompt_id)
    status = history.get("status") or {}
    if status.get("status_str") != "success" or not status.get("completed"):
        raise AdvancedAcceptanceError("original B-arm history is not successful")
    refs = store.load_references(project_id)
    project = store.load_project(project_id)
    ref = refs.get(project.get("current_reference_asset_id"))
    if not ref or ref.get("state") != "APPROVED":
        raise AdvancedAcceptanceError("current reference is no longer approved")
    params = dict(job.get("generation_parameters") or {})
    static_prompt = load_advanced_api_workflow()["6"]["inputs"]["prompt"]
    request = VideoGenerationRequest(
        study_id=project_id,
        reference_assets=[{"asset_id": ref["id"], "role": ref.get("role", "first_frame"),
                           "path_or_ref": ref.get("stored_path") or ref.get("filename", "ref.png"),
                           "sha256": ref.get("sha256")}],
        workflow_id=ADVANCED_WORKFLOW_ID, camera_motion="slow_push",
        generation_parameters=params,
        prompt_payload={"mode": "I2VA", "prompt": static_prompt,
                        "prompt_hash": job.get("prompt_hash") or hashlib.sha256(
                            static_prompt.encode("utf-8")).hexdigest()},
        output_spec={"container": "mp4", "codec": "h264", "fps": params["fps"],
                     "resolution": params["resolution"], "report_format": "json"},
        gates={"reference_approved": True, "intent_confirmed": True,
               "prompt_verified": True, "risk_reviewed": True},
    )
    output = comfy.collect_output(history, job_id, ADVANCED_WORKFLOW_ID, {
        "study_id": project_id, "workflow_id": ADVANCED_WORKFLOW_ID,
        "camera_motion": request.camera_motion,
        "resolution": params.get("resolution"), "fps": params.get("fps"),
        "duration": params.get("duration"), "quality": params.get("quality"),
        "seed": params.get("seed"), "prompt_hash": request.prompt_payload["prompt_hash"],
    })
    output_api = OutputAPI(store, allow_mock_outputs=False, runtime_paths=runtime_paths)
    output_api.build_real_output_package(project_id, job, output, request)
    runtime_output = str(output["video_path"])
    job["prompt_id"] = prompt_id
    job["submission_state"] = "ACKNOWLEDGED"
    job["failure_code"] = ""
    job["error_category"] = ""
    job["failure_reason"] = ""
    job["technical_details"] = ""
    job["runtime_output_path"] = runtime_output
    job["source_output_path"] = runtime_output
    job["output_path"] = runtime_output
    try:
        final_video = output_api.copy_to_study_output(project_id, job, runtime_output)
    except Exception as exc:  # delivery is separate from generation
        job["delivery_state"] = "OUTPUT_DELIVERY_FAILED"
        job["delivery_error"] = f"{type(exc).__name__}: {exc}"
    else:
        job["final_output_path"] = str(final_video)
        job["output_path"] = str(final_video)
        job["delivery_state"] = "DELIVERED"
        job["delivery_error"] = ""
    job["state"] = "COMPLETED"
    job["lifecycle_state"] = "SUCCEEDED"
    job["progress"] = 100.0
    job["current_stage"] = "保存视频"
    job["eta_seconds"] = 0.0
    job.setdefault("stages", []).append("COMPLETED")
    job["package_built"] = True
    job["finished_at"] = store.timestamp()
    job["active"] = False
    job["is_active"] = False
    store.save_jobs(project_id, {**store.load_jobs(project_id), job_id: job})
    job_api = JobAPI(store, output_api=output_api, runtime_adapter=None,
                     allow_mock_jobs=False, runtime_paths=runtime_paths)
    job_api._sync_project_complete(project_id, job)
    manifest = output_api.get_result(job_id)
    return {
        "job_id": job_id, "workflow": ADVANCED_WORKFLOW_ID, "arm": "B",
        "state": job["state"], "lifecycle_state": job["lifecycle_state"],
        "delivery_state": job.get("delivery_state"), "prompt_id": prompt_id,
        "snapshot_id": job.get("workflow_snapshot_id"),
        "workflow_hash": job.get("workflow_hash"),
        "execution_workflow_sha256": job.get("execution_workflow_sha256"),
        "parameters": {key: params.get(key) for key in
                       ("duration", "fps", "resolution", "steps", "seed", "quality")},
        "output": {"available": manifest["output"]["available"],
                   "mime_type": manifest["output"]["mime_type"],
                   "size_bytes": manifest["output"]["size_bytes"],
                   "ffprobe": manifest.get("ffprobe")},
        "recovered_after_observation_timeout": True,
    }


__all__ = [
    "AdvancedAcceptanceError", "AdvancedAcceptanceRuntimeAdapter",
    "finalize_reconciled_b_arm", "run_advanced_b_arm",
]
