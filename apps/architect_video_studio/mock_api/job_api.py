"""Job API (PATCH2.7-D: UI -> Runtime binding).

Endpoint contract unchanged. Internal execution switches from clock-based mock
simulation to the real RuntimeAdapter when one is configured:

    submit_job -> builds VideoGenerationRequest -> adapter thread (async)
    get_job    -> poll current state (mock thresholds or real stage mapping)
    cancel     -> terminal CANCELLED, no auto retry

The UI never builds a ComfyUI payload; only the RuntimeAdapter does.
"""

from __future__ import annotations

import copy
import threading
import time
import shutil
import hashlib
import json
import os
import inspect
import math
import re
from typing import Any, Callable, Dict, List, Mapping, Optional
from pathlib import Path
from urllib.parse import urlsplit

from ..state_machine.machine import (
    JobStateMachine,
    ProjectStateMachine,
)
from .store import StudioStore
from .job_state import (
    is_job_active, is_job_terminal, is_job_recoverable,
    normalize_terminal_record, terminal_elapsed_seconds,
)
from .study_state import build_study_state
from ._paths import REPO_ROOT
from runtime.adapters.runtime_paths import RuntimePathContract, RuntimePathError
from runtime.adapters.comfyui_client import (
    ComfyUICommunicationTimeout,
    ComfyUIOfflineError,
    ComfyProtocolError,
    GenerationTimeoutError,
)
from runtime.product_hardening import unique_comfy_filename
from runtime.product_hardening import estimate_eta
from runtime.a4_profiles import (
    actual_execution_parameters,
    normalize_quality_id,
    resolve_product_parameters,
)
from runtime.reference_contract import (
    REF2VA_DEFAULT_IMAGE_SIZE, REF2VA_IMAGE_SIZE_OPTIONS,
    reference_bindings, ref2va_schema_capabilities,
    resolve_selected_references, selected_ref2va_roles,
)
from runtime.multiframe_guides import (
    GUIDE_ROLE, GuideFrameError, NATIVE_H3_FPS, compile_timeline_guide_prompt,
    resolve_guide_bindings,
)
from runtime.result_pipeline import (
    ResultIdentityError, classify_result_failure, expected_save_video_identity,
    sanitize_result_error, summarize_history_outputs,
)
from runtime.adapters.multiframe_guide_capability import (
    MultiFrameGuideCapabilityAdapter,
)
from runtime.generation_capabilities import (
    estimate_generation_range,
    lifecycle_state,
    validate_workflow_parameters,
    weighted_progress,
)
from runtime.workflow_motion import WorkflowParameterError, normalize_camera_motion

# rough expected real-run duration used to derive UI stages while executing
_EXPECTED_REAL_SECONDS = 900.0

# Comfy observations can arrive out of order. Keep accepted execution state monotonic.
_JOB_STAGE_RANK = {
    "PREPARING": 0,
    "LOADING_MODEL": 1,
    "ENCODING": 2,
    "SAMPLING": 3,
    "DECODING": 4,
    "EXPORTING": 5,
    "COMPLETED": 6,
}


