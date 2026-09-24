"""Controlled, acceptance-only STANDARD vs NATIVE_HIGH GPU evidence runner.

This module is deliberately not imported by the product API. It requires an
explicit CLI confirmation, keeps STANDARD fail-closed in normal submissions,
and persists ambiguity markers so a lost observation is reconciled rather
than submitted twice.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from apps.architect_video_studio.mock_api.job_api import JobAPI
from apps.architect_video_studio.mock_api.job_state import is_job_active
from apps.architect_video_studio.mock_api.output_api import OutputAPI
from apps.architect_video_studio.mock_api.store import StudioStore
from apps.architect_video_studio.mock_api.study_state import build_study_state
from apps.architect_video_studio.state_machine.machine import ProjectStateMachine
from runtime.a4_profiles import (
    QUALITY_PROFILE_SPECS, actual_execution_parameters,
    resolve_product_parameters,
)
from runtime.adapters.comfyui_client import ComfyUIClient
from runtime.adapters.native_runtime_adapter import NativeRuntimeAdapter
from runtime.adapters.production_workflow_binding import canonical_workflow_sha256
from runtime.adapters.runtime_paths import RuntimePathContract
from runtime.generation_capabilities import estimate_generation_range
from runtime.media_probe import probe_media_file
from runtime.reference_contract import reference_bindings, resolve_selected_references
from runtime.workflow_motion import normalize_camera_motion


WORKFLOW_ID = "04_Drone_Aerial"
CAMPAIGN = "A4.2_NATIVE_QUALITY"
ARMS = ("STANDARD", "NATIVE_HIGH")
EXPECTED_CANVASES = {"STANDARD": (1248, 704), "NATIVE_HIGH": (1344, 768)}
_SHOWINFO_FRAME_RE = re.compile(r"\bn:\s*(\d+)\s+pts:")


class A4_2AcceptanceError(RuntimeError):
    """A4.2 safety or evidence gate failed."""


class A4_2AcceptanceRuntimeAdapter(NativeRuntimeAdapter):
    """Narrow runner-only adapter: keep correlation out of the compared graph."""

    def attach_job_identity(self, native_request: dict[str, Any],
                            avs_job_id: str) -> dict[str, Any]:
        payload = native_request["translated_payload"]
        save_nodes = [node for node in payload.values()
                      if isinstance(node, dict)
                      and node.get("class_type") == "SaveVideo"]
        if len(save_nodes) != 1:
            raise A4_2AcceptanceError(
                "A4.2 requires exactly one SaveVideo output node for per-job isolation")
        inputs = save_nodes[0].setdefault("inputs", {})
        prefix = str(inputs.get("filename_prefix") or "video/output")
        if str(avs_job_id) not in prefix:
            inputs["filename_prefix"] = f"{prefix}_{avs_job_id}"
        native_request["avs_job_id"] = str(avs_job_id)
        native_request["execution_workflow_sha256"] = canonical_workflow_sha256(payload)
        return native_request


def compare_execution_payloads(standard: Mapping[str, Any],
                               native_high: Mapping[str, Any], *,
                               operational_output_prefixes: tuple[str, str] | None = None
                               ) -> dict[str, Any]:
    """Pass only when the final Comfy graphs differ exclusively in H3 canvas."""
    left, right = copy.deepcopy(dict(standard)), copy.deepcopy(dict(native_high))

    def canvas_node(graph: dict[str, Any]) -> dict[str, Any]:
        nodes = [node for node in graph.values()
                 if isinstance(node, dict)
                 and node.get("class_type") == "MiniMaxH3ImageToVideo"]
        if len(nodes) != 1:
            raise A4_2AcceptanceError("fair gate requires exactly one H3 video node")
        return nodes[0].setdefault("inputs", {})

    left_inputs, right_inputs = canvas_node(left), canvas_node(right)
    left_canvas = (left_inputs.get("width"), left_inputs.get("height"))
    right_canvas = (right_inputs.get("width"), right_inputs.get("height"))
    if left_canvas != EXPECTED_CANVASES["STANDARD"]:
        raise A4_2AcceptanceError("STANDARD graph did not bind the approved 1248x704 canvas")
    if right_canvas != EXPECTED_CANVASES["NATIVE_HIGH"]:
        raise A4_2AcceptanceError("NATIVE_HIGH graph did not bind the approved 1344x768 canvas")
    for inputs in (left_inputs, right_inputs):
        inputs.pop("width", None)
        inputs.pop("height", None)
    output_prefix_gate = None
    if operational_output_prefixes is not None:
        def save_video_inputs(graph: dict[str, Any]) -> dict[str, Any]:
            nodes = [node for node in graph.values()
                     if isinstance(node, dict) and node.get("class_type") == "SaveVideo"]
            if len(nodes) != 1:
                raise A4_2AcceptanceError(
                    "output-isolation gate requires exactly one SaveVideo node")
            return nodes[0].setdefault("inputs", {})

        left_output, right_output = save_video_inputs(left), save_video_inputs(right)
        actual_prefixes = (str(left_output.get("filename_prefix") or ""),
                           str(right_output.get("filename_prefix") or ""))
        if (actual_prefixes != operational_output_prefixes
                or not all(actual_prefixes) or actual_prefixes[0] == actual_prefixes[1]):
            raise A4_2AcceptanceError(
                "per-job output prefixes are missing, duplicated, or unexpected")
        # Output names isolate artifacts and do not affect generation. Normalize
        # only this explicitly verified field; every other graph field remains
        # part of the strict equality gate.
        left_output["filename_prefix"] = right_output["filename_prefix"] = (
            "__A4_2_PER_JOB_OUTPUT_ISOLATION__")
        output_prefix_gate = "PASS_NON_GENERATION_METADATA_ONLY"
    if left != right:
        raise A4_2AcceptanceError(
            "fair gate failed: final execution graphs differ beyond H3 width/height")
    result = {
        "pass": True,
        "only_variable": "MiniMaxH3ImageToVideo.width,height",
        "standard_workflow_sha256": canonical_workflow_sha256(standard),
        "native_high_workflow_sha256": canonical_workflow_sha256(native_high),
    }
    if output_prefix_gate:
        result["per_job_output_isolation"] = output_prefix_gate
        result["operational_metadata_exclusion"] = "SaveVideo.inputs.filename_prefix"
    return result


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha256_json(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _managed_ffmpeg(runtime_paths: RuntimePathContract) -> str | None:
    if runtime_paths.ffmpeg and runtime_paths.ffmpeg.is_file():
        return str(runtime_paths.ffmpeg)
    if runtime_paths.embedded_python.is_file():
        try:
            result = subprocess.run(
                [str(runtime_paths.embedded_python), "-c",
                 "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"],
                capture_output=True, text=True, timeout=15, check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            candidate = (result.stdout or "").strip().splitlines()[-1]
            if result.returncode == 0 and Path(candidate).is_file():
                return candidate
        except (OSError, subprocess.SubprocessError, IndexError):
            pass
    return None


def _queue_counts(client: ComfyUIClient) -> tuple[int, int]:
    queue = client.get_queue()
    if not isinstance(queue, dict):
        raise A4_2AcceptanceError("ComfyUI queue response is not readable")
    running = queue.get("queue_running")
    pending = queue.get("queue_pending")
    if not isinstance(running, list) or not isinstance(pending, list):
        raise A4_2AcceptanceError("ComfyUI queue response is missing active/pending lists")
    return len(running), len(pending)


def _gpu_snapshot(client: ComfyUIClient) -> dict[str, Any] | None:
    try:
        data = client._request("GET", "/system_stats", operation="health")
    except Exception:  # resource sampling is evidence-only, never job authority
        return None
    devices = data.get("devices") if isinstance(data, dict) else None
    if not isinstance(devices, list):
        return None
    candidates = []
    for device in devices:
        if not isinstance(device, dict):
            continue
        try:
            total = int(device.get("vram_total"))
            free = int(device.get("vram_free"))
        except (TypeError, ValueError):
            continue
        candidates.append({
            "name": str(device.get("name") or "GPU"),
            "total_bytes": total,
            "free_bytes": free,
            "used_bytes": max(0, total - free),
        })
    return max(candidates, key=lambda item: item["total_bytes"]) if candidates else None


class _ResourceSampler:
    def __init__(self, client: ComfyUIClient, interval: float = 2.0) -> None:
        self.client = client
        self.interval = interval
        self.stop_event = threading.Event()
        self.samples: list[dict[str, Any]] = []
        self.thread = threading.Thread(target=self._sample, daemon=True)

    def _sample(self) -> None:
        while not self.stop_event.is_set():
            current = _gpu_snapshot(self.client)
            if current:
                self.samples.append(current)
            self.stop_event.wait(self.interval)

    def __enter__(self) -> "_ResourceSampler":
        self.thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop_event.set()
        self.thread.join(timeout=self.interval + 1)
        current = _gpu_snapshot(self.client)
        if current:
            self.samples.append(current)

    def evidence(self) -> dict[str, Any]:
        if not self.samples:
            return {"available": False, "scope": "ComfyUI system-wide sample"}
        peak = max(self.samples, key=lambda item: item["used_bytes"])
        first = self.samples[0]
        return {
            "available": True,
            "scope": "ComfyUI system-wide VRAM sample; not process-isolated",
            "device": peak["name"],
            "total_bytes": peak["total_bytes"],
            "baseline_used_bytes": first["used_bytes"],
            "peak_used_bytes": peak["used_bytes"],
            "peak_free_bytes": peak["free_bytes"],
            "sample_count": len(self.samples),
            "sample_interval_seconds": self.interval,
        }


def _video_frame_count(path: Path, runtime_paths: RuntimePathContract) -> int | None:
    executable = runtime_paths.ffprobe
    if executable and executable.is_file():
        try:
            result = subprocess.run(
                [str(executable), "-v", "error", "-select_streams", "v:0",
                 "-count_frames", "-show_entries", "stream=nb_read_frames",
                 "-of", "json", str(path)],
                capture_output=True, text=True, timeout=30, check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if result.returncode == 0:
                streams = json.loads(result.stdout).get("streams") or []
                count = (streams[0] or {}).get("nb_read_frames") if streams else None
                if count not in (None, "N/A"):
                    return int(count)
        except (OSError, subprocess.SubprocessError, ValueError, TypeError,
                IndexError, json.JSONDecodeError):
            pass

    # Some packaged Windows runtimes ship FFmpeg but not ffprobe. Decode the
    # video stream to the null muxer and count showinfo's sequential frame
    # indices; passthrough sync prevents output-rate duplication/drop.
    ffmpeg = _managed_ffmpeg(runtime_paths)
    if not ffmpeg:
        return None
    try:
        result = subprocess.run(
            [ffmpeg, "-hide_banner", "-nostdin", "-v", "info", "-i", str(path),
             "-map", "0:v:0", "-vf", "showinfo", "-vsync", "0",
             "-an", "-sn", "-dn", "-f", "null", "-"],
            capture_output=True, text=True, timeout=120, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode != 0:
            return None
        indices = [int(match.group(1))
                   for match in _SHOWINFO_FRAME_RE.finditer(result.stderr or "")]
        if not indices or indices != list(range(len(indices))):
            return None
        return len(indices)
    except (OSError, subprocess.SubprocessError, ValueError, TypeError):
        return None


def _needs_acceptance_probe(job: Mapping[str, Any] | None) -> bool:
    evidence = (job or {}).get("acceptance_evidence") or {}
    return bool((job or {}).get("state") == "COMPLETED"
                and evidence.get("pass") is not True)


def _reopen_misbound_acceptance_job(job: dict[str, Any], store: StudioStore,
                                    project_id: str, client: Any) -> bool:
    """Rebind a false-terminal A4 Job only to its exact correlated history graph.

    This repairs an observation race without submitting another prompt. It is
    intentionally limited to a failed A4.2 acceptance Job whose completed
    history entry has the persisted Job id, workflow SHA, expected canvas, and
    per-job output identity.
    """
    evidence = job.get("acceptance_evidence") or {}
    if (job.get("acceptance_campaign") != CAMPAIGN
            or job.get("state") != "COMPLETED"
            or evidence.get("pass") is True):
        return False
    job_id = str(job.get("id") or "")
    workflow_sha = str(job.get("execution_workflow_sha256") or "")
    old_prompt_id = str(job.get("prompt_id") or "")
    if not job_id or not workflow_sha or not old_prompt_id:
        return False
    recovered = client.reconcile_prompt(
        prompt_id=None, avs_job_id=job_id,
        execution_workflow_sha256=workflow_sha, legacy_seed=None)
    prompt_id = str(recovered.get("prompt_id") or "")
    if (recovered.get("status") != "COMPLETED"
            or recovered.get("source") != "history"
            or not prompt_id or prompt_id == old_prompt_id):
        return False
    entry = recovered.get("entry") or {}
    serialized = json.dumps(entry, sort_keys=True, ensure_ascii=False, default=str)
    if job_id not in serialized or workflow_sha not in serialized:
        return False
    prompt = entry.get("prompt")
    graph = prompt[2] if isinstance(prompt, (list, tuple)) and len(prompt) > 2 else None
    if not isinstance(graph, Mapping):
        return False
    try:
        if canonical_workflow_sha256(graph) != workflow_sha:
            return False
    except (TypeError, ValueError):
        return False
    h3_nodes = [node for node in graph.values()
                if isinstance(node, Mapping)
                and node.get("class_type") == "MiniMaxH3ImageToVideo"]
    save_nodes = [node for node in graph.values()
                  if isinstance(node, Mapping) and node.get("class_type") == "SaveVideo"]
    expected_canvas = EXPECTED_CANVASES.get(str(job.get("acceptance_arm")))
    if (len(h3_nodes) != 1 or len(save_nodes) != 1 or expected_canvas is None
            or (h3_nodes[0].get("inputs", {}).get("width"),
                h3_nodes[0].get("inputs", {}).get("height")) != expected_canvas
            or job_id not in str(save_nodes[0].get("inputs", {}).get("filename_prefix") or "")):
        return False

    jobs = store.load_jobs(project_id)
    latest = jobs.get(job_id)
    if (not latest or latest.get("state") != "COMPLETED"
            or latest.get("prompt_id") != old_prompt_id
            or (latest.get("acceptance_evidence") or {}).get("pass") is True):
        return False
    latest["prompt_id"] = prompt_id
    latest["state"] = "RECONCILING"
    latest["lifecycle_state"] = "SUBMISSION_UNKNOWN"
    latest["submission_state"] = "RECONCILING"
    latest["current_stage"] = "同步 ComfyUI 任务"
    latest["progress_message"] = "正在同步同一 ComfyUI Job 的终态与输出"
    latest["progress"] = None
    latest["eta_seconds"] = None
    latest["final_output_path"] = ""
    latest["output_path"] = ""
    latest["source_output_path"] = ""
    latest["runtime_output_path"] = ""
    latest["package_built"] = False
    latest["delivery_state"] = "NOT_PRODUCED"
    latest["delivery_error"] = ""
    latest["last_observation"] = {
        "timestamp": _timestamp(), "source": "history",
        "status": "COMPLETED", "prompt_id": prompt_id,
        "candidates": 1, "observation_error": "",
    }
    jobs[job_id] = latest
    store.save_jobs(project_id, jobs)
    return True


def _range_evidence(job_id: str, api_base: str) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{api_base.rstrip('/')}/api/jobs/{job_id}/media",
        headers={"Range": "bytes=0-1"}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            body = response.read(3)
            return {
                "status": int(response.status),
                "content_range_present": bool(response.headers.get("Content-Range")),
                "bytes_observed": len(body),
                "pass": response.status == 206 and len(body) == 2
                and response.headers.get("Accept-Ranges") == "bytes",
            }
    except (urllib.error.URLError, TimeoutError, OSError):
        return {"status": None, "content_range_present": False,
                "bytes_observed": 0, "pass": False}


def _existing_acceptance_jobs(jobs: Mapping[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [job for job in jobs.values()
            if job.get("acceptance_campaign") == CAMPAIGN]


def _acceptance_arm_passed(job: Mapping[str, Any] | None) -> bool:
    evidence = (job or {}).get("acceptance_evidence") or {}
    return bool((job or {}).get("state") == "COMPLETED" and evidence.get("pass") is True)


def _standard_arm_passed(job: Mapping[str, Any] | None) -> bool:
    return _acceptance_arm_passed(job)


def _selected_arms(requested_arm: str) -> tuple[str, ...]:
    arm = str(requested_arm or "").strip().upper()
    if arm not in ARMS:
        raise A4_2AcceptanceError("A4.2 accepts exactly one explicit arm per invocation")
    return (arm,)


def _validate_acceptance_study_gate(study: Mapping[str, Any],
                                    prompt: Mapping[str, Any]) -> str:
    """Allow only the approved A4.2 candidate exception, without opening JobAPI."""
    verified = prompt.get("verified") or {}
    if verified.get("pass") is not True or study.get("prompt_current") is not True:
        raise A4_2AcceptanceError("the current approved Prompt is not verified/current")
    if study.get("reference_approved") is not True:
        raise A4_2AcceptanceError("the selected reference is not approved")

    profile = prompt.get("a4_profile") or {}
    is_candidate = (
        str(prompt.get("prompt_engine_provider") or "").upper() == "OFFLINE_COMPILER"
        and str(profile.get("quality_profile") or "").upper() == "STANDARD"
        and profile.get("availability") == "CANDIDATE_FOR_A4_2"
        and QUALITY_PROFILE_SPECS["STANDARD"].get("availability")
        == "CANDIDATE_FOR_A4_2"
    )
    if is_candidate:
        if study.get("generate_allowed") is not False:
            raise A4_2AcceptanceError(
                "STANDARD candidate must remain closed to ordinary production generation")
        if study.get("prompt_confirmed") is not False:
            raise A4_2AcceptanceError(
                "STANDARD candidate Study confirmation state drifted from its fail-closed contract")
        return "A4_2_STANDARD_CANDIDATE_WITH_PRODUCTION_GATE_CLOSED"

    if study.get("prompt_confirmed") is not True:
        raise A4_2AcceptanceError("Study confirmation is not satisfied")
    return "CONFIRMED_PROMPT"


def _validate_prepared_arm_graph(arm: str, request: Any,
                                 params: Mapping[str, Any],
                                 profile: Mapping[str, Any],
                                 prepared: Mapping[str, Any]) -> dict[str, Any]:
    """Fail before submission unless the actual bound graph matches the arm contract."""
    if arm not in ARMS or params.get("quality") != arm:
        raise A4_2AcceptanceError("acceptance arm/profile identity mismatch")
    if request.workflow_id != WORKFLOW_ID or prepared.get("workflow_id") != WORKFLOW_ID:
        raise A4_2AcceptanceError("acceptance graph is not bound to 04_Drone_Aerial")
    payload = prepared.get("translated_payload")
    if not isinstance(payload, Mapping):
        raise A4_2AcceptanceError("acceptance execution graph is missing")
    try:
        actual = actual_execution_parameters(payload, WORKFLOW_ID, profile)
    except (KeyError, TypeError, ValueError) as exc:
        raise A4_2AcceptanceError(
            "actual execution graph parameters could not be verified") from exc

    resolved = profile.get("final_execution_parameters")
    if not isinstance(resolved, Mapping):
        raise A4_2AcceptanceError("resolved arm execution parameters are missing")
    expected = {
        "quality_profile": arm,
        "architecture_profile": profile.get("architecture_profile"),
        "resolution": params.get("resolution"),
        "width": params.get("width"),
        "height": params.get("height"),
        "duration_seconds": params.get("resolved_duration_seconds"),
        "requested_duration_seconds": params.get("duration"),
        "fps": params.get("fps"),
        "frame_count": params.get("frame_count"),
        "seed": params.get("seed"),
        "steps": params.get("steps"),
        "sampler": params.get("sampler_mode"),
        "scheduler": resolved.get("scheduler"),
        "denoise": resolved.get("denoise"),
        "acceleration": resolved.get("acceleration"),
        "reference_count": len(request.reference_assets or []),
    }
    for key, expected_value in expected.items():
        actual_value = actual.get(key)
        if isinstance(expected_value, float):
            try:
                matches = math.isclose(float(actual_value), expected_value,
                                       rel_tol=0.0, abs_tol=1e-6)
            except (TypeError, ValueError):
                matches = False
        else:
            matches = actual_value == expected_value
        if not matches:
            raise A4_2AcceptanceError(
                f"{arm} execution graph mismatch in {key}")

    nodes_by_type: dict[str, list[Mapping[str, Any]]] = {}
    for node in payload.values():
        if isinstance(node, Mapping):
            nodes_by_type.setdefault(str(node.get("class_type") or ""), []).append(node)
    h3_nodes = nodes_by_type.get("MiniMaxH3ImageToVideo", [])
    prompt_text = str((request.prompt_payload or {}).get("prompt") or "")
    if len(h3_nodes) != 1 or (h3_nodes[0].get("inputs") or {}).get("prompt") != prompt_text:
        raise A4_2AcceptanceError("execution graph Prompt binding differs from the verified Prompt")
    refs = list(request.reference_assets or [])
    if (request.prompt_payload or {}).get("reference_bindings") != reference_bindings(refs):
        raise A4_2AcceptanceError("execution request reference provenance differs from the approved Prompt")
    image_nodes = nodes_by_type.get("LoadImage", [])
    expected_names = [Path(str(ref.get("path_or_ref") or "")).name for ref in refs]
    actual_names = [str((node.get("inputs") or {}).get("image") or "")
                    for node in image_nodes]
    if len(image_nodes) != len(refs) or actual_names != expected_names:
        raise A4_2AcceptanceError("execution graph image binding differs from the approved reference")

    prompt_profile = (request.prompt_payload or {}).get("a4_profile") or {}
    provenance_fields = (
        "contract_version", "architecture_profile", "architecture_profile_version",
        "quality_profile_version", "prompt_profile_version",
    )
    if any(prompt_profile.get(key) != profile.get(key) for key in provenance_fields):
        raise A4_2AcceptanceError("architecture Prompt provenance differs from the resolved arm profile")
    return actual


def _resolved_execution_parameters(params: Mapping[str, Any],
                                    profile: Mapping[str, Any]) -> dict[str, Any]:
    resolved = profile.get("final_execution_parameters")
    if not isinstance(resolved, Mapping):
        raise A4_2AcceptanceError("resolved arm execution parameters are missing")
    return {**dict(resolved), **dict(params)}


def _new_job(store: StudioStore, project_id: str, job_api: JobAPI,
             request: Any, params: dict[str, Any], profile: dict[str, Any],
             pair_id: str, input_fingerprint: str,
             fair_gate: dict[str, Any], source_job_id: str) -> dict[str, Any]:
    project = store.load_project(project_id)
    if project.get("state") == "COMPLETED":
        machine = ProjectStateMachine("COMPLETED")
        machine.transition("start_new_generation", actor="architect",
                           reason="start controlled A4.2 quality acceptance")
        project["state"] = machine.state
    if project.get("state") != "USER_CONFIRM":
        raise A4_2AcceptanceError("Study is not at a safe confirmation state for a new arm")
    job_id = store.new_id("job")
    now = time.time()
    ref_bindings = list(request.prompt_payload.get("reference_bindings") or [])
    resolved_params = _resolved_execution_parameters(params, profile)
    trace = {
        "contract_version": profile["contract_version"],
        "quality_profile_version": profile["quality_profile_version"],
        "prompt_profile_version": profile["prompt_profile_version"],
        "architecture_profile_version": profile["architecture_profile_version"],
        "workflow_id": WORKFLOW_ID,
        "requested_quality_profile": params["quality"],
        "resolved_execution_profile": profile["resolved_execution_profile"],
        "execution_mode": profile["execution_mode"],
        "availability": profile["availability"],
        "native_generation": dict(profile["native_generation"]),
        "delivery": {**dict(profile["delivery"]), "status": "NOT_PRODUCED"},
        "native_generation_width": params["width"],
        "native_generation_height": params["height"],
        "native_generation_fps": params["fps"],
        "delivery_width": params["width"],
        "delivery_height": params["height"],
        "delivery_fps": params["delivery_fps"],
        "requested_duration": params["duration"],
        "resolved_frame_count": params["frame_count"],
        "effective_duration": params["resolved_duration_seconds"],
        "steps": params["steps"],
        "sampler": resolved_params["sampler_mode"],
        "scheduler": resolved_params["scheduler"],
        "denoise": resolved_params["denoise"],
        "seed": params["seed"],
        "acceleration": resolved_params["acceleration"],
        "reference_bindings": ref_bindings,
        "architecture_profile": profile["architecture_profile"],
        "architecture_profile_version": profile["architecture_profile_version"],
        "profile_parameter_overrides": dict(profile["profile_parameter_overrides"]),
        "final_execution_parameters": resolved_params,
        "workflow_sha256": None,
        "postprocess_applied": False,
        "status": "WAITING_FOR_RUNTIME_BINDER",
    }
    source_prompt = request.prompt_payload
    job = {
        "id": job_id,
        "project_id": project_id,
        "workflow": WORKFLOW_ID,
        "state": "PREPARING",
        "seed": int(params["seed"]),
        "camera_motion": request.camera_motion,
        "generation_parameters": dict(params),
        "runtime": "native",
        "created_at": store.timestamp(),
        "started_at": now,
        "elapsed": 0.0,
        "estimated_time": estimate_generation_range(
            store.load_jobs(project_id).values(), workflow_id=WORKFLOW_ID,
            duration=params["duration"], fps=params["fps"],
            resolution=params["resolution"], steps=params["steps"], cold_start=True),
        "stages": ["PREPARING"],
        "package_built": False,
        "output_path": "",
        "source_output_path": "",
        "runtime_output_path": "",
        "final_output_path": "",
        "failure_reason": "",
        "prompt_hash": source_prompt.get("prompt_hash"),
        "prompt_snapshot": {
            key: source_prompt.get(key) for key in
            ("workflow", "mode", "prompt", "alignment",
             "integrated_multimodal_description", "overall_soundscape",
             "non_diegetic_music", "prompt_hash", "a4_profile",
             "reference_bindings", "provenance")
        },
        "reference_bindings": ref_bindings,
        "reference_assets_snapshot": [
            {**binding, "filename": Path(str(ref.get("path_or_ref") or "")).name}
            for binding, ref in zip(ref_bindings, request.reference_assets)
        ],
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
        "acceptance_campaign": CAMPAIGN,
        "acceptance_pair_id": pair_id,
        "acceptance_arm": params["quality"],
        "acceptance_input_fingerprint": input_fingerprint,
        "acceptance_fair_gate": dict(fair_gate),
        "acceptance_source_job_id": source_job_id,
        "acceptance_submission_attempts": 0,
    }
    jobs = store.load_jobs(project_id)
    jobs[job_id] = job
    store.save_jobs(project_id, jobs)
    machine = ProjectStateMachine(project["state"])
    machine.transition("confirm_generate", actor="architect",
                       reason=f"start A4.2 {params['quality']} arm")
    project["state"] = machine.state
    store.save_project(project)
    store.append_audit(project_id, {
        "actor": "architect", "event": "a4_2_quality_arm_started",
        "from": "USER_CONFIRM", "to": "GPU_RUNNING",
        "detail": {"job_id": job_id, "arm": params["quality"],
                   "pair_id": pair_id, "fair_gate": "PASS"},
    })
    return job


def _mark_submission_boundary(store: StudioStore, project_id: str,
                              job_id: str) -> bool:
    jobs = store.load_jobs(project_id)
    job = jobs[job_id]
    if job.get("cancelled") or job.get("state") == "CANCELLED":
        return False
    job["submission_state"] = "SUBMISSION_UNKNOWN"
    job["lifecycle_state"] = "SUBMISSION_UNKNOWN"
    job["submission_started_at"] = _timestamp()
    job["acceptance_submission_attempts"] = int(
        job.get("acceptance_submission_attempts") or 0) + 1
    store.save_jobs(project_id, jobs)
    return True


def _probe_evidence(job: dict[str, Any], runtime_paths: RuntimePathContract,
                    api_base: str) -> dict[str, Any]:
    path = Path(str(job.get("final_output_path") or job.get("output_path") or ""))
    if not path.is_file() or path.stat().st_size <= 0:
        return {"available": False, "pass": False, "error_code": "MEDIA_MISSING"}
    probe = probe_media_file(path, runtime_paths=runtime_paths)
    frames = _video_frame_count(path, runtime_paths)
    expected = EXPECTED_CANVASES[str(job.get("acceptance_arm"))]
    range_result = _range_evidence(str(job["id"]), api_base)
    metadata_pass = bool(
        probe.get("available")
        and (probe.get("width"), probe.get("height")) == expected
        and abs(float(probe.get("fps") or 0) - 24.0) < 0.02
        and abs(float(probe.get("duration_seconds") or 0)
                - float(job["generation_parameters"]["resolved_duration_seconds"])) < 0.15
        and frames == int(job["generation_parameters"]["frame_count"]))
    return {
        "available": True,
        "pass": metadata_pass and range_result["pass"],
        "size_bytes": path.stat().st_size,
        "ffprobe": probe,
        "decoded_frame_count": frames,
        "media_range": range_result,
    }


def _wait_or_reconcile(job_api: JobAPI, store: StudioStore, project_id: str,
                       job_id: str, *, timeout_seconds: float = 1800.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    job = store.load_jobs(project_id)[job_id]
    if job.get("submission_state") == "NOT_STARTED":
        return job
    next_reconcile = time.monotonic() + 15
    job = job_api.reconcile_job(job_id, start_observer=True)
    while is_job_active(job) and time.monotonic() < deadline:
        time.sleep(5)
        job = store.load_jobs(project_id).get(job_id, job)
        if not is_job_active(job):
            break
        if time.monotonic() >= next_reconcile:
            job = job_api.reconcile_job(job_id, start_observer=True)
            next_reconcile = time.monotonic() + 15
    return store.load_jobs(project_id).get(job_id, job)


def run_a4_2_acceptance(*, data_root: Path, project_id: str,
                        runtime_paths: RuntimePathContract,
                        client: ComfyUIClient | None = None,
                        api_base: str = "http://127.0.0.1:8788",
                        observe_timeout_seconds: float = 1800.0,
                        arm: str = "STANDARD") -> dict[str, Any]:
    """Run/resume one explicitly selected A4.2 arm; unknown submissions are never retried."""
    arms_to_run = _selected_arms(arm)
    store = StudioStore(Path(data_root))
    project = store.load_project(project_id)
    jobs = store.load_jobs(project_id)
    previous_acceptance = _existing_acceptance_jobs(jobs)
    pair_ids = {str(job.get("acceptance_pair_id") or "")
                for job in previous_acceptance}
    if len(pair_ids) > 1 or "" in pair_ids:
        raise A4_2AcceptanceError("multiple or incomplete A4.2 experiment records found")
    pair_id = next(iter(pair_ids), f"a4-2-{uuid.uuid4().hex[:12]}")
    by_arm: dict[str, dict[str, Any]] = {}
    for job in previous_acceptance:
        arm = str(job.get("acceptance_arm") or "")
        if arm not in ARMS or arm in by_arm:
            raise A4_2AcceptanceError("duplicate or unknown A4.2 arm record found")
        by_arm[arm] = job

    store_study = build_study_state(store, project_id)
    intent = store.load_intent(project_id) or {}
    prompt = store.load_prompt(project_id) or {}
    if intent.get("selected_workflow") != WORKFLOW_ID or prompt.get("workflow") != WORKFLOW_ID:
        raise A4_2AcceptanceError("A4.2 requires the current Study and Prompt to select 04_Drone_Aerial")
    _validate_acceptance_study_gate(store_study, prompt)
    if not intent or intent.get("requires_user_confirmation"):
        raise A4_2AcceptanceError("current architecture intent is not confirmed")

    refs_by_id = store.load_references(project_id)
    approved_refs = resolve_selected_references(
        project_id, project, refs_by_id, WORKFLOW_ID,
        require_approved=True, reference_root=store.input_dir(project_id))
    if len(approved_refs) != 1 or approved_refs[0].get("role") != "first_frame":
        raise A4_2AcceptanceError("04_Drone_Aerial must bind exactly one approved first_frame")
    bindings = reference_bindings(approved_refs)
    if prompt.get("a4_profile") and prompt.get("reference_bindings") != bindings:
        raise A4_2AcceptanceError("approved reference identity differs from the current Prompt")

    active_acceptance = [job for job in previous_acceptance if is_job_active(job)]
    non_acceptance_active = [job for job in jobs.values()
                             if is_job_active(job) and job.get("acceptance_campaign") != CAMPAIGN]
    if non_acceptance_active:
        raise A4_2AcceptanceError("another active Study Job must finish before A4.2")
    if len(active_acceptance) > 1:
        raise A4_2AcceptanceError("more than one active A4.2 Job is recorded")

    seed_source = max(
        (job for job in jobs.values()
         if job.get("workflow") == WORKFLOW_ID and job.get("state") == "COMPLETED"),
        key=lambda item: str(item.get("created_at") or ""), default=None)
    camera_motion = str((seed_source or {}).get("camera_motion")
                        or normalize_camera_motion(WORKFLOW_ID))
    if camera_motion != "aerial_reveal":
        raise A4_2AcceptanceError("the saved 04_Drone_Aerial camera contract is not aerial_reveal")
    input_fingerprint = _sha256_json({
        "workflow": WORKFLOW_ID,
        "prompt_hash": prompt.get("prompt_hash"),
        "reference_bindings": bindings,
        "intent_hash": _sha256_json(intent),
        "camera_motion": camera_motion,
        "architecture_profile_version": (prompt.get("a4_profile") or {}).get(
            "architecture_profile_version"),
    })
    if any(job.get("acceptance_input_fingerprint") != input_fingerprint
           for job in previous_acceptance):
        raise A4_2AcceptanceError("current Study inputs differ from the persisted A4.2 experiment")

    runtime_paths.validate_for_job()
    comfy = client or ComfyUIClient(
        base_url="http://127.0.0.1:8189", output_root=str(runtime_paths.output_root),
        strict_output=True, ffmpeg_path=_managed_ffmpeg(runtime_paths),
        health_timeout=5.0, submission_timeout=60.0, metadata_timeout=10.0,
        observation_timeout=15.0, output_timeout=30.0)
    adapter = A4_2AcceptanceRuntimeAdapter(
        client=comfy, comfy_input_dir=str(runtime_paths.input_root),
        production_binding=False, runtime_paths=runtime_paths,
        allow_a4_2_candidate=True)
    preflight = adapter.preflight()  # read-only health, model and live-node checks
    version = str((preflight.get("health") or {}).get("comfyui_version") or "")
    if version != "0.33.1":
        raise A4_2AcceptanceError("A4.2 is pinned to the unchanged production ComfyUI 0.33.1")
    running, pending = _queue_counts(comfy)
    if not active_acceptance and (running or pending):
        raise A4_2AcceptanceError("ComfyUI queue is not idle; no A4.2 prompt was submitted")

    output_api = OutputAPI(store, allow_mock_outputs=False, runtime_paths=runtime_paths)
    job_api = JobAPI(store, output_api=output_api, runtime_adapter=adapter,
                     allow_mock_jobs=False, comfy_input_dir=str(runtime_paths.input_root),
                     runtime_paths=runtime_paths)
    plans: dict[str, dict[str, Any]] = {}
    for arm in ARMS:
        params, profile = resolve_product_parameters(
            WORKFLOW_ID,
            {"quality": arm, "duration": 4.0, "fps": 24, "delivery_fps": 24,
             "seed": 42},
            allow_a4_2_candidate=(arm == "STANDARD"))
        request = job_api._build_request(
            project_id, project, prompt, approved_refs, params, camera_motion)
        # Stage the same approved image before graph construction, so the
        # filename visible in each final payload is identical.
        job_api._stage_refs_to_comfy_input(project_id, request)
        prepared = adapter.prepare(request)
        from runtime.adapters.production_workflow_binding import validate_production_payload
        validation = validate_production_payload(
            prepared["translated_payload"], preflight["object_info"])
        if not validation.get("ready"):
            raise A4_2AcceptanceError("live Comfy node validation failed before submission")
        _validate_prepared_arm_graph(arm, request, params, profile, prepared)
        plans[arm] = {"params": params, "profile": profile,
                      "request": request, "prepared": prepared}
    standard_route = adapter.attach_job_identity(
        copy.deepcopy(plans["STANDARD"]["prepared"]), "a4_2_STANDARD_ROUTE_CHECK")
    native_high_route = adapter.attach_job_identity(
        copy.deepcopy(plans["NATIVE_HIGH"]["prepared"]), "a4_2_NATIVE_HIGH_ROUTE_CHECK")
    route_prefixes = tuple(
        str(next(node for node in route["translated_payload"].values()
                 if isinstance(node, dict) and node.get("class_type") == "SaveVideo")
                .get("inputs", {}).get("filename_prefix") or "")
        for route in (standard_route, native_high_route)
    )
    fair_gate = compare_execution_payloads(
        standard_route["translated_payload"],
        native_high_route["translated_payload"],
        operational_output_prefixes=route_prefixes)
    fair_gate["pair_gate_sha256"] = _sha256_json({
        "standard": fair_gate["standard_workflow_sha256"],
        "native_high": fair_gate["native_high_workflow_sha256"],
        "only_variable": fair_gate["only_variable"],
        "input_fingerprint": input_fingerprint,
    })
    if any(job.get("acceptance_fair_gate", {}).get("pair_gate_sha256")
           != fair_gate["pair_gate_sha256"] for job in previous_acceptance):
        raise A4_2AcceptanceError("recomputed A4.2 fair gate differs from the persisted plan")

    stop_reason = None
    for arm in arms_to_run:
        existing = by_arm.get(arm)
        if arm == "NATIVE_HIGH":
            standard_job = by_arm.get("STANDARD")
            if not _standard_arm_passed(standard_job):
                # A valid paired comparison requires a probed STANDARD output.
                # Do not burn the second GPU arm after a failure or observation gap.
                stop_reason = "STANDARD_ARM_NOT_COMPLETED_AND_PROBED; NATIVE_HIGH_NOT_SUBMITTED"
                break
        params = plans[arm]["params"]
        profile = plans[arm]["profile"]
        request = plans[arm]["request"]
        if existing is not None and existing.get("submission_state") != "NOT_STARTED":
            # An acknowledged or ambiguous /prompt is always observed in place.
            recovered = _reopen_misbound_acceptance_job(
                existing, store, project_id, comfy)
            if recovered:
                existing = job_api.reconcile_job(str(existing["id"]))
            else:
                existing = _wait_or_reconcile(
                    job_api, store, project_id, str(existing["id"]),
                    timeout_seconds=observe_timeout_seconds)
            if _needs_acceptance_probe(existing):
                existing["acceptance_evidence"] = _probe_evidence(
                    existing, runtime_paths, api_base)
                existing["acceptance_completed_at"] = existing.get("finished_at") or _timestamp()
                store.save_jobs(project_id, {**store.load_jobs(project_id),
                                             str(existing["id"]): existing})
            by_arm[arm] = existing
            if is_job_active(existing):
                stop_reason = "SUBMISSION_RECONCILIATION_PENDING; NO_NEW_PROMPT_SUBMITTED"
                break
            continue
        if existing is not None and existing.get("state") in (
                "COMPLETED", "FAILED", "GPU_FAILED", "CANCELLED", "SUBMISSION_LOST"):
            if _needs_acceptance_probe(existing):
                existing["acceptance_evidence"] = _probe_evidence(
                    existing, runtime_paths, api_base)
                existing["acceptance_completed_at"] = (
                    existing.get("finished_at") or _timestamp())
                store.save_jobs(project_id, {**store.load_jobs(project_id),
                                             str(existing["id"]): existing})
            by_arm[arm] = existing
            continue

        running, pending = _queue_counts(comfy)
        if running or pending:
            raise A4_2AcceptanceError(
                f"ComfyUI queue is not idle before the {arm} arm; no new prompt submitted")
        if existing is None:
            source_job_id = str((seed_source or {}).get("id") or "")
            existing = _new_job(
                store, project_id, job_api, request, params, profile,
                pair_id, input_fingerprint, fair_gate, source_job_id)
            by_arm[arm] = existing
        job_id = str(existing["id"])
        start_clock = time.perf_counter()
        sampler = _ResourceSampler(comfy)
        with sampler:
            adapter.progress_callback = lambda event, jid=job_id: job_api._record_progress(
                project_id, jid, event)
            adapter.submission_callback = lambda info, jid=job_id: job_api._record_submission(
                project_id, jid, info)
            job_api._run_real_job(
                project_id, job_id, request,
                prepared=plans[arm]["prepared"],
                before_submit=lambda jid=job_id: _mark_submission_boundary(
                    store, project_id, jid))
        elapsed = round(time.perf_counter() - start_clock, 3)
        existing = store.load_jobs(project_id)[job_id]
        if is_job_active(existing) and existing.get("submission_state") != "NOT_STARTED":
            existing = _wait_or_reconcile(
                job_api, store, project_id, job_id,
                timeout_seconds=observe_timeout_seconds)
        latest = store.load_jobs(project_id).get(job_id, existing)
        latest["acceptance_elapsed_seconds"] = elapsed
        latest["acceptance_vram"] = sampler.evidence()
        if latest.get("state") == "COMPLETED":
            latest["acceptance_evidence"] = _probe_evidence(
                latest, runtime_paths, api_base)
            latest["acceptance_completed_at"] = latest.get("finished_at") or _timestamp()
        store.save_jobs(project_id, {**store.load_jobs(project_id), job_id: latest})
        by_arm[arm] = latest
        if by_arm[arm].get("state") not in ("COMPLETED", "FAILED", "GPU_FAILED",
                                             "CANCELLED", "SUBMISSION_LOST"):
            stop_reason = "JOB_OBSERVATION_PENDING; NO_DUPLICATE_PROMPT_SUBMITTED"
            break

    final_jobs = store.load_jobs(project_id)
    results = {}
    for arm in ARMS:
        job = next((item for item in final_jobs.values()
                    if item.get("acceptance_campaign") == CAMPAIGN
                    and item.get("acceptance_pair_id") == pair_id
                    and item.get("acceptance_arm") == arm), None)
        if job:
            results[arm] = {
                "job_id": job.get("id"),
                "state": job.get("state"),
                "prompt_id": job.get("prompt_id"),
                "workflow_sha256": job.get("execution_workflow_sha256"),
                "elapsed_seconds": job.get("acceptance_elapsed_seconds"),
                "vram": job.get("acceptance_vram"),
                "media": job.get("acceptance_evidence"),
            }
    standard_job = next((item for item in final_jobs.values()
                         if item.get("acceptance_campaign") == CAMPAIGN
                         and item.get("acceptance_pair_id") == pair_id
                         and item.get("acceptance_arm") == "STANDARD"), None)
    high_job = next((item for item in final_jobs.values()
                     if item.get("acceptance_campaign") == CAMPAIGN
                     and item.get("acceptance_pair_id") == pair_id
                     and item.get("acceptance_arm") == "NATIVE_HIGH"), None)
    standard_passed = _standard_arm_passed(standard_job)
    high_passed = _acceptance_arm_passed(high_job)
    if standard_passed and high_passed:
        classification = "A4_2_PAIR_COMPLETE"
    elif standard_passed and high_job is None:
        classification = "A4_2_STANDARD_PASS_HIGH_NOT_RUN"
        stop_reason = stop_reason or "HIGH_REQUIRES_A_SEPARATE_EXPLICIT_INVOCATION"
    elif standard_job and (standard_job.get("state") in (
            "FAILED", "GPU_FAILED", "CANCELLED", "SUBMISSION_LOST")
            or (standard_job.get("state") == "COMPLETED"
                and (standard_job.get("acceptance_evidence") or {}).get("pass") is not True)):
        classification = "A4_2_STANDARD_FAILED"
    else:
        classification = "A4_2_INCOMPLETE_OR_RECONCILING"
    return {
        "classification": classification,
        "pair_id": pair_id,
        "workflow": WORKFLOW_ID,
        "comfyui_version": version,
        "fair_gate": fair_gate,
        "arms": results,
        "stop_reason": stop_reason,
        "owner_visual_review": "PENDING_OWNER",
        "standard_readiness": "PENDING_GPU_AND_OWNER_GATES",
        "quality_cost_classification": "PENDING_OWNER_VISUAL_REVIEW",
    }


__all__ = ["A4_2AcceptanceError", "A4_2AcceptanceRuntimeAdapter",
           "_selected_arms", "_standard_arm_passed",
           "_validate_prepared_arm_graph",
           "_validate_acceptance_study_gate", "_resolved_execution_parameters",
           "compare_execution_payloads",
           "run_a4_2_acceptance"]