def build_runtime_identity(runtime_target: str, runtime_adapter,
                           preflight_result: Optional[dict] = None) -> dict:
    """Build path-free, durable identity metadata for a Job's Comfy runtime."""
    role = str(runtime_target or "production")
    if role not in {"production", "experimental"}:
        role = "unknown"
    client = getattr(runtime_adapter, "client", None)
    runtime_spec = getattr(runtime_adapter, "runtime_identity_spec", {}) or {}
    backend = "native_comfyui" if client is not None else "mock"
    default_port = 8190 if role == "experimental" else 8189
    base_url = str(getattr(client, "base_url", "") or "")
    try:
        endpoint = urlsplit(base_url)
        port = endpoint.port or default_port
        scheme = endpoint.scheme.lower()
        host = (endpoint.hostname or "").lower()
    except ValueError:
        port = default_port
        scheme = ""
        host = ""

    endpoint_kind = (
        "loopback" if host in {"127.0.0.1", "localhost", "::1"}
        else "remote" if host else "unconfigured"
    )
    endpoint_payload = {"scheme": scheme, "host": host, "port": port}
    endpoint_fingerprint = (
        hashlib.sha256(json.dumps(
            endpoint_payload, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")).hexdigest() if host else None
    )

    result = preflight_result if isinstance(preflight_result, dict) else {}
    health = result.get("health") if isinstance(result.get("health"), dict) else {}
    system = health.get("system") if isinstance(health.get("system"), dict) else {}
    version = (health.get("comfyui_version") or system.get("comfyui_version")
               or getattr(client, "comfyui_version", None)
               or getattr(runtime_adapter, "comfyui_version", None)
               or runtime_spec.get("comfyui_version"))
    version = str(version).strip() if version else None
    if version and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,79}", version):
        version = None

    git_sha = (getattr(client, "comfyui_git_sha", None)
               or getattr(runtime_adapter, "comfyui_git_sha", None))
    git_sha = str(git_sha).strip().lower() if git_sha else None
    if (git_sha and (not 7 <= len(git_sha) <= 64
                     or any(char not in "0123456789abcdef" for char in git_sha))):
        git_sha = None

    output_root_fingerprint = str(
        getattr(client, "output_root_fingerprint", "") or "").strip().lower()
    if not re.fullmatch(r"(?:[0-9a-f]{24}|[0-9a-f]{64})", output_root_fingerprint):
        output_root_fingerprint = None
    default_runtime_id = ("experimental-h3-8190" if role == "experimental"
                          else "production-h3-8189" if role == "production"
                          else f"{backend}:{role}:{endpoint_kind}:{port}")
    runtime_id = str(runtime_spec.get("runtime_id") or default_runtime_id)
    identity = {
        "identity_schema_version": 2,
        "runtime_id": runtime_id,
        "runtime_role": role,
        "target": role,  # Backward-compatible field used by existing recovery code.
        "backend": str(runtime_spec.get("backend") or
                        ("comfyui" if client is not None else "mock")),
        "execution_backend": backend,
        "endpoint_kind": endpoint_kind,
        "port": port,
        "endpoint_fingerprint": endpoint_fingerprint,
        "comfyui_version": version,
        "comfyui_git_sha": (runtime_spec.get("comfyui_git_sha") or git_sha),
        "capabilities": list(runtime_spec.get("capabilities") or []),
        "output_root_fingerprint": output_root_fingerprint,
    }
    identity["runtime_config_fingerprint"] = str(
        runtime_spec.get("config_fingerprint") or hashlib.sha256(json.dumps(
            identity, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")).hexdigest())
    return identity


class InputStagingError(FileNotFoundError):
    """The approved reference is not visible to the active ComfyUI input root."""


class JobAPI:
    def __init__(self, store: StudioStore, output_api=None,
                 clock: Callable[[], float] | None = None,
                 runtime_adapter=None,
                 experimental_runtime_adapter=None,
                 allow_mock_jobs: bool = True,
                 comfy_input_dir: Optional[str] = None,
                 experimental_comfy_input_dir: Optional[str] = None,
                 runtime_paths: Optional[RuntimePathContract] = None,
                 experimental_route_enabled: bool = False,
                 long_form_api=None) -> None:
        self.store = store
        from .output_api import OutputAPI
        self.output_api = output_api or OutputAPI(store)
        self.clock = clock or time.time
        self.runtime_adapter = runtime_adapter  # Optional[RuntimeAdapter]
        self.experimental_runtime_adapter = experimental_runtime_adapter
        self.allow_mock_jobs = bool(allow_mock_jobs)
        self.comfy_input_dir = comfy_input_dir
        self.experimental_comfy_input_dir = experimental_comfy_input_dir
        self.runtime_paths = runtime_paths
        self.experimental_route_enabled = bool(experimental_route_enabled)
        self.long_form_api = long_form_api
        self._threads: Dict[str, threading.Thread] = {}
        self._recovery_locks: Dict[str, threading.Lock] = {}
        self._idle_memory_since: Optional[float] = None
        self._idle_memory_last_probe: float = 0.0
        self._idle_memory_last_release: Optional[float] = None
        self.auto_release_idle_memory = os.environ.get(
            "AVS_AUTO_RELEASE_IDLE_MEMORY", "1").strip().lower() not in ("0", "false", "off")

    @staticmethod
    def _result_identity_for_event(job: dict) -> dict:
        pipeline = job.get("result_pipeline") or {}
        expected = pipeline.get("expected_output_identity") or {}
        prefix = str(expected.get("filename_prefix") or "")
        prefix_digest = hashlib.sha256(prefix.encode("utf-8")).hexdigest() if prefix else ""
        return {
            "node_id": str(expected.get("node_id") or ""),
            "node_type": str(expected.get("node_type") or ""),
            "filename_prefix_sha256": prefix_digest,
            "workflow_sha256": str(job.get("execution_workflow_sha256") or ""),
        }

    def _record_result_event(self, project_id: str, job_id: str,
                             stage: str, status: str, *,
                             error: BaseException | str | None = None,
                             error_code: str = "",
                             candidates: Optional[List[dict]] = None,
                             detail: Optional[dict] = None) -> None:
        """Persist bounded, path-free result-pipeline evidence best-effort."""
        job = self.store.load_jobs(project_id).get(job_id)
        if not job:
            return
        pipeline = dict(job.get("result_pipeline") or {})
        expected = pipeline.get("expected_output_identity") or {}
        clean_candidates = []
        prefix_leaf = Path(str(expected.get("filename_prefix") or "")).name
        for item in (candidates or [])[:32]:
            if not isinstance(item, dict):
                continue
            name = str(item.get("filename") or "")
            name = Path(name.replace("\\", "/")).name
            subfolder = str(item.get("subfolder") or "").replace("\\", "/")
            parts = subfolder.split("/") if subfolder else []
            if (subfolder.startswith("/") or ":" in subfolder
                    or "<PATH>" in sanitize_result_error(subfolder)
                    or any(part in ("", ".", "..") for part in parts)
                    or any(not all(char.isalnum() or char in "_.-" for char in part)
                           for part in parts)):
                subfolder = "<INVALID>"
            clean_candidates.append({
                "node_id": str(item.get("node_id") or "")[:64],
                "field": str(item.get("field") or "")[:24],
                "filename": (name[:240] if prefix_leaf and name.startswith(prefix_leaf)
                             else "<UNMATCHED>"),
                "subfolder": subfolder[:240],
                "type": str(item.get("type") or "")[:32],
                "format": str(item.get("format") or "")[:64],
                "size": item.get("size") if isinstance(item.get("size"), int) else None,
            })
        safe_code = "".join(
            char for char in str(error_code).upper()
            if char.isalnum() or char in "_-")[:80]
        if isinstance(error, ResultIdentityError):
            message = sanitize_result_error(error)
        elif error:
            # Runtime exceptions can embed user prompt text or serialized node
            # inputs. Persist the type/code only; never persist that payload.
            message = f"Result pipeline operation failed ({safe_code or type(error).__name__})."
        else:
            message = ""
        record = {
            "timestamp": self.store.timestamp(),
            "job_id": job_id,
            "prompt_id": str(job.get("prompt_id") or ""),
            "workflow_sha256": str(job.get("execution_workflow_sha256") or ""),
            "runtime_identity": dict(
                (job.get("execution_trace") or {}).get("runtime_identity") or {}),
            "expected_output_identity": self._result_identity_for_event(job),
            "stage": str(stage)[:64],
            "status": str(status)[:24],
            "error_type": (type(error).__name__ if isinstance(error, BaseException) else
                           ("RuntimeError" if error else "")),
            "error_code": safe_code,
            "failure_classification": classify_result_failure(
                safe_code,
                runtime_target=str((job.get("execution_trace") or {}).get(
                    "runtime_identity", {}).get("target") or "")),
            "message": message,
            "observed_output_candidates": clean_candidates,
            "media_probe_status": str(
                ((job.get("execution_trace") or {}).get("delivery") or {}).get("status") or "UNKNOWN"),
            "packaging_status": str(pipeline.get("packaging_status") or "NOT_STARTED"),
            "detail": {k: v for k, v in (detail or {}).items()
                       if k in {"history_status", "output_count", "media_bytes",
                                "media_sha256", "probe_status", "package_built"}},
        }
        try:
            self.store.append_job_result_event(project_id, job_id, record)
        except Exception:
            # The diagnostic journal must never turn a successful generation
            # into a failed one; the Job snapshot remains the primary record.
            pass
        events = list(pipeline.get("events") or [])
        events.append(record)
        pipeline.update({"schema_version": 1, "current_stage": record["stage"],
                         "status": record["status"], "events": events[-40:]})
        if record["stage"] == "COMFY_HISTORY":
            pipeline["history_outputs"] = clean_candidates
        if record["stage"] == "PACKAGING":
            pipeline["packaging_status"] = (
                "RUNNING" if record["status"] == "STARTED" else record["status"])
        job["result_pipeline"] = pipeline
        try:
            self._save_job(project_id, job)
        except Exception:
            # Preserve the original failure in the independent JSONL sidecar.
            pass

    def _reconcile_completed_packaging(self, project_id: str,
                                       job: Dict[str, Any]) -> Dict[str, Any]:
        """Repair packaging bookkeeping only when the Job-bound package proves success."""
        package_media = self.output_api._package_video_path(project_id, job)
        if package_media is None:
            return job

        job_id = str(job.get("id") or "")
        pipeline = dict(job.get("result_pipeline") or {})
        original_events = list(pipeline.get("events") or [])
        snapshot_events = list(original_events)
        sidecar_events = self.store.load_job_result_events(project_id, job_id)

        def event_key(item: dict) -> tuple:
            return (str(item.get("timestamp") or ""),
                    str(item.get("stage") or ""),
                    str(item.get("status") or ""),
                    str(item.get("error_code") or ""))

        known = {event_key(item) for item in snapshot_events if isinstance(item, dict)}
        packaging_events = [item for item in sidecar_events
                            if isinstance(item, dict)
                            and item.get("stage") == "PACKAGING"]
        for item in packaging_events:
            key = event_key(item)
            if key not in known:
                snapshot_events.append(item)
                known.add(key)

        snapshot_packaging_pass = any(
            isinstance(item, dict) and item.get("stage") == "PACKAGING"
            and item.get("status") == "PASS" for item in snapshot_events)
        sidecar_packaging_pass = any(item.get("status") == "PASS"
                                     for item in packaging_events)
        if not snapshot_packaging_pass and not sidecar_packaging_pass:
            self._record_result_event(
                project_id, job_id, "PACKAGING", "PASS",
                detail={"package_built": True,
                        "media_bytes": package_media.stat().st_size})
            return self.store.load_jobs(project_id).get(job_id, job)

        if snapshot_packaging_pass and not sidecar_packaging_pass:
            # The Job snapshot is authoritative if a previous sidecar write
            # failed; preserve its original event identity when backfilling.
            pass_event = next(item for item in snapshot_events
                              if isinstance(item, dict)
                              and item.get("stage") == "PACKAGING"
                              and item.get("status") == "PASS")
            self.store.append_job_result_event(project_id, job_id, pass_event)

        pipeline["events"] = snapshot_events[-40:]
        pipeline["packaging_status"] = "PASS"
        job_needs_save = (
            pipeline.get("packaging_status") !=
            (job.get("result_pipeline") or {}).get("packaging_status")
            or pipeline["events"] != original_events
        )
        if not job_needs_save:
            return job
        job["result_pipeline"] = pipeline
        self._save_job(project_id, job, preserve_result_pipeline=True)
        return self.store.load_jobs(project_id).get(job_id, job)

    def _runtime_output_fingerprint(self, runtime_adapter) -> str:
        client = getattr(runtime_adapter, "client", None)
        return str(getattr(client, "output_root_fingerprint", "") or "")

    def _adapter_for_target(self, runtime_target: str):
        if runtime_target == "production":
            return self.runtime_adapter
        if runtime_target == "experimental":
            return self.experimental_runtime_adapter
        return None

    def _adapter_for_job(self, job: dict):
        return self._adapter_for_target(str(job.get("runtime_target") or "production"))

    @staticmethod
    def _validate_experimental_endpoint(runtime_adapter) -> None:
        """Validate the isolated loopback endpoint independent of route policy."""
        if runtime_adapter is None:
            raise ValueError(
                "EXPERIMENTAL_RUNTIME_UNAVAILABLE: A5 requires the isolated native runtime")
        client = getattr(runtime_adapter, "client", None)
        parts = urlsplit(str(getattr(client, "base_url", "")))
        try:
            port = parts.port
        except ValueError:
            port = None
        if (parts.scheme != "http" or parts.hostname not in {"127.0.0.1", "localhost"}
                or port != 8190 or parts.username or parts.password):
            raise ValueError(
                "EXPERIMENTAL_RUNTIME_IDENTITY_MISMATCH: A5 may use only loopback port 8190")

    def _validate_experimental_target(self, runtime_target: str, runtime_adapter, *,
                                      runtime_id: Optional[str],
                                      execution_purpose: Optional[str],
                                      requires_guides: bool,
                                      director_execution: Optional[Mapping[str, Any]] = None,
                                      requires_ref2va: bool = False) -> None:
        if runtime_target != "experimental":
            if runtime_id not in (None, "", "production-h3-8189"):
                raise ValueError("RUNTIME_IDENTITY_MISMATCH: production runtime ID rejected")
            if execution_purpose in {"A5_EXPERIMENTAL_VALIDATION",
                                     "A6_REF2VA_VALIDATION",
                                     "A7_DIRECTOR_VALIDATION"}:
                raise ValueError("EXPERIMENTAL_PURPOSE_TARGET_MISMATCH")
            if requires_ref2va:
                raise ValueError("REF2VA_EXPERIMENTAL_RUNTIME_REQUIRED")
            return
        if not self.experimental_route_enabled:
            raise ValueError("EXPERIMENTAL_ROUTE_DISABLED: experimental route is not enabled")
        self._validate_experimental_endpoint(runtime_adapter)
        if runtime_id != "experimental-h3-8190":
            raise ValueError("EXPERIMENTAL_RUNTIME_ID_REQUIRED: select experimental-h3-8190")
        if requires_ref2va:
            if requires_guides:
                raise ValueError("REF2VA_WITH_ADDGUIDE_UNVALIDATED")
            if execution_purpose != "A6_REF2VA_VALIDATION":
                raise ValueError("EXPERIMENTAL_JOB_NOT_AUTHORIZED: explicit A6 purpose required")
        elif director_execution is not None:
            if execution_purpose != "A7_DIRECTOR_VALIDATION":
                raise ValueError(
                    "EXPERIMENTAL_JOB_NOT_AUTHORIZED: explicit A7 Director purpose required")
            if not requires_guides:
                raise ValueError(
                    "A7_EXPERIMENTAL_GUIDE_JOB_REQUIRED: experimental Director route requires selected guides")
        elif execution_purpose != "A5_EXPERIMENTAL_VALIDATION":
            raise ValueError("EXPERIMENTAL_JOB_NOT_AUTHORIZED: explicit A5 validation purpose required")
        elif not requires_guides:
            raise ValueError("EXPERIMENTAL_GUIDE_JOB_REQUIRED: route is restricted to A5 guide Jobs")
        spec = getattr(runtime_adapter, "runtime_identity_spec", {}) or {}
        if (spec.get("runtime_id") != "experimental-h3-8190"
                or spec.get("runtime_role") != "experimental"
                or spec.get("comfyui_version") != "0.36.0"
                or str(spec.get("comfyui_git_sha") or "").lower()
                != "ee71d5c4993f29086b27fde1629a945ae48425bf"
                or not re.fullmatch(r"[0-9a-f]{64}",
                                    str(spec.get("config_fingerprint") or ""))):
            raise ValueError("EXPERIMENTAL_RUNTIME_FINGERPRINT_MISMATCH")
        client = getattr(runtime_adapter, "client", None)
        configured_output = str(spec.get("output_root_fingerprint") or "")
        actual_output = str(getattr(client, "output_root_fingerprint", "") or "")
        if not configured_output or configured_output != actual_output:
            raise ValueError("EXPERIMENTAL_RUNTIME_OUTPUT_FINGERPRINT_MISMATCH")

    # ------------------------------------------------------------------ #
    def submit_job(self, project_id: str, seed: int = 42,
                   risk_reviewed: bool = False,
                   generation_parameters: Optional[Dict[str, Any]] = None,
                   camera_motion: Optional[str] = None,
                   runtime_target: str = "production",
                   runtime_id: Optional[str] = None,
                   execution_purpose: Optional[str] = None,
                   director_execution: Optional[Dict[str, Any]] = None,
                   long_form_execution: Optional[Dict[str, Any]] = None,
                   dry_run: bool = False) -> Dict[str, Any]:
        if runtime_target not in {"production", "experimental"}:
            raise ValueError("RUNTIME_TARGET_INVALID: choose production or experimental")
        runtime_adapter = self._adapter_for_target(runtime_target)
        project = self.store.load_project(project_id)
        intent_for_route = self.store.load_intent(project_id) or {}
        route_workflow = str(intent_for_route.get("selected_workflow") or "")
        selected_roles = project.get("selected_reference_asset_ids") or {}
        requires_ref2va = bool(selected_ref2va_roles(selected_roles))
        self._validate_experimental_target(
            runtime_target, runtime_adapter, runtime_id=runtime_id,
            execution_purpose=execution_purpose,
            requires_guides=bool(project.get("guide_frames")),
            director_execution=director_execution,
            requires_ref2va=requires_ref2va)
        if project.get("guide_frames") and runtime_target != "experimental":
            raise ValueError(
                "GUIDE_RUNTIME_ISOLATION_REQUIRED: timeline guides require isolated port 8190")
        if runtime_adapter is None and not self.allow_mock_jobs:
            raise ValueError(
                "REAL_RUNTIME_REQUIRED: 真实 ComfyUI 尚未就绪，当前不能开始生成；"
                "请等待服务启动或前往环境设置/修复。"
            )
        previous_project_state = project["state"]
        if dry_run and project["state"] == "COMPLETED":
            # A completed Study is reusable, but preflight must model the same
            # fresh confirmation gate as a real new-generation request. Keep
            # this transition in-memory only: a dry run must not mutate Study
            # state or create a Job.
            machine = ProjectStateMachine(project["state"])
            machine.transition("start_new_generation", actor="architect",
                               reason="preflight another generation in completed Study")
            project["state"] = machine.state
        if dry_run and project["state"] != "USER_CONFIRM":
            raise ValueError(
                f"preflight requires USER_CONFIRM; project is {project['state']}")
        if dry_run:
            study = build_study_state(self.store, project_id)
            if not study["generate_allowed"]:
                raise ValueError(
                    "PREFLIGHT_STUDY_GATES_FAILED: "
                    + ", ".join(study["gate_reasons"])
                )
        if not dry_run and project["state"] == "GPU_FAILED":
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
        elif not dry_run and project["state"] == "QUALITY_FAILED":
            machine = ProjectStateMachine(project["state"])
            machine.transition("user_reviewed", actor="architect",
                               reason="retry after quality failure")
            project["state"] = machine.state
            self.store.save_project(project)
        elif not dry_run and project["state"] == "COMPLETED":
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
        if runtime_target == "production" and runtime_adapter is not None \
                and self.runtime_paths is not None:
            self.runtime_paths.validate_for_job()

        prompt = self.store.load_prompt(project_id)
        if prompt is None:
            raise ValueError("Prompt Gate: generate_prompt first")
        if not (prompt.get("verified") or {}).get("pass"):
            raise ValueError("Prompt Gate: official structure verification failed")
        current_intent = self.store.load_intent(project_id) or {}
        selected_workflow = current_intent.get("selected_workflow")
        if selected_workflow and selected_workflow != prompt.get("workflow"):
            raise ValueError(
                "WORKFLOW_PROMPT_MISMATCH: 请重新生成当前视频类型的 Prompt。")
        refs_by_id = self.store.load_references(project_id)
        ref2va_mode = str(prompt.get("mode") or "") == "Ref2VA"
        if ref2va_mode and runtime_target != "experimental":
            raise ValueError("REF2VA_EXPERIMENTAL_RUNTIME_REQUIRED")
        approved = resolve_selected_references(
            project_id, project, refs_by_id, prompt.get("workflow"),
            require_approved=True,
            reference_root=self.store.input_dir(project_id),
            include_ref2va_roles=ref2va_mode)
        selected_bindings = reference_bindings(approved, ref2va=ref2va_mode)
        prompt_bindings = prompt.get("reference_bindings")
        if prompt.get("a4_profile") and prompt_bindings != selected_bindings:
            raise ValueError(
                "REFERENCE_PROMPT_MISMATCH: 参考图角色或审批身份已变化，请重新生成 Prompt。")
        # Study state is authoritative for current intent, approved
        # references, profile and pinned Skill identity. Enforce that same
        # freshness gate here: a saved USER_CONFIRM state can outlive a local
        # Skill-bundle change without an intent mutation. Run it after the
        # more specific workflow/profile/reference identity gates so those
        # diagnostics remain actionable.
        study = build_study_state(self.store, project_id)
        if not study.get("prompt_current"):
            raise ValueError(
                "PROMPT_STALE: 当前提示词与意图、参考图或 Skill 版本不一致，请重新编译。")

        continuity_binding = None
        execution_project = project
        if long_form_execution is not None:
            if not isinstance(long_form_execution, Mapping) or not director_execution:
                raise ValueError("LONG_FORM_DIRECTOR_EXECUTION_REQUIRED")
            queue_id = str(long_form_execution.get("queue_id") or "")
            long_form_shot_id = str(long_form_execution.get("shot_id") or "")
            if long_form_shot_id != str(director_execution.get("shot_id") or ""):
                raise ValueError("LONG_FORM_SHOT_IDENTITY_MISMATCH")
            if self.long_form_api is None:
                raise ValueError("LONG_FORM_RUNTIME_UNAVAILABLE")
            prepared_long_form = self.long_form_api.prepare_for_job(
                project_id, queue_id, long_form_shot_id)
            continuity_binding = prepared_long_form.get("binding")
            if (not isinstance(continuity_binding, Mapping)
                    or continuity_binding.get("shot_id") != long_form_shot_id
                    or continuity_binding.get("queue_id") != queue_id):
                raise ValueError("LONG_FORM_BINDING_IDENTITY_INVALID")
            modes = list(continuity_binding.get("continuity_modes") or [])
            if "LOCK_PROJECT_IDENTITY" in modes:
                selected_by_id = {str(item.get("asset_id") or ""): item
                                  for item in selected_bindings}
                identity = list(continuity_binding.get("reference_bindings") or [])
                if not identity or any(
                        str(item.get("asset_id") or "") not in selected_by_id
                        or str(selected_by_id[str(item.get("asset_id") or "")]
                                .get("sha256") or "").lower()
                        != str(item.get("content_sha256") or "").lower()
                        for item in identity):
                    raise ValueError("LONG_FORM_PROJECT_IDENTITY_SELECTION_MISMATCH")
            derived_reference = prepared_long_form.get("reference")
            if "CONTINUE_VISUALLY" in modes:
                if (not isinstance(derived_reference, Mapping)
                        or derived_reference.get("state") != "APPROVED"
                        or derived_reference.get("role") != "first_frame"):
                    raise ValueError("LONG_FORM_DERIVED_REFERENCE_UNAVAILABLE")
                if str(prompt.get("mode") or "") == "Ref2VA":
                    raise ValueError("LONG_FORM_CONTINUITY_REF2VA_UNSUPPORTED")
                refs_by_id = dict(refs_by_id)
                derived_id = str(derived_reference.get("id") or "")
                refs_by_id[derived_id] = dict(derived_reference)
                execution_project = copy.deepcopy(project)
                selected_ids = dict(execution_project.get(
                    "selected_reference_asset_ids") or {})
                selected_ids["first_frame"] = derived_id
                execution_project["selected_reference_asset_ids"] = selected_ids
                approved = resolve_selected_references(
                    project_id, execution_project, refs_by_id, prompt.get("workflow"),
                    require_approved=True,
                    reference_root=self.store.input_dir(project_id),
                    include_ref2va_roles=False)
                selected_bindings = reference_bindings(approved)
                prompt = copy.deepcopy(prompt)
                prompt["reference_bindings"] = copy.deepcopy(selected_bindings)
            director_execution = copy.deepcopy(director_execution)
            director_execution["continuity_binding"] = copy.deepcopy(
                continuity_binding)

        try:
            normalized_motion = normalize_camera_motion(prompt["workflow"], camera_motion)
        except WorkflowParameterError as exc:
            raise ValueError(f"{exc.code}: 参数配置错误。{exc}") from exc

        # The live ComfyUI registry is checked before a Job record is created.
        # This prevents missing model-path/workflow bindings from becoming a
        # misleading GPU_FAILED job and never submits /prompt.
        preflight_result = None
        if runtime_adapter is not None and hasattr(runtime_adapter, "preflight"):
            try:
                preflight_result = runtime_adapter.preflight()
            except Exception as exc:  # noqa: BLE001
                if runtime_target == "experimental":
                    raise ValueError("EXPERIMENTAL_RUNTIME_UNAVAILABLE") from exc
                raise ValueError(f"MODEL_PATH_ERROR: 模型路径或工作流绑定未通过预检。{exc}") from exc
        if runtime_target == "experimental":
            live_health = (preflight_result or {}).get("health") or {}
            live_version = str(live_health.get("comfyui_version")
                               or (live_health.get("system") or {}).get(
                                   "comfyui_version") or "")
            if live_version != "0.36.0":
                raise ValueError("EXPERIMENTAL_RUNTIME_VERSION_MISMATCH")
            if requires_ref2va:
                self._require_ref2va_runtime(preflight_result)
        elif runtime_target == "production" and runtime_adapter is not None:
            live_health = (preflight_result or {}).get("health") or {}
            live_version = str(live_health.get("comfyui_version")
                               or (live_health.get("system") or {}).get(
                                   "comfyui_version") or "")
            if live_version and live_version != "0.33.1":
                raise ValueError("PRODUCTION_RUNTIME_VERSION_MISMATCH")

        try:
            params, profile_context = resolve_product_parameters(
                prompt["workflow"], generation_parameters, seed=int(seed))
            params = validate_workflow_parameters(
                prompt["workflow"], params, seed=int(seed))
        except ValueError as exc:
            raise ValueError(f"参数不符合 H3 生成契约: {exc}") from exc
        raw_generation_parameters = generation_parameters or {}
        image_size_was_requested = (
            "ref2va_image_size" in raw_generation_parameters)
        if ref2va_mode:
            ref2va_image_size = raw_generation_parameters.get(
                "ref2va_image_size", REF2VA_DEFAULT_IMAGE_SIZE)
            if (not isinstance(ref2va_image_size, str)
                    or ref2va_image_size not in REF2VA_IMAGE_SIZE_OPTIONS):
                raise ValueError("REF2VA_IMAGE_SIZE_UNSUPPORTED")
            live_object_info = (preflight_result or {}).get("object_info") or {}
            live_ref2va_schema = ref2va_schema_capabilities(live_object_info)
            if (not live_ref2va_schema.get("available")
                    or ref2va_image_size not in live_ref2va_schema.get(
                        "reference_image_size_options", [])):
                raise ValueError(
                    f"REF2VA_IMAGE_SIZE_UNAVAILABLE:{ref2va_image_size}")
            # Persist the fidelity choice in the immutable Job snapshot and
            # pass the same value to the native graph compiler.
            params["ref2va_image_size"] = ref2va_image_size
        elif image_size_was_requested:
            raise ValueError("REF2VA_IMAGE_SIZE_ONLY_FOR_REF2VA")
        prompt_params = prompt.get("generation_parameters") or {}
        if prompt_params and (
                normalize_quality_id(prompt_params.get("quality", "NATIVE_HIGH"))
                != profile_context["quality_profile"]
                or not math.isclose(
                    float(prompt_params.get("duration", 4.0)),
                    float(params["duration"]), rel_tol=0.0, abs_tol=1e-9)):
            raise ValueError(
                "QUALITY_PROFILE_PROMPT_MISMATCH: 请先按当前质量与时长重新生成 Prompt。")
        prompt_profile = prompt.get("a4_profile") or {}
        expected_profile_identity = {
            "contract_version": profile_context["contract_version"],
            "workflow_id": profile_context["workflow_id"],
            "quality_profile": profile_context["quality_profile"],
            "architecture_profile": profile_context["architecture_profile"],
            "architecture_profile_version": profile_context[
                "architecture_profile_version"],
            "quality_profile_version": profile_context["quality_profile_version"],
            "prompt_profile_version": profile_context["prompt_profile_version"],
        }
        if any(prompt_profile.get(key) != expected
               for key, expected in expected_profile_identity.items()):
            raise ValueError(
                "A4_PROFILE_PROMPT_MISMATCH: 当前 Prompt 工作流/配置版本已过期，请重新生成。")
        # The normalized parameter is the value the Golden binder will use;
        # keep the Job row/audit seed identical even for legacy callers that
        # provide it only inside generation_parameters.
        seed = int(params["seed"])

        guide_bindings = []
        guide_capability = None
        if project.get("guide_frames"):
            try:
                guide_bindings = resolve_guide_bindings(
                    project_id, project.get("guide_frames"), refs_by_id,
                    target_frame_count=int(params["frame_count"]),
                    fps=NATIVE_H3_FPS, workflow_id=prompt["workflow"],
                    reference_root=self.store.input_dir(project_id))
            except GuideFrameError as exc:
                raise ValueError(str(exc)) from exc
            if runtime_adapter is None:
                raise ValueError(
                    "GUIDE_RUNTIME_UNAVAILABLE: mock execution cannot consume native guides")
            try:
                guide_capability = MultiFrameGuideCapabilityAdapter(
                    runtime_adapter.client,
                    runtime_name=runtime_target,
                    version=str((preflight_result or {}).get("health", {}).get(
                        "comfyui_version") or (((preflight_result or {}).get(
                            "health") or {}).get("system") or {}).get(
                                "comfyui_version") or "unknown"),
                    port=8190 if runtime_target == "experimental" else 8189,
                ).require()
            except Exception as exc:  # noqa: BLE001 - do not create a misleading Job
                raise ValueError(str(exc)) from exc

        director_compilation = None
        if director_execution is not None:
            from .director_api import DirectorAPI
            director_compilation = DirectorAPI(
                self.store, output_api=self.output_api).prepare_for_job(
                    project_id, director_execution, prompt, params,
                    runtime_target=runtime_target, project=execution_project,
                    references=refs_by_id,
                    continuity_binding=continuity_binding)
            prompt = director_compilation["prompt"]
            params = director_compilation["generation_parameters"]
            if int(params.get("frame_count", 0)) != int(profile_context[
                    "final_execution_parameters"].get("frame_count", 0)):
                raise ValueError("DIRECTOR_FRAME_COUNT_BINDING_MISMATCH")

        guide_prompt = (compile_timeline_guide_prompt(
            str(prompt.get("prompt") or ""), guide_bindings, fps=NATIVE_H3_FPS)
            if guide_bindings else None)
        guide_prompt_metadata = ({key: value for key, value in guide_prompt.items()
                                  if key != "prompt"}
                                 if guide_prompt else None)

        now = self.clock()
        job_id = self.store.new_id("preflight" if dry_run else "job")
        job = {
            "id": job_id,
            "project_id": project_id,
            "workflow": prompt["workflow"],
            "state": "PREPARING",
            "seed": int(seed),
            "camera_motion": normalized_motion,
            "generation_parameters": params,
            "execution_trace": {
                "contract_version": profile_context["contract_version"],
                "quality_profile_version": profile_context["quality_profile_version"],
                "prompt_profile_version": profile_context["prompt_profile_version"],
                "architecture_profile_version": profile_context[
                    "architecture_profile_version"],
                "workflow_id": prompt["workflow"],
                "workflow": prompt["workflow"],
                "quality_profile": profile_context["quality_profile"],
                "requested_quality_profile": profile_context["requested_quality_profile"],
                "resolved_execution_profile": profile_context["resolved_execution_profile"],
                "execution_mode": profile_context["execution_mode"],
                "native_generation": dict(profile_context["native_generation"]),
                "delivery": {**dict(profile_context["delivery"]),
                             "status": "NOT_PRODUCED"},
                "reference_bindings": selected_bindings,
                "guide_count": len(guide_bindings),
                "guide_bindings": [{key: guide[key] for key in (
                    "asset_id", "role", "requested_time_seconds",
                    "resolved_frame_idx", "ordinal", "content_sha256",
                    "source_identity", "approval_evidence")}
                    for guide in guide_bindings],
                "native_generation_fps": NATIVE_H3_FPS,
                "target_frame_count": int(params["frame_count"]),
                "guide_backend": "MiniMaxH3AddGuide" if guide_bindings else "NONE",
                "runtime_capability": guide_capability,
                "guide_prompt_compilation": guide_prompt_metadata,
                "director_execution": (director_compilation.get("provenance")
                                       if director_compilation else None),
                "runtime_identity": build_runtime_identity(
                    runtime_target, runtime_adapter, preflight_result),
                "architecture_profile": profile_context["architecture_profile"],
                "profile_parameter_overrides": profile_context["profile_parameter_overrides"],
                "final_execution_parameters": dict(
                    profile_context["final_execution_parameters"]),
                "workflow_sha256": None,
                "status": "WAITING_FOR_RUNTIME_BINDER" if runtime_adapter
                          else "MOCK_NOT_BOUND",
            },
            "runtime": "native" if runtime_adapter else "mock",
            "runtime_target": runtime_target,
            "runtime_id": ("experimental-h3-8190" if runtime_target == "experimental"
                           else "production-h3-8189"),
            "execution_purpose": (execution_purpose or "PRODUCTION"),
            "created_at": self.store.timestamp(),
            "started_at": now,
            "elapsed": 0.0,
            "stages": ["PREPARING"],
            "package_built": False,
            "output_path": "",
            "source_output_path": "",
            "failure_reason": "",
            "prompt_hash": prompt["prompt_hash"],
            "prompt_snapshot": {
                key: prompt.get(key)
                for key in ("workflow", "mode", "prompt", "alignment",
                            "integrated_multimodal_description", "overall_soundscape",
                            "non_diegetic_music", "prompt_hash", "a4_profile",
                            "reference_bindings", "provenance")
            },
            "reference_bindings": selected_bindings,
            "guide_bindings_snapshot": [{key: guide[key] for key in (
                "asset_id", "role", "requested_time_seconds",
                "resolved_frame_idx", "ordinal", "content_sha256",
                "source_identity", "approval_evidence")}
                for guide in guide_bindings],
            "director_execution": (director_compilation.get("provenance")
                                   if director_compilation else None),
            "reference_assets_snapshot": [
                {**binding, "filename": str(ref.get("filename") or "")}
                for binding, ref in zip(selected_bindings, approved)
            ],
            "cancelled": False,
            # Native execution has no authoritative percentage until Comfy
            # emits a sampler event. ``None`` prevents a false 0% impression;
            # mock jobs retain the historical numeric contract.
            "progress": None if runtime_adapter is not None else 0.0,
            "current_stage": "准备参考图",
            "step": None,
            "total_steps": None,
            "eta_seconds": None,
            "prompt_id": None,
            "submission_state": "NOT_STARTED",
            "execution_workflow_sha256": None,
            "lifecycle_state": "CREATED",
            "progress_message": "准备参考图",
            "runtime_output_path": "",
            "final_output_path": "",
            "result_pipeline": {
                "schema_version": 1,
                "current_stage": "PREPARING",
                "status": "PENDING",
                "expected_output_identity": None,
                "history_outputs": [],
                "packaging_status": "NOT_STARTED",
                "events": [],
            },
        }
        if guide_prompt:
            job["prompt_snapshot"]["execution_prompt"] = guide_prompt["prompt"]
            job["prompt_snapshot"]["guide_prompt_compilation"] = guide_prompt_metadata
        history = self.store.load_jobs(project_id).values()
        job["estimated_time"] = estimate_generation_range(
            history, workflow_id=job["workflow"], duration=params["duration"],
            fps=params["fps"], resolution=params["resolution"],
            steps=params["steps"], cold_start=True)
        if dry_run:
            if runtime_target != "experimental" or runtime_adapter is None:
                raise ValueError("EXPERIMENTAL_PREFLIGHT_REQUIRES_EXPERIMENTAL_RUNTIME")
            return self._persist_experimental_preflight(
                project_id, project, prompt, approved, params, normalized_motion,
                guide_bindings, job, runtime_adapter, preflight_result,
                execution_purpose=execution_purpose, guide_prompt=guide_prompt)
        jobs = self.store.load_jobs(project_id)
        if long_form_execution is not None:
            try:
                # Reserve the exact queue slot before persisting a Job. The
                # per-queue lock makes concurrent clicks fail closed.
                self.long_form_api.reserve_job(
                    project_id,
                    str(long_form_execution.get("queue_id") or ""),
                    str(long_form_execution.get("shot_id") or ""),
                    job)
            except Exception as exc:  # noqa: BLE001 - do not create a duplicate
                raise ValueError("LONG_FORM_QUEUE_RESERVATION_FAILED") from exc
        jobs[job_id] = job
        self.store.save_jobs(project_id, jobs)
        if long_form_execution is not None:
            try:
                # Persist the queue association before a runtime worker can
                # submit /prompt. A lost response is recoverable from the
                # immutable long_form_execution Job provenance.
                self.long_form_api.bind_job(
                    project_id,
                    str(long_form_execution.get("queue_id") or ""),
                    str(long_form_execution.get("shot_id") or ""),
                    job_id)
            except Exception as exc:  # noqa: BLE001 - fail closed before GPU
                persisted_jobs = self.store.load_jobs(project_id)
                failed_job = persisted_jobs.get(job_id)
                if failed_job:
                    failed_job.update(
                        state="FAILED",
                        failure_reason="LONG_FORM_QUEUE_BIND_FAILED",
                        submission_attempted=False,
                        submission_state="NOT_STARTED",
                        lifecycle_state="FAILED_BEFORE_SUBMISSION")
                    persisted_jobs[job_id] = failed_job
                    self.store.save_jobs(project_id, persisted_jobs)
                raise ValueError(
                    "LONG_FORM_QUEUE_BIND_FAILED_BEFORE_SUBMISSION") from exc
        if director_compilation:
            from .director_api import DirectorAPI
            DirectorAPI(self.store, output_api=self.output_api).mark_job(
                project_id,
                director_compilation["provenance"]["sequence_id"],
                director_compilation["provenance"]["shot_id"],
                job_id,
                generation_settings={
                    "quality": profile_context["quality_profile"],
                    "fps": NATIVE_H3_FPS,
                    "seed": int(seed),
                },
            )

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

        if runtime_adapter:
            request = self._build_request(project_id, project, prompt, approved,
                                          params, normalized_motion, guide_bindings,
                                          guide_prompt=guide_prompt)
            runtime_adapter.progress_callback = lambda event: self._record_progress(
                project_id, job_id, event)
            runtime_adapter.submission_callback = lambda info: self._record_submission(
                project_id, job_id, info)
            thread = threading.Thread(
                target=self._run_real_job,
                args=(project_id, job_id, request, None, None, runtime_target),
                daemon=True,
            )
            self._threads[job_id] = thread
            thread.start()
        return self.get_job(job_id)

    def _persist_experimental_preflight(
            self, project_id: str, project: dict, prompt: dict,
            approved_refs: List[dict], params: dict, camera_motion: str,
            guide_bindings: List[dict], job: dict, runtime_adapter,
            preflight_result: Optional[dict], *,
            execution_purpose: Optional[str] = None,
            guide_prompt: Optional[dict] = None) -> Dict[str, Any]:
        """Compile and persist a path-free preflight snapshot, never a Job."""
        from runtime.adapters.production_workflow_binding import canonical_workflow_sha256

        client = getattr(runtime_adapter, "client", None)
        if client is None:
            raise ValueError("EXPERIMENTAL_RUNTIME_UNAVAILABLE")
        queue_before = client.get_queue()
        if queue_before.get("queue_running") or queue_before.get("queue_pending"):
            raise ValueError("EXPERIMENTAL_RUNTIME_QUEUE_NOT_IDLE")

        request = self._build_request(
            project_id, project, prompt, approved_refs, params,
            camera_motion, guide_bindings, guide_prompt=guide_prompt)
        # Mirror the deterministic input names used by the real staging path,
        # but do not copy any media into the experimental runtime during a dry run.
        stored_refs = self.store.load_references(project_id)
        for reference in request.reference_assets:
            record = stored_refs.get(str(reference.get("asset_id") or "")) or {}
            source = Path(str(record.get("stored_path") or ""))
            if not source.is_file():
                raise ValueError("PREFLIGHT_REFERENCE_MISSING")
            reference["path_or_ref"] = unique_comfy_filename(record, source)
            reference["filename"] = reference["path_or_ref"]

        try:
            prepared = runtime_adapter.prepare(request)
            prepared = runtime_adapter.attach_job_identity(prepared, job["id"])
        except Exception as exc:  # noqa: BLE001 - keep private runtime paths out of API errors
            code = str(getattr(exc, "code", "") or type(exc).__name__)
            safe_code = "".join(char for char in code.upper()
                                if char.isalnum() or char in "_-")[:80]
            raise ValueError(
                f"EXPERIMENTAL_PREFLIGHT_COMPILE_FAILED:{safe_code or 'RUNTIME_CONTRACT'}") from exc
        payload = prepared.get("translated_payload") or {}
        ref2va_mode = str(prompt.get("mode") or "") == "Ref2VA"
        ref2va_plan = prepared.get("ref2va_plan") if ref2va_mode else None
        if ref2va_mode and not isinstance(ref2va_plan, dict):
            raise ValueError("REF2VA_PREFLIGHT_PLAN_MISSING")
        snapshot = self._build_workflow_snapshot(
            request, approved_refs, payload, ref2va_plan=ref2va_plan)
        workflow_sha = canonical_workflow_sha256(payload)
        if workflow_sha != snapshot.get("execution_workflow_sha256"):
            raise ValueError("PREFLIGHT_WORKFLOW_SHA_MISMATCH")
        try:
            bound_execution_parameters = actual_execution_parameters(
                payload, str(request.workflow_id), job["execution_trace"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("PREFLIGHT_EXECUTION_TRACE_INVALID") from exc
        expected_execution = job["execution_trace"].get(
            "final_execution_parameters") or {}
        expected_trace_values = {
            "quality_profile": job["execution_trace"].get("quality_profile"),
            "architecture_profile": job["execution_trace"].get(
                "architecture_profile"),
            "resolution": expected_execution.get("resolution"),
            "width": expected_execution.get("width"),
            "height": expected_execution.get("height"),
            "requested_duration_seconds": expected_execution.get(
                "requested_duration_seconds"),
            "fps": expected_execution.get("fps"),
            "frame_count": expected_execution.get("frame_count"),
            "latent_length": expected_execution.get("latent_length"),
            "seed": expected_execution.get("seed"),
            "steps": expected_execution.get("steps"),
            "sampler": expected_execution.get("sampler_mode"),
            "scheduler": expected_execution.get("scheduler"),
            "denoise": expected_execution.get("denoise"),
            "acceleration": expected_execution.get("acceleration"),
        }
        for name, expected in expected_trace_values.items():
            actual = bound_execution_parameters.get(name)
            if isinstance(expected, (int, float)) and not isinstance(expected, bool):
                matches = (actual is not None and math.isclose(
                    float(actual), float(expected), rel_tol=0.0, abs_tol=1e-6))
            else:
                matches = actual == expected
            if not matches:
                raise ValueError(f"PREFLIGHT_EXECUTION_PARAMETER_MISMATCH:{name}")
        if (ref2va_mode and bound_execution_parameters.get("reference_count")
                != len(approved_refs)):
            raise ValueError("PREFLIGHT_EXECUTION_REFERENCE_COUNT_MISMATCH")
        expected_output = expected_save_video_identity(
            payload, job["id"], workflow_sha)
        runtime_identity = build_runtime_identity(
            "experimental", runtime_adapter, preflight_result)
        spec = getattr(runtime_adapter, "runtime_identity_spec", {}) or {}
        if (runtime_identity.get("runtime_id") != "experimental-h3-8190"
                or runtime_identity.get("comfyui_version") != "0.36.0"
                or runtime_identity.get("comfyui_git_sha")
                != "ee71d5c4993f29086b27fde1629a945ae48425bf"
                or runtime_identity.get("runtime_config_fingerprint")
                != spec.get("config_fingerprint")):
            raise ValueError("PREFLIGHT_RUNTIME_IDENTITY_MISMATCH")
        queue_after = client.get_queue()
        if queue_before != queue_after:
            raise ValueError("PREFLIGHT_RUNTIME_QUEUE_CHANGED")

        guide_rows = [{key: guide.get(key) for key in (
            "asset_id", "role", "requested_time_seconds", "resolved_frame_idx",
            "ordinal", "content_sha256", "source_identity", "approval_evidence")}
            for guide in guide_bindings]
        ref2va_bindings = list((ref2va_plan or {}).get("bindings") or [])
        director_execution = job.get("director_execution") or {}
        is_a7_director = bool(director_execution)
        expected_purpose = (
            "A7_DIRECTOR_VALIDATION" if is_a7_director
            else "A6_REF2VA_VALIDATION" if ref2va_mode
            else "A5_EXPERIMENTAL_VALIDATION")
        if execution_purpose != expected_purpose:
            raise ValueError("EXPERIMENTAL_PREFLIGHT_PURPOSE_MISMATCH")
        runtime_capability = (
            {"node": "MiniMaxH3ReferenceToVideo", "available": True,
             "status": "AVAILABLE", "runtime_id": runtime_identity["runtime_id"]}
            if ref2va_mode else prepared.get("guide_capability"))
        if is_a7_director:
            runtime_capability = {
                **dict(runtime_capability or {}),
                "director_validation": True,
                "sequence_id": director_execution.get("sequence_id"),
                "shot_id": director_execution.get("shot_id"),
            }
        node_types: Dict[str, int] = {}
        for node in payload.values():
            node_type = str(node.get("class_type") or "unknown")
            node_types[node_type] = node_types.get(node_type, 0) + 1
        record = {
            "schema_version": 1,
            "snapshot_type": (
                "A7_DIRECTOR_EXPERIMENTAL_PREFLIGHT" if is_a7_director
                else "A6_REF2VA_EXPERIMENTAL_PREFLIGHT" if ref2va_mode
                else "A5_EXPERIMENTAL_PREFLIGHT"),
            "id": job["id"],
            "project_id": project_id,
            "state": "DRY_RUN",
            "created_at": self.store.timestamp(),
            "execution_purpose": expected_purpose,
            "runtime_target": "experimental",
            "runtime_identity": runtime_identity,
            "guide_count": len(guide_rows),
            "guide_bindings": guide_rows,
            "ref2va_count": len(ref2va_bindings),
            "reference_execution_plan": snapshot.get("reference_execution_plan"),
            "target_frame_count": int(params["frame_count"]),
            "native_generation_fps": NATIVE_H3_FPS,
            "prompt_sha256": str(prompt.get("prompt_hash") or ""),
            "execution_prompt_sha256": str(
                (guide_prompt or {}).get("execution_prompt_sha256") or
                (guide_prompt or {}).get("source_prompt_sha256") or ""),
            "guide_prompt_compilation": ({key: value for key, value in
                                          guide_prompt.items() if key != "prompt"}
                                         if guide_prompt else None),
            "reference_bindings": reference_bindings(
                approved_refs, ref2va=ref2va_mode),
            "director_execution": director_execution or None,
            "generation_parameters": dict(params),
            "bound_execution_parameters": bound_execution_parameters,
            "execution_workflow_sha256": workflow_sha,
            "workflow_node_count": len(payload),
            "workflow_node_types": node_types,
            "runtime_capability": runtime_capability,
            "expected_output_identity": expected_output,
            "prompt_id": None,
            "submission_attempted": False,
            "submission_state": "NOT_PERFORMED",
            "private_paths_included": False,
        }
        preflight_dir = self.store.data_root / "preflights"
        self.store.save_json(preflight_dir / f"{job['id']}.json", record)
        return {
            "id": job["id"], "project_id": project_id,
            "state": "DRY_RUN", "execution_purpose": record["execution_purpose"],
            "snapshot_type": record["snapshot_type"],
            "runtime_identity": runtime_identity,
            "guide_count": len(guide_rows),
            "guide_frame_indexes": [row["resolved_frame_idx"] for row in guide_rows],
            "ref2va_count": len(ref2va_bindings),
            "reference_execution_plan": snapshot.get("reference_execution_plan"),
            "bound_execution_parameters": bound_execution_parameters,
            "target_frame_count": int(params["frame_count"]),
            "native_generation_fps": NATIVE_H3_FPS,
            "workflow_sha256": workflow_sha,
            "workflow_node_count": len(payload),
            "runtime_capability": runtime_capability,
            "director_execution": director_execution or None,
            "expected_output_prefix": expected_output.get("filename_prefix"),
            "output_root_fingerprint": runtime_identity.get("output_root_fingerprint"),
            "prompt_id": None, "submission_attempted": False,
            "submission_state": "NOT_PERFORMED",
            "preflight_snapshot_persisted": True,
            "queue_unchanged": True,
        }

    def _build_workflow_snapshot(self, request: Any,
                                 approved_refs: List[dict],
                                 execution_payload: Dict[str, Any], *,
                                 ref2va_plan: Optional[dict] = None) -> Dict[str, Any]:
        """Persist the exact API graph used for the real Comfy submission."""
        from runtime.adapters.production_workflow_binding import canonical_workflow_sha256
        workflow_id = str(request.workflow_id)
        workflow = json.loads(json.dumps(execution_payload, ensure_ascii=False))
        workflow_hash = canonical_workflow_sha256(workflow)
        ref2va_mode = str((getattr(request, "prompt_payload", None) or {}).get(
            "mode") or "") == "Ref2VA"
        selected_ref_bindings = reference_bindings(
            approved_refs, ref2va=ref2va_mode)
        reference_execution_plan = None
        if ref2va_mode:
            source_plan = ref2va_plan or {}
            reference_execution_plan = {
                key: source_plan.get(key)
                for key in ("schema_version", "runtime_id", "backend", "node",
                            "limits", "counts", "reference_image_size",
                            "required_vaes", "bindings")
                if key in source_plan
            }
        guide_bindings = [{key: item.get(key) for key in (
            "asset_id", "role", "requested_time_seconds", "resolved_frame_idx",
            "ordinal", "content_sha256", "source_identity", "approval_evidence")}
            for item in (getattr(request, "guide_frames", None) or [])]
        asset_identity = (selected_ref_bindings if not guide_bindings else {
            "references": selected_ref_bindings, "guide_bindings": guide_bindings})
        asset_hash = hashlib.sha256(json.dumps(
            asset_identity, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")).hexdigest()
        prompt_hash = str((request.prompt_payload or {}).get("prompt_hash") or "")
        snapshot_id = hashlib.sha256(
            f"{workflow_hash}:{asset_hash}:{prompt_hash}".encode("utf-8")
        ).hexdigest()[:24]
        return {
            "snapshot_id": snapshot_id,
            "workflow_id": workflow_id,
            "reference_mode": "Ref2VA" if ref2va_mode else str(
                (getattr(request, "prompt_payload", None) or {}).get("mode") or ""),
            "file_name": f"golden/{workflow_id}.json",
            "workflow": workflow,
            "execution_payload": workflow,
            "execution_workflow_sha256": workflow_hash,
            "workflow_hash": workflow_hash,
            "asset_hash": asset_hash,
            "reference_bindings": selected_ref_bindings,
            "reference_execution_plan": reference_execution_plan,
            "guide_count": len(guide_bindings),
            "guide_bindings": guide_bindings,
            "guide_prompt_compilation": (request.prompt_payload or {}).get(
                "guide_prompt_compilation"),
            "prompt_hash": prompt_hash,
            "reference_filenames": [
                str(item.get("path_or_ref") or item.get("filename") or "")
                for item in approved_refs
            ],
        }

    @staticmethod
    def _require_ref2va_runtime(preflight_result: Optional[dict]) -> None:
        """Fail before Job creation unless the live experimental runtime can execute Ref2VA."""
        from runtime.reference_contract import ref2va_schema_capabilities
        from runtime.adapters.ref2va_workflow_binding import REF2VA_MODEL

        object_info = (preflight_result or {}).get("object_info") or {}
        schema = ref2va_schema_capabilities(object_info)
        if not schema.get("available"):
            raise ValueError("REF2VA_NODE_SCHEMA_UNAVAILABLE")

        def choices(node_name: str, field: str) -> list[str]:
            spec = (((object_info.get(node_name) or {}).get("input") or {})
                    .get("required") or {}).get(field)
            if not isinstance(spec, (list, tuple)) or not spec:
                return []
            value = spec[0]
            while isinstance(value, (list, tuple)) and value:
                value = value[0]
            if isinstance(spec[0], (list, tuple)):
                pending = list(spec[0])
                result: list[str] = []
                while pending:
                    child = pending.pop(0)
                    if isinstance(child, (list, tuple)):
                        pending[0:0] = list(child)
                    elif isinstance(child, str):
                        result.append(child)
                return result
            return [str(value)] if isinstance(value, str) else []

        if REF2VA_MODEL not in choices("UNETLoader", "unet_name"):
            raise ValueError("REF2VA_CHECKPOINT_UNAVAILABLE")
        if not any("video_vae" in item.lower()
                   for item in choices("VAELoader", "vae_name")):
            raise ValueError("REF2VA_VIDEO_VAE_UNAVAILABLE")

    # ------------------------------------------------------------------ #
    def get_job(self, job_id: str) -> Dict[str, Any]:
        project_id, job = self.store.find_job(job_id)
        if job.get("runtime") == "mock" and not self.allow_mock_jobs:
            return _decorate_job(_mock_runtime_blocked_job(job))
        if job.get("runtime") == "native":
            if self._should_reconcile(job):
                self.reconcile_job(job_id, start_observer=True)
                project_id, job = self.store.find_job(job_id)
            if is_job_terminal(job):
                self._ensure_terminal_fields(project_id, job)
                project_id, job = self.store.find_job(job_id)
                if job["state"] == "COMPLETED":
                    # A successful Runtime file is not enough: make a missing
                    # custom-folder delivery recoverable on every refresh.
                    if (not job.get("final_output_path")
                            or job.get("delivery_state") == "OUTPUT_DELIVERY_FAILED"):
                        self._recover_completed_output(project_id, job)
                        project_id, job = self.store.find_job(job_id)
                    if not _real_output_exists(self.store, project_id, job):
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
        # Detail views are also reconciliation entry points; refreshing the
        # page must be able to repair legacy false-failed Jobs.
        project_id, job = self.store.find_job(job_id)
        if job.get("runtime") == "native" and self._should_reconcile(job):
            self.reconcile_job(job_id, start_observer=True)
            project_id, job = self.store.find_job(job_id)
        if is_job_terminal(job):
            self._ensure_terminal_fields(project_id, job)
            project_id, job = self.store.find_job(job_id)
        if (job.get("runtime") == "native" and job.get("state") == "COMPLETED"
                and (not job.get("final_output_path")
                     or job.get("delivery_state") == "OUTPUT_DELIVERY_FAILED")):
            self._recover_completed_output(project_id, job)
            project_id, job = self.store.find_job(job_id)
        project = self.store.load_project(project_id)
        refs_by_id = self.store.load_references(project_id)
        job_bindings = list(job.get("reference_bindings") or [])
        if not job_bindings:
            current_reference = refs_by_id.get(project.get("current_reference_asset_id"))
            job_bindings = (reference_bindings([current_reference])
                            if current_reference and current_reference.get("state") == "APPROVED"
                            else [])
        snapshots = {item.get("asset_id"): item
                     for item in job.get("reference_assets_snapshot") or []}
        refs = []
        for binding in job_bindings:
            item = refs_by_id.get(binding.get("asset_id"))
            snapshot = snapshots.get(binding.get("asset_id"), {})
            refs.append({
                "asset_id": binding.get("asset_id"),
                "role": binding.get("role"),
                "filename": snapshot.get("filename") or (item or {}).get("filename"),
                "sha256": binding.get("sha256"),
                "approval_state": binding.get("approval_state"),
                "preview_url": (
                    f"/api/assets/{binding['asset_id']}/content?v={binding.get('sha256') or 1}"
                    if item and (item.get("stored_path")
                                 and Path(item["stored_path"]).is_file()) else None),
            })
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
            "reference": (dict(refs[0]) if refs else None),
            "references": refs,
            "prompt_summary": str(prompt.get("prompt", ""))[:280],
            "parameters": dict(job.get("generation_parameters") or {}),
            "technical_details": {
                "failure_code": detail.get("failure_code", ""),
                "failure_reason": detail.get("technical_details", detail.get("failure_reason", "")),
                "runtime": detail.get("runtime", ""),
                "workflow": detail.get("workflow", ""),
                "output_path": detail.get("output_path", ""),
                "source_output_path": detail.get("source_output_path", ""),
                "runtime_output_path": detail.get("runtime_output_path", ""),
                "final_output_path": detail.get("final_output_path", ""),
                "execution_trace": dict(job.get("execution_trace") or {}),
            },
        })
        return detail

    def retry_job(self, job_id: str) -> Dict[str, Any]:
        project_id, job = self.store.find_job(job_id)
        if job.get("runtime") == "native" and self._should_reconcile(job):
            self.reconcile_job(job_id, start_observer=True)
            project_id, job = self.store.find_job(job_id)
            if job.get("state") in ("PREPARING", "LOADING_MODEL", "SAMPLING",
                                      "DECODING", "EXPORTING", "RECONCILING"):
                raise ValueError("原任务仍在 ComfyUI 中运行，已重新连接，不会重复提交")
            if job.get("state") == "COMPLETED":
                return _decorate_job(job)
        effective_state = job.get("state")
        if (job.get("runtime") == "mock" and not self.allow_mock_jobs
                and effective_state == "COMPLETED"):
            effective_state = "FAILED"
        if effective_state not in ("FAILED", "GPU_FAILED", "CANCELLED", "SUBMISSION_LOST"):
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
        # Job Center refresh is a bounded, existing server activity point.
        self.maybe_release_idle_memory()
        out = []
        for job in self.store.load_jobs(project_id).values():
            out.append(self.get_job(job["id"]))
        return sorted(out, key=lambda j: j["created_at"], reverse=True)

    def maybe_release_idle_memory(self, threshold_seconds: float = 600.0) -> Dict[str, Any]:
        """Release model memory only after a proven, safe idle window.

        Failure to query queue, health, or the release endpoint never changes a Job.
        """
        now = float(self.clock())
        if not self.auto_release_idle_memory:
            return {"released": False, "reason": "disabled"}
        if now - self._idle_memory_last_probe < 30.0:
            return {"released": False, "reason": "probe_throttled"}
        self._idle_memory_last_probe = now
        client = getattr(self.runtime_adapter, "client", None)
        if client is None or not hasattr(client, "get_queue") or not hasattr(client, "free_memory"):
            return {"released": False, "reason": "unsupported"}
        try:
            for project in self.store.list_projects():
                for job in self.store.load_jobs(project["id"]).values():
                    if is_job_active(job):
                        self._idle_memory_since = None
                        return {"released": False, "reason": "active_job",
                                "job_id": job.get("id")}
            queue = client.get_queue()
            if (queue.get("queue_running") or queue.get("queue_pending")):
                self._idle_memory_since = None
                return {"released": False, "reason": "comfy_queue_active"}
        except Exception as exc:
            self._idle_memory_since = None
            return {"released": False, "reason": "observation_failed",
                    "error_type": type(exc).__name__}
        if self._idle_memory_since is None:
            self._idle_memory_since = now
            return {"released": False, "reason": "idle_window_started"}
        if now - self._idle_memory_since < max(1.0, float(threshold_seconds)):
            return {"released": False, "reason": "threshold_not_reached",
                    "idle_seconds": round(now - self._idle_memory_since, 3)}
        if self._idle_memory_last_release is not None and (
                now - self._idle_memory_last_release < max(30.0, float(threshold_seconds))):
            return {"released": False, "reason": "already_released"}
        try:
            client.free_memory()
            health = client.health_check() if hasattr(client, "health_check") else {}
        except Exception as exc:
            return {"released": False, "reason": "release_failed",
                    "error_type": type(exc).__name__}
        self._idle_memory_last_release = now
        self._idle_memory_since = now
        return {"released": True, "reason": "idle_threshold_reached",
                "health_available": bool((health or {}).get("available", True))}

    def estimate(self, project_id: str,
                 generation_parameters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        project = self.store.load_project(project_id)
        prompt = self.store.load_prompt(project_id) or {}
        intent = self.store.load_intent(project_id) or {}
        workflow = str(prompt.get("workflow") or intent.get("selected_workflow")
                       or "05_Slow_Walkthrough")
        params, _profile_context = resolve_product_parameters(
            workflow, generation_parameters)
        params = validate_workflow_parameters(workflow, params)
        return estimate_generation_range(
            self.store.load_jobs(project_id).values(), workflow_id=workflow,
            duration=params["duration"], fps=params["fps"],
            resolution=params["resolution"], steps=params["steps"],
            cold_start=not any(j.get("state") in ("COMPLETED", "SUCCEEDED")
                               for j in self.store.load_jobs(project_id).values())) | {
            "workflow": workflow, "parameters": params,
            "project_id": project.get("id"),
        }

    def _should_reconcile(self, job: Dict[str, Any]) -> bool:
        """Identify accepted/unknown work, including legacy false failures."""
        if job.get("runtime") != "native" or job.get("cancelled"):
            return False
        if is_job_terminal(job) and job.get("state") not in ("FAILED", "GPU_FAILED"):
            return False
        if job.get("submission_state") in ("SUBMISSION_UNKNOWN", "RECONCILING"):
            return True
        if job.get("prompt_id") and job.get("state") not in (
                "COMPLETED", "CANCELLED"):
            return True
        if job.get("state") not in ("FAILED", "GPU_FAILED"):
            return False
        code = str(job.get("failure_code") or job.get("error_category") or "")
        text = str(job.get("technical_details") or job.get("failure_reason") or "").lower()
        timeout_evidence = ("timed out" in text or "timeout" in text
                            or "acknowledgement" in text
                            or "generationtimeouterror" in text)
        return (code in ("COMFYUI_CRASHED", "COMFY_COMMUNICATION_TIMEOUT",
                         "TIMEOUT_ERROR", "GENERATION_TIMEOUT")
                or (code == "COMFYUI_ERROR" and timeout_evidence)) and (
            timeout_evidence or "offline" in text or "reconciliation" in text)

    def _record_submission(self, project_id: str, job_id: str,
                           info: Dict[str, Any]) -> None:
        project_id_found, job = self.store.find_job(job_id)
        if project_id_found != project_id:
            return
        if is_job_terminal(job):
            # Submission acknowledgement can arrive after a user cancellation
            # or another terminal transition. It is telemetry, not authority
            # to rewrite terminal Job state.
            return
        job["prompt_id"] = info.get("prompt_id")
        if info.get("client_id"):
            job["client_id"] = str(info["client_id"])
        job["submission_state"] = "ACKNOWLEDGED"
        job["failure_code"] = ""
        job["error_category"] = ""
        job["failure_reason"] = ""
        job["technical_details"] = ""
        if job.get("state") not in ("CANCELLED", "COMPLETED"):
            job["state"] = "LOADING_MODEL"
            job["current_stage"] = "加载 H3 模型"
            job["lifecycle_state"] = "QUEUED"
            if "LOADING_MODEL" not in job.get("stages", []):
                job.setdefault("stages", []).append("LOADING_MODEL")
        self._save_job(project_id, job)

    def reconcile_job(self, job_id: str, *, start_observer: bool = False) -> Dict[str, Any]:
        """Reconcile local state with queue/history without submitting again."""
        project_id, job = self.store.find_job(job_id)
        runtime_adapter = self._adapter_for_job(job)
        client = getattr(runtime_adapter, "client", None)
        reconcile = getattr(client, "reconcile_prompt", None)
        if client is None or reconcile is None:
            return job
        job["submission_state"] = "RECONCILING"
        self._save_job(project_id, job)
        try:
            found = reconcile(
                prompt_id=job.get("prompt_id"),
                avs_job_id=job.get("id"),
                execution_workflow_sha256=job.get("execution_workflow_sha256"),
                legacy_seed=job.get("seed"),
            )
        except ComfyUICommunicationTimeout as exc:
            job["state"] = "RECONCILING"
            job["lifecycle_state"] = "SUBMISSION_UNKNOWN"
            job["submission_state"] = "SUBMISSION_UNKNOWN"
            job["failure_code"] = "COMFY_COMMUNICATION_TIMEOUT"
            job["error_category"] = "COMFY_COMMUNICATION_TIMEOUT"
            job["user_message"] = "生成中 · 正在同步任务状态"
            job["technical_details"] = f"{type(exc).__name__}: {exc}"
            self._save_job(project_id, job)
            return job
        except ComfyProtocolError as exc:
            # Empty/non-JSON metadata is an observation failure, not proof of execution failure.
            self._mark_reconciling(project_id, job, exc, code="COMFY_PROTOCOL_ERROR")
            return job
        except ComfyUIOfflineError as exc:
            # Job observation cannot prove process death. Engine health is a
            # separate supervisor concern; preserve a reconnectable Job here.
            job["state"] = "RECONCILING"
            job["lifecycle_state"] = "SUBMISSION_UNKNOWN"
            job["submission_state"] = "SUBMISSION_UNKNOWN"
            job["failure_code"] = "COMFY_COMMUNICATION_TIMEOUT"
            job["error_category"] = "COMFY_COMMUNICATION_TIMEOUT"
            job["user_message"] = "正在同步 ComfyUI 任务状态"
            job["technical_details"] = f"observation unavailable: {exc}"
            self._save_job(project_id, job)
            return job
        job["last_observation"] = {
            "timestamp": self.store.timestamp(),
            "source": found.get("source", "queue/history"),
            "status": found.get("status", "UNKNOWN"),
            "prompt_id": found.get("prompt_id") or job.get("prompt_id"),
            "candidates": found.get("candidates"),
            "observation_error": str(found.get("observation_error") or ""),
        }
        self._save_job(project_id, job)
        status = found.get("status")
        if status in ("RUNNING", "COMPLETED") and found.get("prompt_id"):
            job["prompt_id"] = found["prompt_id"]
            job["submission_state"] = "ACKNOWLEDGED"
            job["failure_code"] = ""
            job["error_category"] = ""
            job["failure_reason"] = ""
            job["technical_details"] = ""
            if status == "RUNNING":
                job["state"] = "SAMPLING"
                job["current_stage"] = "同步 ComfyUI 任务"
                job["lifecycle_state"] = "RUNNING"
                job["user_message"] = "生成中 · 正在同步进度"
                if "SAMPLING" not in job.get("stages", []):
                    job.setdefault("stages", []).append("SAMPLING")
            self._save_job(
                project_id, job,
                allow_reconciled_reactivation=(status == "RUNNING"),
            )
            if start_observer and status == "RUNNING":
                self._start_reattach_observer(
                    project_id, job_id, job["prompt_id"], job.get("client_id"))
            elif status == "COMPLETED":
                self._finish_reconciled_job(project_id, job_id, found.get("entry") or {})
        elif status == "FAILED":
            entry = found.get("entry") or {}
            detail = json.dumps(entry.get("status", {}).get("messages", entry),
                                ensure_ascii=False)[:2000]
            job["state"] = "FAILED"
            job["lifecycle_state"] = "FAILED"
            job["submission_state"] = "ACKNOWLEDGED"
            job["failure_code"] = "COMFYUI_ERROR"
            job["error_category"] = "COMFYUI_ERROR"
            job["user_message"] = "ComfyUI 执行失败，请查看任务详情。"
            job["technical_details"] = detail
            job["failure_reason"] = detail
            self._normalize_terminal_job(job, "FAILED", job["user_message"])
            self._save_job(project_id, job)
            self._sync_project_failed(project_id, job, detail)
        else:
            job["state"] = "RECONCILING"
            job["lifecycle_state"] = "SUBMISSION_UNKNOWN"
            job["submission_state"] = "SUBMISSION_UNKNOWN"
            job["failure_code"] = "COMFY_COMMUNICATION_TIMEOUT"
            job["error_category"] = "COMFY_COMMUNICATION_TIMEOUT"
            job["user_message"] = "生成中 · 正在同步任务状态"
            job["technical_details"] = "No matching queue/history entry yet; no duplicate submitted."
            self._save_job(project_id, job)
        return self.store.find_job(job_id)[1]

    def _start_reattach_observer(self, project_id: str, job_id: str,
                                 prompt_id: str, client_id: Optional[str] = None) -> None:
        thread = self._threads.get(job_id)
        if thread and thread.is_alive():
            return
        thread = threading.Thread(target=self._reattach_job,
                                  args=(project_id, job_id, prompt_id, client_id), daemon=True)
        self._threads[job_id] = thread
        thread.start()

    def _reattach_job(self, project_id: str, job_id: str, prompt_id: str, client_id: Optional[str] = None) -> None:
        try:
            _, job = self.store.find_job(job_id)
            runtime_adapter = self._adapter_for_job(job)
            if runtime_adapter is None:
                raise RuntimeError("persisted runtime target is no longer configured")
            state = runtime_adapter.poll(
                prompt_id, timeout_seconds=1800.0, poll_interval=5.0,
                on_event=lambda event: self._record_progress(project_id, job_id, event),
                client_id=client_id)
            if state.get("status") != "COMPLETED":
                raise RuntimeError(f"ComfyUI execution failed: {state.get('messages')}")
            self._finish_reconciled_job(project_id, job_id,
                                        runtime_adapter.client.get_history(prompt_id))
        except (GenerationTimeoutError, ComfyUICommunicationTimeout,
                ComfyUIOfflineError, ComfyProtocolError) as exc:
            project_id_found, job = self.store.find_job(job_id)
            self._mark_reconciling(project_id_found, job, exc)
        except Exception as exc:  # noqa: BLE001 - observer boundary
            project, job = self.store.find_job(job_id)
            # A progress callback, persistence write, or transport adapter can
            # fail while Comfy is still executing. Once prompt_id is durable,
            # only exact queue/history reconciliation may decide terminal
            # truth; an observer exception alone must not fail the Job.
            if job.get("prompt_id") and job.get("submission_state") in (
                    "ACKNOWLEDGED", "SUBMISSION_UNKNOWN", "RECONCILING"):
                try:
                    self.reconcile_job(job_id, start_observer=False)
                except Exception as observation_exc:  # noqa: BLE001
                    try:
                        project, latest = self.store.find_job(job_id)
                        self._mark_reconciling(
                            project, latest, observation_exc,
                            code="COMFY_OBSERVATION_ERROR",
                        )
                    except Exception:
                        # Preserve durable prompt identity even if the store is
                        # temporarily unable to publish another snapshot.
                        pass
                return
            category, friendly = _classify_failure(exc)
            job["state"] = "FAILED"
            job["failure_code"] = category
            job["error_category"] = category
            job["user_message"] = friendly
            job["technical_details"] = f"{type(exc).__name__}: {category}"
            job["failure_reason"] = job["technical_details"]
            self._save_job(project, job)
            self._sync_project_failed(project, job, job["technical_details"])

    def _mark_reconciling(self, project_id: str, job: Dict[str, Any],
                          exc: Exception, code: str = "COMFY_COMMUNICATION_TIMEOUT") -> None:
        """Persist an observation gap without inventing execution failure."""
        job["state"] = "RECONCILING"
        job["lifecycle_state"] = "SUBMISSION_UNKNOWN"
        job["submission_state"] = "SUBMISSION_UNKNOWN"
        job["failure_code"] = code
        job["error_category"] = code
        job["user_message"] = "正在同步 ComfyUI 任务状态"
        job["technical_details"] = f"{type(exc).__name__}: {code}"
        job["failure_reason"] = job["technical_details"]
        if "RECONCILING" not in job.get("stages", []):
            job.setdefault("stages", []).append("RECONCILING")
        self._save_job(project_id, job)

    def _finish_reconciled_job(self, project_id: str, job_id: str,
                               history: Optional[Dict[str, Any]] = None, *,
                               output: Optional[Dict[str, Any]] = None,
                               allow_failed_recovery: bool = False) -> None:
        project_id, job = self.store.find_job(job_id)
        if job.get("state") == "COMPLETED":
            # Terminal owner state wins over late history/observer callbacks.
            if self.output_api._job_media_path(project_id, job) is not None:
                return
        if (is_job_terminal(job)
                and not (allow_failed_recovery
                         and job.get("state") in ("FAILED", "GPU_FAILED", "COMPLETED"))):
            return
        project = self.store.load_project(project_id)
        refs = self.store.load_references(project_id)
        ref_snapshots = list(job.get("reference_assets_snapshot") or [])
        if ref_snapshots:
            current_refs = []
            for binding in ref_snapshots:
                item = refs.get(binding.get("asset_id"))
                if item:
                    current_refs.append({**item, "state": binding.get("approval_state"),
                                         "role": binding.get("role")})
        else:
            current = refs.get(project.get("current_reference_asset_id"))
            current_refs = [current] if current else []
        prompt = job.get("prompt_snapshot") or self.store.load_prompt(project_id) or {}
        guide_bindings = self._restore_guide_bindings(project_id, job)
        guide_prompt_metadata = prompt.get("guide_prompt_compilation")
        persisted_guide_prompt = None
        if isinstance(guide_prompt_metadata, dict):
            execution_prompt = prompt.get("execution_prompt")
            if isinstance(execution_prompt, str):
                persisted_guide_prompt = {
                    **guide_prompt_metadata, "prompt": execution_prompt,
                }
        request = self._build_request(
            project_id, project, prompt, current_refs,
            dict(job.get("generation_parameters") or {}), job.get("camera_motion"),
            guide_bindings, guide_prompt=persisted_guide_prompt)
        runtime_adapter = self._adapter_for_job(job)
        if runtime_adapter is None:
            raise RuntimeError("persisted runtime target is no longer configured")
        snapshot = job.get("workflow_snapshot") or {}
        workflow = snapshot.get("workflow")
        workflow_sha = str(job.get("execution_workflow_sha256") or "")
        if not workflow_sha or not isinstance(workflow, dict):
            raise ResultIdentityError(
                "WORKFLOW_IDENTITY_MISSING", "the durable execution graph is unavailable")
        from runtime.adapters.production_workflow_binding import canonical_workflow_sha256
        if canonical_workflow_sha256(workflow) != workflow_sha:
            raise ResultIdentityError(
                "WORKFLOW_IDENTITY_MISMATCH", "the durable execution graph hash changed")
        expected = expected_save_video_identity(workflow, job_id, workflow_sha)
        pipeline = dict(job.get("result_pipeline") or {})
        persisted_expected = pipeline.get("expected_output_identity")
        if persisted_expected and persisted_expected != expected:
            raise ResultIdentityError(
                "OUTPUT_IDENTITY_MISMATCH", "persisted SaveVideo identity does not match the Job")
        client = getattr(runtime_adapter, "client", None)
        if client is None or not hasattr(client, "collect_output"):
            raise RuntimeError("RESULT_RUNTIME_UNAVAILABLE: selected runtime cannot collect output")
        runtime_identity = dict((job.get("execution_trace") or {}).get("runtime_identity") or {})
        expected_root = str(runtime_identity.get("output_root_fingerprint") or "")
        current_root = str(getattr(client, "output_root_fingerprint", "") or "")
        if expected_root and expected_root != current_root:
            raise ResultIdentityError(
                "RUNTIME_OUTPUT_IDENTITY_MISMATCH",
                "selected runtime output root differs from the Job's runtime")
        prompt_id = str(job.get("prompt_id") or "")
        if not prompt_id:
            raise ResultIdentityError(
                "PROMPT_OUTPUT_ASSOCIATION_FAILURE",
                "the durable Studio Job has no Comfy prompt identity")
        if output is None:
            history = dict(history or {})
            if str(history.get("prompt_id") or prompt_id) != prompt_id:
                raise ResultIdentityError(
                    "PROMPT_OUTPUT_ASSOCIATION_FAILURE",
                    "history prompt identity does not match the Studio Job")
            history.setdefault("prompt_id", prompt_id)
            candidates = summarize_history_outputs(history)
            self._record_result_event(project_id, job_id, "OUTPUT_DISCOVERY", "STARTED",
                                      candidates=candidates)
            try:
                output = client.collect_output(
                    history, job_id, job.get("workflow", ""), {
                        "expected_prompt_id": prompt_id,
                        "expected_output_identity": expected,
                        "execution_workflow_sha256": workflow_sha,
                        "studio_job_id": job_id,
                        "runtime_target": str(job.get("runtime_target") or "production"),
                    })
            except Exception as exc:
                error_code = (getattr(exc, "code", "")
                              or str(exc).split(":", 1)[0])
                failure_stage = ("MEDIA_PROBE" if str(error_code).startswith(
                    "MEDIA_PROBE") else "OUTPUT_DISCOVERY")
                self._record_result_event(
                    project_id, job_id, failure_stage, "FAILED", error=exc,
                    error_code=error_code,
                    candidates=candidates)
                raise
            self._record_result_event(project_id, job_id, "OUTPUT_DISCOVERY", "PASS",
                                      candidates=candidates)
        else:
            runtime_info = output.get("runtime_info") or {}
            observed = runtime_info.get("observed_output") or {}
            prefix_leaf = Path(str(expected.get("filename_prefix") or "")).name
            observed_name = Path(str(observed.get("filename") or "")).name
            if (str(runtime_info.get("prompt_id") or "") != prompt_id
                    or str(runtime_info.get("studio_job_id") or "") != job_id
                    or str(runtime_info.get("workflow_sha256") or "") != workflow_sha
                    or str(runtime_info.get("output_root_fingerprint") or "") != current_root
                    or str(observed.get("node_id") or "") != str(expected["node_id"])
                    or not observed_name.startswith(prefix_leaf)):
                raise ResultIdentityError(
                    "OUTPUT_IDENTITY_MISMATCH",
                    "collected output does not match the durable Job identity")
            if expected_root and current_root and expected_root != current_root:
                raise ResultIdentityError(
                    "RUNTIME_OUTPUT_IDENTITY_MISMATCH",
                    "collected media came from a different runtime output root")
        pipeline["expected_output_identity"] = expected
        runtime_info = output.get("runtime_info") or {}
        observed_output = runtime_info.get("observed_output") or {}
        pipeline["observed_output_identity"] = {
            "prompt_id": prompt_id,
            "studio_job_id": job_id,
            "workflow_sha256": workflow_sha,
            "runtime_output_fingerprint": str(
                runtime_info.get("output_root_fingerprint") or current_root),
            "node_id": str(observed_output.get("node_id") or expected["node_id"]),
            "filename": Path(str(observed_output.get("filename") or "")).name,
            "subfolder": str(observed_output.get("subfolder") or "").replace("\\", "/"),
            "size": observed_output.get("size"),
            "format": str(observed_output.get("format") or "")[:64],
        }
        pipeline["current_stage"] = "OUTPUT_DISCOVERY"
        pipeline["status"] = "PASS"
        job["result_pipeline"] = pipeline
        runtime_output = str(output.get("video_path", ""))
        if (not runtime_output or not Path(runtime_output).is_file()
                or Path(runtime_output).stat().st_size <= 0):
            raise ResultIdentityError("OUTPUT_FILE_MISSING", "runtime returned no media file")
        job["runtime_output_path"] = runtime_output
        job["source_output_path"] = runtime_output
        job["result_pipeline"]["runtime_output_fingerprint"] = current_root
        self._save_job(project_id, job)
        self._record_result_event(project_id, job_id, "MEDIA_PROBE", "STARTED")
        self._update_delivery_probe(project_id, job, runtime_output)
        delivery_status = str((job.get("execution_trace") or {}).get(
            "delivery", {}).get("status") or "PROBE_UNAVAILABLE")
        self._record_result_event(
            project_id, job_id, "MEDIA_PROBE",
            "PASS" if delivery_status == "PROBED" else "UNAVAILABLE",
            detail={"probe_status": delivery_status,
                    "media_bytes": Path(runtime_output).stat().st_size
                    if Path(runtime_output).is_file() else None})
        self._record_result_event(project_id, job_id, "PACKAGING", "STARTED")
        try:
            self.output_api.build_real_output_package(project_id, job, output, request)
        except Exception as exc:
            self._record_result_event(
                project_id, job_id, "PACKAGING", "FAILED", error=exc,
                error_code=str(exc).split(":", 1)[0])
            raise
        self._record_result_event(
            project_id, job_id, "PACKAGING", "PASS",
            detail={"package_built": True,
                    "media_bytes": Path(runtime_output).stat().st_size})
        job["runtime_output_path"] = runtime_output
        job["source_output_path"] = runtime_output
        job["final_output_path"] = ""
        job["output_path"] = runtime_output
        self._record_result_event(project_id, job_id, "OUTPUT_DELIVERY", "STARTED")
        try:
            final_video = self.output_api.copy_to_study_output(
                project_id, job, runtime_output)
        except Exception as exc:  # delivery failure is not generation failure
            job["delivery_state"] = "OUTPUT_DELIVERY_FAILED"
            job["delivery_error"] = sanitize_result_error(
                f"{type(exc).__name__}: {exc}")
            job["user_message"] = "视频已生成，但复制到指定目录失败"
            self._record_result_event(
                project_id, job_id, "OUTPUT_DELIVERY", "FAILED", error=exc,
                error_code="OUTPUT_DELIVERY_FAILURE")
        else:
            job["final_output_path"] = str(final_video)
            job["output_path"] = str(final_video)
            job["delivery_state"] = "DELIVERED"
            job["delivery_error"] = ""
            self._record_result_event(project_id, job_id, "OUTPUT_DELIVERY", "PASS",
                                      detail={"media_bytes": final_video.stat().st_size})
        job["state"] = "COMPLETED"
        job["lifecycle_state"] = "SUCCEEDED"
        job["submission_state"] = "ACKNOWLEDGED"
        job["progress"] = 100.0
        job["current_stage"] = "保存视频"
        job["eta_seconds"] = 0.0
        job.setdefault("stages", []).append("COMPLETED")
        job["package_built"] = True
        self._normalize_terminal_job(job, "COMPLETED")
        self._record_result_event(project_id, job_id, "RESULT_PERSISTENCE", "STARTED")
        try:
            self._save_job(project_id, job, preserve_result_pipeline=True)
        except Exception as exc:
            self._record_result_event(
                project_id, job_id, "RESULT_PERSISTENCE", "FAILED", error=exc,
                error_code="RESULT_PERSISTENCE_FAILURE")
            raise
        self._record_result_event(project_id, job_id, "RESULT_PERSISTENCE", "PASS",
                                  detail={"package_built": True})
        self._sync_project_complete(project_id, job)

    def _restore_guide_bindings(self, project_id: str, job: dict) -> list[dict]:
        trace = job.get("execution_trace") or {}
        saved = list(trace.get("guide_bindings") or
                     job.get("guide_bindings_snapshot") or [])
        if not saved:
            return []
        rows = [{
            "guide_id": f"guide-{item.get('ordinal', index)}",
            "asset_id": item.get("asset_id"),
            "role": item.get("role"),
            "requested_time_seconds": item.get("requested_time_seconds"),
            "ordinal": item.get("ordinal", index),
            "content_sha256": item.get("content_sha256"),
            "source_identity": item.get("source_identity"),
            "approval_state": (item.get("approval_evidence") or {}).get(
                "state", "APPROVED"),
        } for index, item in enumerate(saved, start=1)]
        return resolve_guide_bindings(
            project_id, rows, self.store.load_references(project_id),
            target_frame_count=int((job.get("generation_parameters") or {}).get(
                "frame_count", 0)),
            fps=NATIVE_H3_FPS, workflow_id=str(job.get("workflow") or ""),
            reference_root=self.store.input_dir(project_id))

    def _recover_completed_output(self, project_id: str,
                                  job: Dict[str, Any]) -> bool:
        """Recover a successful Comfy result whose delivery copy was lost.

        This is deliberately bounded to a persisted native ``prompt_id`` and
        a history entry reporting success.  It does not submit or retry work.
        """
        if job.get("runtime") != "native":
            return False
        if job.get("final_output_path") and Path(
                str(job["final_output_path"])).is_file():
            return True
        client = getattr(self._adapter_for_job(job), "client", None)
        if client is None or not hasattr(client, "get_history"):
            return False
        try:
            if job.get("runtime_output_path") and Path(
                    str(job["runtime_output_path"])).is_file():
                final_video = self.output_api.copy_to_study_output(
                    project_id, job, str(job["runtime_output_path"]))
                job["final_output_path"] = str(final_video)
                job["output_path"] = str(final_video)
                job["delivery_state"] = "DELIVERED"
                job["delivery_error"] = ""
                self._save_job(project_id, job)
            elif job.get("prompt_id"):
                history = client.get_history(str(job["prompt_id"]))
                status = history.get("status", {}) if isinstance(history, dict) else {}
                if status.get("status_str") != "success" or not status.get("completed"):
                    return False
                self._finish_reconciled_job(project_id, str(job["id"]), history)
            else:
                return False
            _, recovered = self.store.find_job(str(job["id"]))
            return bool(recovered.get("final_output_path")) and Path(
                str(recovered["final_output_path"])).is_file()
        except Exception:
            # Public reads must remain available when the runtime is stopped;
            # the existing OUTPUT_ERROR projection explains the missing file.
            return False

    def recover_result(self, job_id: str) -> Dict[str, Any]:
        """Reconcile one already-submitted native Job without a new /prompt."""
        lock = self._recovery_locks.setdefault(job_id, threading.Lock())
        with lock:
            project_id, job = self.store.find_job(job_id)
            if job.get("runtime") != "native":
                raise ValueError("RESULT_RECOVERY_NATIVE_ONLY")
            if job.get("state") == "CANCELLED" or job.get("cancelled"):
                raise ValueError("RESULT_RECOVERY_CANCELLED_JOB")
            if job.get("state") == "COMPLETED":
                media = self.output_api._job_media_path(project_id, job)
                if media is not None:
                    job = self._reconcile_completed_packaging(project_id, job)
                    return _recovery_job_payload(job)

            prompt_id = str(job.get("prompt_id") or "")
            workflow_sha = str(job.get("execution_workflow_sha256") or "")
            snapshot = job.get("workflow_snapshot") or {}
            workflow = snapshot.get("workflow")
            if not prompt_id or not workflow_sha or not isinstance(workflow, dict):
                raise ValueError("RESULT_RECOVERY_IDENTITY_INCOMPLETE")
            from runtime.adapters.production_workflow_binding import canonical_workflow_sha256
            if canonical_workflow_sha256(workflow) != workflow_sha:
                raise ValueError("RESULT_RECOVERY_WORKFLOW_SHA_MISMATCH")
            expected = expected_save_video_identity(workflow, job_id, workflow_sha)
            pipeline = dict(job.get("result_pipeline") or {})
            prior_expected = pipeline.get("expected_output_identity")
            if prior_expected and prior_expected != expected:
                raise ValueError("RESULT_RECOVERY_OUTPUT_IDENTITY_MISMATCH")

            runtime_adapter = self._adapter_for_job(job)
            client = getattr(runtime_adapter, "client", None)
            if runtime_adapter is None or client is None or not hasattr(client, "get_history"):
                raise ValueError("RESULT_RECOVERY_RUNTIME_UNAVAILABLE")
            runtime_identity = dict((job.get("execution_trace") or {}).get(
                "runtime_identity") or {})
            if int(runtime_identity.get("identity_schema_version") or 1) >= 2:
                expected_runtime_id = (
                    "experimental-h3-8190" if job.get("runtime_target") == "experimental"
                    else "production-h3-8189")
                runtime_spec = getattr(runtime_adapter, "runtime_identity_spec", {}) or {}
                if (runtime_identity.get("runtime_id") != expected_runtime_id
                        or runtime_spec.get("runtime_id") != expected_runtime_id):
                    raise ValueError("RESULT_RECOVERY_RUNTIME_IDENTITY_MISMATCH")
                if job.get("runtime_target") == "experimental" and (
                        runtime_identity.get("comfyui_version") != "0.36.0"
                        or runtime_identity.get("comfyui_git_sha")
                        != "ee71d5c4993f29086b27fde1629a945ae48425bf"
                        or runtime_identity.get("runtime_config_fingerprint")
                        != runtime_spec.get("config_fingerprint")):
                    raise ValueError("RESULT_RECOVERY_RUNTIME_FINGERPRINT_MISMATCH")
            expected_port = runtime_identity.get("port")
            actual_port = urlsplit(str(getattr(client, "base_url", ""))).port
            if expected_port is not None and actual_port != int(expected_port):
                raise ValueError("RESULT_RECOVERY_RUNTIME_TARGET_MISMATCH")
            current_root = str(getattr(client, "output_root_fingerprint", "") or "")
            saved_root = str(runtime_identity.get("output_root_fingerprint") or "")
            if saved_root and saved_root != current_root:
                raise ValueError("RESULT_RECOVERY_OUTPUT_ROOT_MISMATCH")
            if not current_root:
                raise ValueError("RESULT_RECOVERY_OUTPUT_ROOT_UNIDENTIFIED")
            pipeline["expected_output_identity"] = expected
            job["result_pipeline"] = pipeline
            self._save_job(project_id, job)
            self._record_result_event(project_id, job_id, "RECOVERY", "STARTED")

            # Reuse a prior, durably associated file only when every identity
            # field and the explicit runtime output-root fingerprint match.
            observed = pipeline.get("observed_output_identity") or {}
            output = None
            if (observed.get("prompt_id") == prompt_id
                    and observed.get("studio_job_id") == job_id
                    and observed.get("workflow_sha256") == workflow_sha
                    and observed.get("runtime_output_fingerprint") == current_root
                    and observed.get("node_id") == expected.get("node_id")):
                expected_prefix = str(expected.get("filename_prefix") or "")
                prefix_path = Path(expected_prefix.replace("\\", "/"))
                expected_folder = "" if str(prefix_path.parent) == "." else str(prefix_path.parent)
                filename = Path(str(observed.get("filename") or "")).name
                subfolder = str(observed.get("subfolder") or "").replace("\\", "/")
                root = Path(str(getattr(client, "output_root", ""))).expanduser().resolve()
                candidate = (root / subfolder / filename).resolve()
                try:
                    candidate.relative_to(root)
                    within_root = True
                except ValueError:
                    within_root = False
                if (within_root and subfolder == expected_folder
                        and filename.startswith(prefix_path.name)
                        and candidate.is_file() and candidate.stat().st_size > 0):
                    output = {
                        "job_id": f"recovered-{job_id}",
                        "video_path": str(candidate),
                        "workflow_id": job.get("workflow"),
                        "metadata": {},
                        "runtime_info": {
                            "prompt_id": prompt_id,
                            "studio_job_id": job_id,
                            "workflow_sha256": workflow_sha,
                            "output_root_fingerprint": current_root,
                            "observed_output": {
                                "node_id": observed.get("node_id"),
                                "filename_prefix": expected_prefix,
                                "filename": filename,
                                "subfolder": subfolder,
                                "size": candidate.stat().st_size,
                                "format": observed.get("format") or "",
                            },
                        },
                    }

            try:
                if output is None:
                    # Exact prompt lookup on the Job-selected runtime only.
                    history = client.get_history(prompt_id)
                    status = history.get("status") or {}
                    if (str(status.get("status_str") or "").lower() != "success"
                            or not status.get("completed")):
                        raise ResultIdentityError(
                            "COMFY_HISTORY_NOT_TERMINAL_SUCCESS",
                            "the exact Comfy prompt has no terminal-success history")
                    history = dict(history)
                    if str(history.get("prompt_id") or prompt_id) != prompt_id:
                        raise ResultIdentityError(
                            "PROMPT_OUTPUT_ASSOCIATION_FAILURE",
                            "history prompt identity does not match the Studio Job")
                    history.setdefault("prompt_id", prompt_id)
                    self._record_result_event(
                        project_id, job_id, "COMFY_HISTORY", "COMPLETED",
                        candidates=summarize_history_outputs(history),
                        detail={"history_status": "COMPLETED",
                                "output_count": len(summarize_history_outputs(history))})
                    self._finish_reconciled_job(
                        project_id, job_id, history,
                        allow_failed_recovery=True)
                else:
                    self._finish_reconciled_job(
                        project_id, job_id, output=output,
                        allow_failed_recovery=True)
            except Exception as exc:
                self._record_result_event(
                    project_id, job_id, "RECOVERY", "FAILED", error=exc,
                    error_code=getattr(exc, "code", "") or str(exc).split(":", 1)[0])
                raise
            recovered_project, recovered = self.store.find_job(job_id)
            if (recovered.get("state") != "COMPLETED"
                    or self.output_api._job_media_path(recovered_project, recovered) is None):
                error = ResultIdentityError(
                    "RESULT_RECOVERY_INCOMPLETE",
                    "reconciliation did not produce a Job-bound media Result")
                self._record_result_event(
                    project_id, job_id, "RECOVERY", "FAILED", error=error,
                    error_code=error.code)
                raise ValueError(error.code)
            self._record_result_event(project_id, job_id, "RECOVERY", "PASS",
                                      detail={"package_built": True})
            return _recovery_job_payload(self.store.find_job(job_id)[1])

    def retry_output_delivery(self, job_id: str) -> Dict[str, Any]:
        """Retry only the destination copy; never rerun Comfy generation."""
        project_id, job = self.store.find_job(job_id)
        if job.get("runtime") != "native" or job.get("state") != "COMPLETED":
            raise ValueError("只有已成功生成的视频可以重试交付")
        if not self._recover_completed_output(project_id, job):
            raise ValueError("Runtime 输出不存在，无法重试复制")
        return _decorate_job(self.store.find_job(job_id)[1])

    def create_delivery(self, job_id: str, request: Dict[str, Any]) -> Dict[str, Any]:
        """Run A8 post-processing and persist path-free delivery provenance."""
        from runtime.a8_delivery import DeliveryError

        project_id, job = self.store.find_job(job_id)
        target_resolution = str(request.get("target_resolution") or "")
        delivery_fps = request.get("delivery_fps")
        try:
            result = self.output_api.create_delivery(
                job_id, target_resolution=target_resolution,
                delivery_fps=delivery_fps)
        except DeliveryError as exc:
            # The per-Job delivery manifest is the detailed stage record.
            # Mirror only safe identifiers/status into the Job trace.
            try:
                available = self.output_api.list_deliveries(job_id).get("items", [])
                failed = next((item for item in reversed(available)
                               if item.get("target_resolution") == target_resolution
                               and item.get("delivery_fps") == delivery_fps
                               and item.get("status") == "FAILED"), None)
                trace = dict(job.get("execution_trace") or {})
                if failed:
                    records = list(trace.get("delivery_outputs") or [])
                    records = [item for item in records
                               if item.get("delivery_id") != failed.get("delivery_id")]
                    records.append(failed)
                    trace["delivery_outputs"] = records[-12:]
                trace["delivery_last_error"] = {
                    "stage": "A8_DELIVERY",
                    "error_code": exc.code,
                    "target_resolution": target_resolution[:32],
                    "delivery_fps": delivery_fps
                    if type(delivery_fps) is int else None,
                    "timestamp": self.store.timestamp(),
                }
                job["execution_trace"] = trace
                self._save_job(project_id, job, preserve_result_pipeline=True)
            except Exception:
                pass
            raise

        trace = dict(job.get("execution_trace") or {})
        records = list(trace.get("delivery_outputs") or [])
        records = [item for item in records
                   if item.get("delivery_id") != result.get("delivery_id")]
        records.append(result)
        trace["delivery_outputs"] = records[-12:]
        trace.pop("delivery_last_error", None)
        job["execution_trace"] = trace
        self._save_job(project_id, job, preserve_result_pipeline=True)
        return result

    def advance(self, job_id: str, elapsed_seconds: float) -> Dict[str, Any]:
        """Explicit deterministic progression (mock tests only)."""
        project_id, job = self.store.find_job(job_id)
        return self._apply_elapsed(project_id, job, float(elapsed_seconds))

    def fail_job(self, job_id: str, reason: str = "mock GPU failure") -> Dict[str, Any]:
        project_id, job = self.store.find_job(job_id)
        if is_job_terminal(job):
            raise ValueError(f"job already in terminal state {job['state']}")
        job["state"] = "GPU_FAILED"
        job["failure_reason"] = reason
        job["lifecycle_state"] = "FAILED"
        job["user_message"] = reason
        self._normalize_terminal_job(job, "GPU_FAILED", reason)
        self._save_job(project_id, job)
        self._sync_project_failed(project_id, job, reason)
        return job

    def cancel(self, job_id: str) -> Dict[str, Any]:
        project_id, job = self.store.find_job(job_id)
        if is_job_terminal(job):
            raise ValueError(f"job already in terminal state {job['state']}")
        job["state"] = "CANCELLED"
        job["lifecycle_state"] = "CANCELLED"
        job["submission_state"] = "CANCELLED"
        job["cancelled"] = True
        job["failure_reason"] = "cancelled by user"
        job["user_message"] = "已取消"
        job["stages"].append("CANCELLED")
        self._normalize_terminal_job(job, "CANCELLED", "已取消")
        self._save_job(project_id, job)
        self.store.append_audit(project_id, {
            "actor": "architect", "event": "cancel_job",
            "from": "GPU_RUNNING", "to": "CANCELLED",
            "detail": {"job_id": job_id},
        })
        for attempt in range(3):
            try:
                build_study_state(self.store, project_id)
                break
            except PermissionError:
                if attempt == 2:
                    raise
                time.sleep(0.02 * (attempt + 1))
        return job

    # ------------------------------------------------------------------ #
    def _build_request(self, project_id: str, project: dict, prompt: dict,
                       approved_refs: List[dict], params: dict,
                       camera_motion: Optional[str],
                       guide_bindings: Optional[List[dict]] = None, *,
                       guide_prompt: Optional[dict] = None) -> Any:
        from runtime.adapters.runtime_adapter import VideoGenerationRequest
        intent = self.store.load_intent(project_id) or {}
        refs = [{
            "asset_id": r["id"],
            "project_id": project_id,
            "role": r.get("role", "first_frame"),
            "media_type": r.get("media_type", "image"),
            "approval_state": r.get("state"),
            "path_or_ref": r.get("stored_path") or r.get("filename", "ref.png"),
            "filename": r.get("filename", "ref.png"),
            "sha256": r.get("sha256"),
            "source_identity": r.get("source_identity"),
            "requested_fidelity": r.get("requested_fidelity"),
        } for r in approved_refs]
        guides = list(guide_bindings or [])
        if guides:
            execution_prompt = str(prompt.get("prompt") or "")
            guide_prompt_metadata = None
            if guide_prompt is not None:
                expected_indexes = [item.get("resolved_frame_idx") for item in guides]
                if guide_prompt.get("guide_frame_indexes") != expected_indexes:
                    raise ValueError("GUIDE_PROMPT_FRAME_IDENTITY_MISMATCH")
                source_digest = hashlib.sha256(
                    str(prompt.get("prompt") or "").encode("utf-8")).hexdigest()
                if source_digest != guide_prompt.get("source_prompt_sha256"):
                    raise ValueError("GUIDE_PROMPT_SOURCE_HASH_MISMATCH")
                execution_prompt = str(guide_prompt.get("prompt") or "")
                execution_digest = hashlib.sha256(
                    execution_prompt.encode("utf-8")).hexdigest()
                if execution_digest != guide_prompt.get("execution_prompt_sha256"):
                    raise ValueError("GUIDE_PROMPT_HASH_MISMATCH")
                guide_prompt_metadata = {key: value for key, value in guide_prompt.items()
                                         if key != "prompt"}
        else:
            execution_prompt = str(prompt.get("prompt") or "")
            guide_prompt_metadata = None
        return VideoGenerationRequest(
            study_id=project_id,
            reference_assets=refs,
            guide_frames=guides,
            workflow_id=prompt["workflow"],
            camera_motion=camera_motion or normalize_camera_motion(prompt["workflow"]),
            generation_parameters=params,
            prompt_payload={
                "mode": prompt.get("mode", "I2VA"),
                "prompt": execution_prompt,
                "alignment": prompt.get("alignment", ""),
                "integrated_multimodal_description": prompt.get(
                    "integrated_multimodal_description", ""),
                "overall_soundscape": prompt.get("overall_soundscape", ""),
                "non_diegetic_music": "N/A",
                "prompt_hash": prompt["prompt_hash"],
                "a4_profile": prompt.get("a4_profile") or {},
                "reference_bindings": list(prompt.get("reference_bindings") or []),
                "guide_prompt_compilation": guide_prompt_metadata,
            },
            output_spec={"container": "mp4", "codec": "h264", "fps": params["fps"],
                         "resolution": params.get("resolution", "1344x768"),
                         "native_generation": {
                             "width": params["width"],
                             "height": params["height"],
                             "fps": params["fps"],
                             "frame_count": params["frame_count"],
                             "duration_seconds": params["resolved_duration_seconds"],
                             "requested_duration_seconds": params["duration"],
                         },
                         "delivery": {"width": params["width"],
                                      "height": params["height"],
                                      "fps": params.get("delivery_fps", 24),
                                      "upscale_method": None,
                                      "interpolation_method": None,
                                      "postprocess_applied": False,
                                      "status": "NOT_PRODUCED"},
                         "report_format": "json"},
            gates={"reference_approved": True, "intent_confirmed": True,
                   "prompt_verified": True, "risk_reviewed": True},
        )

    def _run_real_job(self, project_id: str, job_id: str, request: Any,
                      prepared: Optional[Dict[str, Any]] = None,
                      before_submit: Optional[Callable[[], Optional[bool]]] = None,
                      runtime_target: str = "production") -> None:
        job = self.store.load_jobs(project_id).get(job_id)
        if job is None:
            return
        runtime_adapter = self._adapter_for_target(runtime_target)
        if runtime_adapter is None:
            return
        try:
            self._stage_refs_to_comfy_input(
                project_id, request, runtime_target, runtime_adapter)
            prepared = (prepared if prepared is not None else
                        runtime_adapter.prepare(request)
                        if hasattr(runtime_adapter, "prepare") else None)
            if prepared is not None and hasattr(runtime_adapter, "attach_job_identity"):
                prepared = runtime_adapter.attach_job_identity(prepared, job_id)
            job = self.store.load_jobs(project_id).get(job_id) or job
            approved = list(request.reference_assets)
            snapshot_options = {}
            ref2va_plan = (prepared or {}).get("ref2va_plan")
            if ref2va_plan is not None:
                snapshot_options["ref2va_plan"] = ref2va_plan
            job["workflow_snapshot"] = self._build_workflow_snapshot(
                request, approved,
                prepared["translated_payload"] if prepared else {},
                **snapshot_options,
            )
            job["workflow_snapshot_id"] = job["workflow_snapshot"]["snapshot_id"]
            job["workflow_hash"] = job["workflow_snapshot"]["workflow_hash"]
            job["execution_workflow_sha256"] = job["workflow_snapshot"]["execution_workflow_sha256"]
            job["asset_hash"] = job["workflow_snapshot"]["asset_hash"]
            trace = dict(job.get("execution_trace") or {})
            trace["workflow_sha256"] = job["execution_workflow_sha256"]
            if job["workflow_snapshot"].get("reference_execution_plan"):
                trace["reference_execution_plan"] = job["workflow_snapshot"][
                    "reference_execution_plan"]
                trace["ref2va_count"] = len(trace[
                    "reference_execution_plan"].get("bindings") or [])
                trace["ref2va_backend"] = "MiniMaxH3ReferenceToVideo"
            is_native_comfy = (getattr(runtime_adapter, "name", "") == "native"
                               and hasattr(getattr(runtime_adapter, "client", None),
                                           "collect_output"))
            if is_native_comfy:
                try:
                    expected_output = expected_save_video_identity(
                        job["workflow_snapshot"]["workflow"], job_id,
                        job["execution_workflow_sha256"])
                except Exception as exc:
                    self._record_result_event(
                        project_id, job_id, "SAVE_VIDEO_CONTRACT", "FAILED",
                        error=exc, error_code=getattr(exc, "code", "SAVE_VIDEO_CONTRACT_INVALID"))
                    raise
                pipeline = dict(job.get("result_pipeline") or {})
                pipeline["expected_output_identity"] = expected_output
                job["result_pipeline"] = pipeline
                trace["runtime_identity"] = dict(trace.get("runtime_identity") or {})
                trace["runtime_identity"]["output_root_fingerprint"] = (
                    self._runtime_output_fingerprint(runtime_adapter) or None)
                if prepared is not None:
                    prepared["_result_event_callback"] = lambda event: self._record_result_event(
                        project_id, job_id,
                        str(event.get("stage") or "OUTPUT_DISCOVERY"),
                        str(event.get("status") or "UNKNOWN"),
                        error=event.get("error"),
                        error_code=str(event.get("error_code") or ""),
                        candidates=event.get("candidates"),
                        detail=event.get("detail"),
                    )
            if prepared and prepared.get("guide_capability"):
                trace["runtime_capability"] = prepared["guide_capability"]
            if prepared and prepared.get("translated_payload"):
                try:
                    trace["final_execution_parameters"] = actual_execution_parameters(
                        prepared["translated_payload"], str(request.workflow_id), trace)
                    trace["status"] = "BOUND"
                except (KeyError, TypeError, ValueError) as exc:
                    trace["status"] = "TRACE_INCOMPLETE"
                    trace["trace_error"] = type(exc).__name__
            else:
                trace["status"] = "TRACE_PAYLOAD_UNAVAILABLE"
            job["execution_trace"] = trace
            self._save_job(project_id, job)
            if is_native_comfy:
                self._record_result_event(
                    project_id, job_id, "SAVE_VIDEO_CONTRACT", "PASS")
            if before_submit is not None:
                # Acceptance runners persist an ambiguity marker immediately
                # before the only /prompt boundary. After interruption they
                # reconcile this exact Job instead of resubmitting it.
                if before_submit() is False:
                    return
                # The callback writes through StudioStore, so refresh the local
                # record before entering an exception path. Otherwise an old
                # NOT_STARTED snapshot could overwrite the durable ambiguity
                # marker after an uncertain /prompt failure.
                job = self.store.load_jobs(project_id).get(job_id) or job
                if job.get("cancelled") or job.get("state") == "CANCELLED":
                    return
            # Persist an ambiguity marker immediately before the only native
            # submit boundary. If acknowledgement persistence fails after
            # Comfy accepts /prompt, reconciliation searches by Job/workflow
            # identity instead of risking a duplicate generation.
            job = self.store.load_jobs(project_id).get(job_id) or job
            if is_native_comfy:
                job["submission_state"] = "SUBMITTING"
                job["lifecycle_state"] = "SUBMISSION_PENDING"
                self._save_job(project_id, job)
            generate = runtime_adapter.generate
            if prepared is not None and "prepared" in inspect.signature(generate).parameters:
                snapshot = generate(request, prepared=prepared)
            else:
                # CPU/test adapters from older contract revisions do not need
                # the prepared graph.  Real NativeRuntimeAdapter always takes
                # the exact object persisted above.
                snapshot = generate(request)
            submitted_sha = snapshot.get("execution_workflow_sha256")
            if submitted_sha and submitted_sha != job["execution_workflow_sha256"]:
                raise RuntimeError("EXECUTION_WORKFLOW_IDENTITY_MISMATCH: prepared graph "
                                   "differs from submitted graph")
            # re-read the latest record: user may have cancelled mid-run
            job = self.store.load_jobs(project_id).get(job_id) or job
            if job.get("cancelled") or job["state"] == "CANCELLED":
                return
            output = runtime_adapter.get_output(snapshot["job_id"])
            latest = self.store.load_jobs(project_id).get(job_id) or job
            if is_job_terminal(latest):
                # Do not publish a late successful callback over an owner
                # cancellation. Runtime artifacts remain recoverable.
                return
            job = latest
            if is_native_comfy:
                self._finish_reconciled_job(project_id, job_id, output=output)
            else:
                # Lightweight runtime fakes preserve the historical CPU-only
                # adapter contract; the strong Comfy identity gate above is
                # mandatory for the production NativeRuntimeAdapter path.
                runtime_output = str(output.get("video_path", ""))
                self._update_delivery_probe(project_id, job, runtime_output)
                self._record_result_event(project_id, job_id, "PACKAGING", "STARTED")
                self.output_api.build_real_output_package(
                    project_id, job, output, request)
                job["runtime_output_path"] = runtime_output
                job["source_output_path"] = runtime_output
                job["final_output_path"] = ""
                job["output_path"] = runtime_output
                try:
                    final_video = self.output_api.copy_to_study_output(
                        project_id, job, runtime_output)
                except Exception as delivery_exc:
                    job["delivery_state"] = "OUTPUT_DELIVERY_FAILED"
                    job["delivery_error"] = sanitize_result_error(
                        f"{type(delivery_exc).__name__}: {delivery_exc}")
                    job["user_message"] = "视频已生成，但复制到指定目录失败"
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
                self._normalize_terminal_job(job, "COMPLETED")
                self._save_job(project_id, job)
                self._sync_project_complete(project_id, job)
            job = self.store.load_jobs(project_id).get(job_id) or job
            self.store.append_audit(project_id, {
                "actor": "runtime", "event": "job_completed",
                "from": "GPU_RUNNING", "to": "COMPLETED",
                "detail": {"job_id": job_id,
                           "prompt_id": snapshot.get("prompt_id")},
            })
        except Exception as exc:  # noqa: BLE001
            latest = self.store.load_jobs(project_id).get(job_id)
            if latest and latest.get("state") == "CANCELLED":
                # An adapter error arriving after cancellation is not a new
                # generation failure.
                return
            job = latest or job
            native_record = {}
            native_job_key = (prepared or {}).get("job_id") if isinstance(prepared, dict) else None
            runtime_jobs = getattr(runtime_adapter, "jobs", {}) or {}
            if native_job_key:
                native_record = runtime_jobs.get(native_job_key) or {}
            acknowledged_prompt = str(native_record.get("prompt_id") or "")
            if acknowledged_prompt and not job.get("prompt_id"):
                job["prompt_id"] = acknowledged_prompt
                job["submission_state"] = "RECONCILING"
                job["prompt_id_persistence_recovered"] = True
                try:
                    self._save_job(project_id, job)
                    job = self.store.load_jobs(project_id).get(job_id) or job
                except Exception:
                    # The pre-submit SUBMITTING snapshot remains the durable
                    # signal if the store is still unavailable.
                    pass
            message = str(exc).lower()
            runtime_mismatch = "missing_node_type" in message or "node type" in message and "not found" in message
            category, friendly = _classify_failure(exc, runtime_mismatch=runtime_mismatch)
            result_stage = str((job.get("result_pipeline") or {}).get(
                "current_stage") or "")
            if result_stage in {
                    "COMFY_HISTORY", "OUTPUT_DISCOVERY", "MEDIA_PROBE",
                    "PACKAGING", "RESULT_PERSISTENCE", "SAVE_VIDEO_CONTRACT",
                    "SAVE_VIDEO_NODE", "COMFY_EXECUTION", "RECOVERY",
                    "OUTPUT_DELIVERY"}:
                self._record_result_event(
                    project_id, job_id, result_stage, "FAILED", error=exc,
                    error_code=(getattr(exc, "code", "")
                                or str(exc).split(":", 1)[0]))
            ambiguous_submission = job.get("submission_state") in (
                "SUBMITTING", "SUBMISSION_UNKNOWN", "RECONCILING")
            if (ambiguous_submission or isinstance(
                    exc, (ComfyUICommunicationTimeout, ComfyUIOfflineError,
                          ComfyProtocolError, GenerationTimeoutError))):
                # A transport timeout is ambiguous. The server may have
                # accepted the prompt, so keep the Job reconnectable instead
                # of poisoning it as a retryable GPU/engine failure. This also
                # covers non-timeout exceptions after an A4.2 submit boundary,
                # until queue/history proves what ComfyUI accepted.
                self._mark_reconciling(project_id, job, exc)
                return
            job["state"] = "GPU_FAILED" if category == "GPU_ERROR" else "FAILED"
            job["lifecycle_state"] = "FAILED"
            job["failure_code"] = category
            job["error_category"] = category
            job["user_message"] = friendly
            if result_stage in {
                    "COMFY_HISTORY", "OUTPUT_DISCOVERY", "MEDIA_PROBE",
                    "PACKAGING", "RESULT_PERSISTENCE", "SAVE_VIDEO_CONTRACT",
                    "SAVE_VIDEO_NODE", "COMFY_EXECUTION", "RECOVERY",
                    "OUTPUT_DELIVERY"}:
                failure_code = (getattr(exc, "code", "")
                                or str(exc).split(":", 1)[0])
                safe_code = "".join(char for char in str(failure_code).upper()
                                    if char.isalnum() or char in "_-")[:80]
                job["technical_details"] = (
                    f"{type(exc).__name__}: {safe_code or 'RESULT_PIPELINE_FAILURE'}")
            elif getattr(runtime_adapter, "name", "") == "native":
                safe_code = "".join(char for char in str(category).upper()
                                    if char.isalnum() or char in "_-")[:80]
                job["technical_details"] = (
                    f"{type(exc).__name__}: {safe_code or 'RUNTIME_FAILURE'}")
            else:
                job["technical_details"] = sanitize_result_error(
                    f"{type(exc).__name__}: {exc}")
            if category == "COMFYUI_CRASHED":
                job["technical_details"] = (
                    "COMFYUI_NATIVE_CRASH: " + job["technical_details"]
                )
            # Keep the persisted technical reason for diagnostics/backward
            # compatibility; normal UI reads friendly_reason instead.
            job["failure_reason"] = job["technical_details"]
            job["stages"].append(job["state"])
            self._normalize_terminal_job(job, job["state"], friendly)
            self._save_job(project_id, job)
            self._sync_project_failed(project_id, job, job["technical_details"])

    def _record_progress(self, project_id: str, job_id: str,
                          event: Dict[str, Any]) -> None:
        job = self.store.load_jobs(project_id).get(job_id)
        if not job or is_job_terminal(job):
            return
        event_prompt = event.get("prompt_id")
        if event_prompt and job.get("prompt_id") and str(event_prompt) != str(job["prompt_id"]):
            return
        previous_stage = job.get("current_stage", "执行工作流")
        event_name = str(event.get("event_type") or event.get("event")
                         or event.get("type") or "")
        # Telemetry loss is an observation condition, never a Job lifecycle
        # transition. Keep the last trustworthy stage/progress and let the
        # /history + /queue reconciler remain authoritative.
        if event_name in ("telemetry_degraded", "syncing", "queue_observed"):
            trace = job.setdefault("observation_trace", [])
            trace.append({
                "timestamp": self.store.timestamp(),
                "prompt_id": job.get("prompt_id") or event_prompt,
                "event": event_name,
                "event_type": event_name,
                "node_id": None,
                "display_node_id": None,
                "value": None,
                "max": None,
                "semantic_stage": previous_stage,
            })
            job["observation_trace"] = trace[-100:]
            job["elapsed"] = round(max(0.0, self.clock() - float(job.get("started_at") or self.clock())), 3)
            job["progress_message"] = event.get("message") or "生成中 · 正在同步任务状态"
            self._save_job(project_id, job)
            return
        job["current_stage"] = event.get("stage") or previous_stage
        # Keep a bounded, privacy-safe observer trace. It contains only
        # event/node/step metadata; prompt text and image content never enter
        # the persisted control-plane trace.
        trace = job.setdefault("observation_trace", [])
        step = event.get("step", event.get("value"))
        total_steps = event.get("total_steps", event.get("max"))
        trace.append({
            "timestamp": self.store.timestamp(),
            "prompt_id": job.get("prompt_id") or event_prompt,
            "event": event_name,
            "event_type": event_name,
            "node_id": event.get("node_id"),
            "display_node_id": event.get("display_node_id"),
            "value": step,
            "max": total_steps,
            "semantic_stage": event.get("stage") or previous_stage,
        })
        job["observation_trace"] = trace[-100:]
        job["elapsed"] = round(max(0.0, self.clock() - float(job.get("started_at") or self.clock())), 3)
        state = {"准备参考图": "PREPARING", "加载 H3 模型": "LOADING_MODEL",
                 "视频采样": "SAMPLING", "同步 ComfyUI 任务": "SAMPLING",
                 "视频解码": "DECODING",
                 "保存视频": "EXPORTING", "生成失败": "FAILED"}.get(
                     job["current_stage"], "LOADING_MODEL")
        current_state = str(job.get("state") or "PREPARING")
        current_rank = _JOB_STAGE_RANK.get(current_state, -1)
        incoming_rank = _JOB_STAGE_RANK.get(state, -1)
        if state not in ("FAILED",) and incoming_rank >= current_rank:
            job["state"] = state
            if state not in job["stages"]:
                job["stages"].append(state)
        elif state not in ("FAILED",) and current_state in _JOB_STAGE_RANK:
            # Polling may report an older stage after websocket sampling events.
            state = current_state
            job["current_stage"] = previous_stage
        if step is not None:
            job["step"] = step
        if total_steps is not None:
            job["total_steps"] = total_steps
        if event_name == "execution_error":
            job["progress_message"] = "正在等待 ComfyUI 确认执行结果"
            self._save_job(project_id, job)
            return
        job["lifecycle_state"] = lifecycle_state(job["current_stage"])
        job["progress_message"] = event.get("message") or job["current_stage"]
        calculated = weighted_progress(
            job["lifecycle_state"], job.get("step"), job.get("total_steps"),
            event.get("progress"))
        if calculated is not None:
            job["progress"] = calculated
            candidate_eta = estimate_eta(float(job.get("elapsed") or 0), calculated)
            if candidate_eta is not None:
                previous_eta = job.get("eta_seconds")
                try:
                    previous_eta = float(previous_eta)
                except (TypeError, ValueError):
                    previous_eta = None
                if previous_eta is None or previous_eta <= 0:
                    job["eta_seconds"] = round(candidate_eta, 1)
                else:
                    # Bound event-to-event volatility; the historical range
                    # remains the stable fallback shown before this signal.
                    bounded = min(max(candidate_eta, previous_eta * 0.5),
                                  previous_eta * 1.5 + 1.0)
                    job["eta_seconds"] = round(
                        previous_eta * 0.65 + bounded * 0.35, 1)
        self._save_job(project_id, job)

    def _update_delivery_probe(self, project_id: str, job: Dict[str, Any],
                               video_path: str) -> None:
        """Record only measured delivery properties; never infer post-processing."""
        path = Path(video_path) if video_path else None
        if path is None or not path.is_file():
            return
        trace = dict(job.get("execution_trace") or {})
        delivery = dict(trace.get("delivery") or {})
        try:
            from runtime.media_probe import probe_media_file
            probe_paths = (None if job.get("runtime_target") == "experimental"
                           else self.runtime_paths)
            probe_options = {"runtime_paths": probe_paths}
            if job.get("runtime_target") == "experimental":
                adapter = self._adapter_for_job(job)
                client = getattr(adapter, "client", None)
                runtime_python = getattr(client, "video_probe_python", None)
                if runtime_python:
                    probe_options["python_executable"] = runtime_python
            probe = probe_media_file(path, **probe_options)
        except Exception:
            delivery["status"] = "PROBE_UNAVAILABLE"
        else:
            if probe and probe.get("available"):
                delivery.update({
                    "width": int(probe["width"]),
                    "height": int(probe["height"]),
                    "fps": float(probe["fps"]),
                    "duration_seconds": float(probe["duration_seconds"]),
                    "video_codec": probe.get("video_codec"),
                    "audio_stream": bool(probe.get("audio_stream")),
                    "frame_count": probe.get("frame_count"),
                    "container_format": probe.get("container_format"),
                    "status": "PROBED",
                    "probe_tool": probe.get("probe_tool"),
                    "postprocess_applied": False,
                    "upscale_method": None,
                    "interpolation_method": None,
                })
            else:
                delivery["status"] = "PROBE_UNAVAILABLE"
        trace["delivery"] = delivery
        job["execution_trace"] = trace
        self._save_job(project_id, job)

    def _stage_refs_to_comfy_input(self, project_id: str, request: Any,
                                   runtime_target: str = "production",
                                   runtime_adapter=None) -> Dict[str, str]:
        """Stage only the request's approved references into active ComfyUI input.

        Studio keeps the original upload in its project store for preview and
        audit.  ComfyUI, however, accepts an input filename relative to its
        own input root.  Use a deterministic ASCII filename and verify both
        the local destination and the live ComfyUI view endpoint before the
        request reaches ``/prompt``.  This avoids Unicode/path mismatches and
        prevents a misleading GPU/Comfy execution failure.
        """
        target_input_dir = (self.experimental_comfy_input_dir
                            if runtime_target == "experimental"
                            else self.comfy_input_dir)
        if not target_input_dir:
            raise InputStagingError("ComfyUI input root is not configured")
        dest_dir = Path(target_input_dir)
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

            checker = getattr(getattr(runtime_adapter or self.runtime_adapter, "client", None),
                              "input_file_available", None)
            if checker is not None and not checker(staged_name):
                raise InputStagingError(
                    f"ComfyUI cannot see staged reference {staged_name} in {dest_dir}")

            request_ref["path_or_ref"] = staged_name
            staged[asset_id] = staged_name

        # A5 guides reuse the same Study reference store, but are staged only
        # after the selected runtime explicitly advertises native AddGuide.
        guide_frames = (request.guide_frames if hasattr(request, "guide_frames")
                        else request.get("guide_frames") or [])
        if not guide_frames:
            return staged
        refs_root = self.store.input_dir(project_id).resolve()
        for guide in guide_frames:
            asset_id = str(guide.get("asset_id") or "")
            ref = stored_refs.get(asset_id)
            if not ref or ref.get("state") != "APPROVED" \
                    or ref.get("role") != GUIDE_ROLE:
                raise InputStagingError("approved timeline guide is unavailable")
            src = Path(str(ref.get("stored_path") or "")).resolve()
            if not src.is_file() or not src.is_relative_to(refs_root):
                raise InputStagingError("timeline guide is outside the Study reference store")
            digest = hashlib.sha256()
            with src.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            expected = str(guide.get("content_sha256") or "").upper()
            if not expected or digest.hexdigest().upper() != expected:
                raise InputStagingError("timeline guide changed after approval")
            staged_name = str(guide.get("comfy_filename") or "")
            if not staged_name or Path(staged_name).name != staged_name:
                raise InputStagingError("timeline guide Comfy filename is unsafe")
            destination = dest_dir / staged_name
            shutil.copy2(src, destination)
            if not destination.is_file() or destination.stat().st_size <= 0:
                raise InputStagingError("timeline guide staging produced no readable image")
            checker = getattr(getattr(runtime_adapter or self.runtime_adapter, "client", None),
                              "input_file_available", None)
            if checker is not None and not checker(staged_name):
                raise InputStagingError(
                    f"ComfyUI cannot see staged timeline guide in {dest_dir}")
            guide["path_or_ref"] = staged_name
            staged[asset_id] = staged_name
        return staged

    # ------------------------------------------------------------------ #
    def _apply_elapsed(self, project_id: str, job: Dict[str, Any],
                       elapsed: float) -> Dict[str, Any]:
        if is_job_terminal(job):
            return job
        target = JobStateMachine.state_for_elapsed(elapsed)
        if target != job["state"]:
            job["state"] = target
            job["elapsed"] = round(elapsed, 3)
            if target not in job["stages"]:
                job["stages"].append(target)
            self._save_job(project_id, job)
            self._sync_project(project_id, job)
        build_study_state(self.store, project_id)
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
        # Rebuild the durable Study projection immediately.  Previously the
        # project record was restored but study_state.json kept the old
        # GENERATING/PREPARING fields, so the next generation was blocked or
        # appeared to be running forever after a memory failure.
        for attempt in range(3):
            try:
                build_study_state(self.store, project_id)
                break
            except PermissionError:
                if attempt == 2:
                    raise
                time.sleep(0.02 * (attempt + 1))

    def _ensure_terminal_fields(self, project_id: str,
                                job: Dict[str, Any]) -> None:
        if not is_job_terminal(job):
            return
        before = (job.get("finished_at"), job.get("elapsed"),
                  job.get("user_message"), job.get("progress"),
                  job.get("lifecycle_state"), job.get("submission_state"),
                  job.get("terminal_normalized_at"), job.get("active"),
                  job.get("is_active"))
        normalize_terminal_record(job, self.store.timestamp())
        self._normalize_terminal_job(job, job.get("state"))
        job["elapsed"] = round(terminal_elapsed_seconds(job), 3)
        after = (job.get("finished_at"), job.get("elapsed"),
                 job.get("user_message"), job.get("progress"),
                 job.get("lifecycle_state"), job.get("submission_state"),
                 job.get("terminal_normalized_at"), job.get("active"),
                 job.get("is_active"))
        if before != after:
            self._save_job(project_id, job)

    def _normalize_terminal_job(self, job: Dict[str, Any],
                                state: str, message: Optional[str] = None) -> None:
        """Apply the terminal-field contract in one place."""
        terminal = str(state or job.get("state") or "FAILED")
        timestamp = job.get("finished_at") or self.store.timestamp()
        job["finished_at"] = timestamp
        job["state"] = terminal
        if terminal == "COMPLETED":
            job["lifecycle_state"] = "SUCCEEDED"
            job["submission_state"] = job.get("submission_state") or "ACKNOWLEDGED"
            job["progress"] = 100.0
            job["eta_seconds"] = 0.0
            job["current_stage"] = "保存视频"
            job["user_message"] = (
                message if message and "复制到指定目录失败" in str(message)
                else ("视频已生成，但复制到指定目录失败"
                      if job.get("delivery_state") == "OUTPUT_DELIVERY_FAILED"
                      else "已完成")
            )
        elif terminal == "CANCELLED":
            job["lifecycle_state"] = "CANCELLED"
            job["submission_state"] = "CANCELLED"
            job["user_message"] = message or "已取消"
        elif terminal == "SUBMISSION_LOST":
            job["lifecycle_state"] = "SUBMISSION_LOST"
            job["submission_state"] = "SUBMISSION_LOST"
            job["user_message"] = message or "任务提交未被 ComfyUI 确认，可重新生成"
        else:
            job["lifecycle_state"] = "FAILED"
            job["user_message"] = message or job.get("user_message") or "任务执行失败"
        job["terminal_normalized_at"] = timestamp
        job["active"] = False
        job["is_active"] = False

    @staticmethod
    def _is_confirmed_reconciled_reactivation(existing: Dict[str, Any],
                                              incoming: Dict[str, Any]) -> bool:
        """Allow only exact, strong-identity queue evidence to clear a false failure."""
        active_states = {
            "RECONCILING", "LOADING_MODEL", "SAMPLING", "DECODING", "EXPORTING",
        }
        return bool(
            existing.get("state") in ("FAILED", "GPU_FAILED")
            and existing.get("runtime") == "native"
            and incoming.get("runtime") == "native"
            and existing.get("submission_state") in (
                "SUBMISSION_UNKNOWN", "RECONCILING",
            )
            and incoming.get("submission_state") == "ACKNOWLEDGED"
            and incoming.get("state") in active_states
            and existing.get("prompt_id")
            and existing.get("prompt_id") == incoming.get("prompt_id")
            and existing.get("execution_workflow_sha256")
            and existing.get("execution_workflow_sha256")
            == incoming.get("execution_workflow_sha256")
            and existing.get("runtime_target") == incoming.get("runtime_target")
            and existing.get("runtime_id") == incoming.get("runtime_id")
        )

    def _save_job(self, project_id: str, job: Dict[str, Any], *,
                  preserve_result_pipeline: bool = False,
                  allow_reconciled_reactivation: bool = False) -> None:
        # Serialize the complete load/check/replace transaction. Atomic file
        # replacement prevents torn JSON, while this lock prevents a worker
        # that loaded an older snapshot from losing a concurrent cancellation.
        with StudioStore._write_lock:
            jobs = self.store.load_jobs(project_id)
            existing = jobs.get(job["id"])
            if (existing and existing.get("state") == "CANCELLED"
                    and job.get("state") != "CANCELLED"):
                # Cancellation is an explicit owner decision. A worker that
                # was already inside an adapter call may still return later;
                # it must never overwrite that decision.
                return
            if (existing and is_job_terminal(existing)
                    and not is_job_terminal(job)):
                # A late worker callback must not resurrect a terminal Job.
                # Exception: strong queue/history evidence for the same
                # acknowledged execution may reverse an observer-only false
                # failure; cancellation and completed Jobs remain immutable.
                if not (allow_reconciled_reactivation
                        and self._is_confirmed_reconciled_reactivation(existing, job)):
                    return
            if preserve_result_pipeline:
                existing_pipeline = dict((existing or {}).get("result_pipeline") or {})
                incoming_pipeline = dict(job.get("result_pipeline") or {})
                pipeline = dict(existing_pipeline or incoming_pipeline)
                for key in ("expected_output_identity", "observed_output_identity",
                            "runtime_output_fingerprint"):
                    if key in incoming_pipeline:
                        pipeline[key] = incoming_pipeline[key]

                events = []
                seen = set()

                def merge_events(records) -> None:
                    for record in records or []:
                        if not isinstance(record, dict):
                            continue
                        key = (str(record.get("timestamp") or ""),
                               str(record.get("stage") or ""),
                               str(record.get("status") or ""),
                               str(record.get("error_code") or ""))
                        if key not in seen:
                            events.append(record)
                            seen.add(key)

                merge_events(existing_pipeline.get("events"))
                merge_events(incoming_pipeline.get("events"))
                try:
                    journal = self.store.load_job_result_events(project_id, job["id"])
                except Exception:
                    journal = []
                merge_events(journal)
                pipeline["events"] = events[-40:]
                if journal:
                    latest = journal[-1]
                    pipeline["current_stage"] = str(latest.get("stage") or
                                                    pipeline.get("current_stage") or "")
                    pipeline["status"] = str(latest.get("status") or
                                             pipeline.get("status") or "")
                    latest_packaging = next((event for event in reversed(journal)
                                             if event.get("stage") == "PACKAGING"), None)
                    if latest_packaging:
                        status = str(latest_packaging.get("status") or "")
                        pipeline["packaging_status"] = (
                            "RUNNING" if status == "STARTED" else status)
                job["result_pipeline"] = pipeline
            jobs[job["id"]] = job
            self.store.save_jobs(project_id, jobs)


def _real_output_exists(store: Any, project_id: str,
                        job: Dict[str, Any]) -> bool:
    """Return whether a persisted native completion has a real MP4 artifact."""
    candidates = [str(job.get(key) or "").strip()
                  for key in ("final_output_path", "output_path", "runtime_output_path")]
    candidates.append(str(store.package_dir(project_id) / "output" / "video.mp4"))
    for candidate in candidates:
        if not candidate:
            continue
        try:
            path = Path(candidate)
            if path.is_file() and path.stat().st_size > 0:
                return True
        except OSError:
            continue
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
    if isinstance(exc, ComfyUICommunicationTimeout):
        return "COMFY_COMMUNICATION_TIMEOUT", "生成中 · 正在同步任务状态"
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
    # Unknown adapter/service failures are not proof of CUDA/model execution.
    # Keep GPU_ERROR reserved for direct CUDA/OOM evidence.
    return "COMFYUI_ERROR", "生成引擎执行失败，请查看任务详情。"


def _decorate_job(job: Dict[str, Any]) -> Dict[str, Any]:
    """Add stable UI fields without changing the persisted lifecycle enum."""
    out = dict(job)
    category = out.get("error_category") or out.get("failure_code", "")
    if not category and "FileNotFoundError" in str(out.get("failure_reason", "")):
        category = "ENVIRONMENT_ERROR"
    out["error_category"] = category
    out["is_terminal"] = is_job_terminal(out)
    out["is_recoverable"] = is_job_recoverable(out)
    out["is_active"] = is_job_active(out)
    out["active"] = out["is_active"]
    if out["is_terminal"]:
        out["elapsed"] = round(terminal_elapsed_seconds(out), 3)
    out["lifecycle_state"] = out.get("lifecycle_state") or {
        "PREPARING": "CREATED", "LOADING_MODEL": "QUEUED",
        "ENCODING": "ENCODING", "SAMPLING": "RUNNING",
        "DECODING": "DECODING", "EXPORTING": "FINALIZING",
        "COMPLETED": "SUCCEEDED", "FAILED": "FAILED",
        "GPU_FAILED": "FAILED", "CANCELLED": "FAILED",
        "SUBMISSION_LOST": "SUBMISSION_LOST",
        "RECONCILING": "SUBMISSION_UNKNOWN",
    }.get(out.get("state"), "RUNNING")
    out["status_label"] = {
        "COMPLETED": "完成", "PREPARING": "准备中", "LOADING_MODEL": "加载模型",
        "SAMPLING": "生成中", "ENCODING": "编码中", "DECODING": "视频解码",
        "EXPORTING": "导出中",
        "FAILED": "生成失败", "GPU_FAILED": "生成失败", "CANCELLED": "已取消",
        "SUBMISSION_LOST": "提交未确认",
        "RECONCILING": "同步任务状态",
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
        "COMFY_COMMUNICATION_TIMEOUT": "生成中 · 正在同步任务状态",
        "OUTPUT_ERROR": "输出失败", "WORKFLOW_PARAMETER_ERROR": "参数配置错误",
        }.get(category, "生成失败")
    else:
        out["friendly_reason"] = ""
    return out


def _recovery_job_payload(job: Dict[str, Any]) -> Dict[str, Any]:
    """Return a path-free, minimal owner/API result for recovery requests."""
    decorated = _decorate_job(job)
    keys = (
        "id", "state", "lifecycle_state", "submission_state", "runtime",
        "runtime_target", "workflow", "prompt_id", "execution_workflow_sha256",
        "result_pipeline", "delivery_state", "package_built", "current_stage",
        "progress", "failure_code", "error_category", "user_message",
        "is_terminal", "is_recoverable", "is_active", "status_label",
        "friendly_reason",
    )
    payload = {key: decorated[key] for key in keys if key in decorated}
    payload["media_url"] = (
        f"/api/jobs/{job.get('id')}/media"
        if job.get("state") == "COMPLETED" else None
    )
    return payload
