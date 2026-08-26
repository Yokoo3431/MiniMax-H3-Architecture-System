"""NativeRuntimeAdapter (RC3.4 PATCH2.7-C2-A/B).

Extends RuntimeAdapter with the fine-grained lifecycle:
    prepare -> submit -> poll -> collect

Boundaries:
    - Workflow Mapping Layer chooses WHICH workflow (workflow_mapping.yaml)
    - RuntimeAdapter (this class) decides HOW to execute
    - ComfyUIClient is the ONLY ComfyUI HTTP boundary (never exposed upward)
    - Prompt Pipeline is NEVER bypassed: prompt comes from the frozen
      OfficialSkillAdapter output inside VideoGenerationRequest.

PATCH2.7-C2-B: supports all five production workflows (01-05). Link data is
derived from each workflow file when present; the frozen asset
`01_Exterior_Hero_NATIVE.json` carries no connection data (last_link_id=0), so
the embedded I2VA template (identical 15-node architecture, validated) is used
for it. No workflow JSON is modified.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from runtime.yaml_compat import safe_load

from runtime.adapters.comfyui_client import (
    ComfyUIClient,
    ComfyUICommunicationTimeout,
    ComfyUIExecutionError,
    ComfyUIOfflineError,
    ComfyUISubmissionUnknown,
    GenerationTimeoutError,
    WorkflowNotFoundError,
)
from runtime.adapters.runtime_adapter import (
    DEFAULT_CONTRACT,
    REPO_ROOT,
    RuntimeAdapter,
    VideoGenerationRequest,
    load_contract,
    map_runtime_status,
    validate_request,
)
from runtime.adapters.production_workflow_binding import (
    build_production_payload, canonical_workflow_sha256, load_registry,
    production_model_contract,
    validate_production_payload,
)
from runtime.adapters.golden_workflow_binding import (
    bind_golden_workflow, golden_entry,
)
from runtime.adapters.runtime_paths import RuntimePathContract, RuntimePathError
from runtime.h3_model_root import validate_h3_model_contract
from runtime.product_hardening import map_comfy_event

WORKFLOW_MAPPING = REPO_ROOT / "runtime" / "contracts" / "workflow_mapping.yaml"
GOLDEN_05_PATH = REPO_ROOT / "production_workflows" / "golden" / "05_Slow_Walkthrough.json"

SUPPORTED_WORKFLOWS = (
    "01_Exterior_Hero",
    "02_Day_Night_Transition",
    "03_Material_Detail",
    "04_Drone_Aerial",
    "05_Slow_Walkthrough",
)

# Per-class widget input names (verified against Native object_info).
_WIDGET_INPUTS = {
    "LoadImage": ["image"],
    "CLIPLoader": ["clip_name", "type"],
    "UNETLoader": ["unet_name", "weight_dtype"],
    "VAELoader": ["vae_name"],
    "MiniMaxH3ImageToVideo": ["prompt", "width", "height", "length"],
    "KSamplerSelect": ["sampler_name"],
    "BasicScheduler": ["scheduler", "steps", "denoise"],
    "RandomNoise": ["noise_seed"],
    "CreateVideo": ["fps"],
    "SaveVideo": ["filename_prefix", "format", "codec"],
    "BasicGuider": [],
    "SamplerCustomAdvanced": [],
    "VAEDecode": [],
    "VAEDecodeAudio": [],
}

# Link template fallback (only for assets without connection data, e.g. 01),
# derived from the validated I2VA architecture (identical 15-node graph).
_LINKS = {
    "6": {"clip": ["2", 0], "vae": ["4", 0], "first_frame": ["1", 0]},
    "8": {"model": ["3", 0]},
    "10": {"model": ["3", 0], "conditioning": ["6", 0]},
    "11": {"noise": ["9", 0], "guider": ["10", 0], "sampler": ["7", 0],
           "sigmas": ["8", 0], "latent_image": ["6", 1]},
    "12": {"samples": ["11", 0], "vae": ["4", 0]},
    "13": {"samples": ["11", 0], "vae": ["5", 0]},
    "14": {"images": ["12", 0], "audio": ["13", 0]},
    "15": {"video": ["14", 0]},
}


def parse_resolution(resolution: str) -> tuple[int, int]:
    parts = str(resolution).lower().replace("x", " ").split()
    if len(parts) != 2:
        raise ValueError(f"invalid resolution {resolution!r}")
    return int(parts[0]), int(parts[1])


def length_for(duration: float, fps: int) -> int:
    """H3 frame-grid length (validated: 4s@24 -> 107 frames)."""
    return int(round(float(duration) * int(fps))) + 11


class NativeRuntimeAdapter(RuntimeAdapter):
    name = "native"

    def __init__(self, client: Optional[ComfyUIClient] = None,
                 contract_path: Path = DEFAULT_CONTRACT,
                 workflow_mapping_path: Path = WORKFLOW_MAPPING,
                 clock: Optional[Callable[[], float]] = None,
                 comfy_input_dir: Optional[str] = None,
                 production_binding: bool = False,
                 runtime_paths: Optional[RuntimePathContract] = None) -> None:
        super().__init__(contract_path)
        self.client = client or ComfyUIClient()
        self.workflow_mapping = safe_load(
            Path(workflow_mapping_path).read_text(encoding="utf-8"))
        self.clock = clock or time.time
        self.comfy_input_dir = Path(comfy_input_dir) if comfy_input_dir else None
        self.production_binding = bool(production_binding)
        self.runtime_paths = runtime_paths
        self.jobs: Dict[str, Dict[str, Any]] = {}
        self.progress_callback = None
        self.submission_callback = None

    # ------------------------------------------------------------------ #
    # prepare
    # ------------------------------------------------------------------ #
    def preflight(self) -> Dict[str, Any]:
        """Validate live ComfyUI capability and all five model bindings.

        This is intentionally read-only: it uses health and object metadata,
        never ``/prompt`` and never loads a model.
        """
        if self.runtime_paths is not None:
            self.runtime_paths.validate_for_job()
            h3_root = validate_h3_model_contract(
                self.runtime_paths.runtime_root,
                self.runtime_paths.models_root,
            )
            if not h3_root.get("ready"):
                raise ComfyUIExecutionError(
                    "MODEL_PATH_ERROR: MiniMax-H3 model root is not visible to the "
                    "pinned loader: " + json.dumps(h3_root, ensure_ascii=False)
                )
        health = self.client.health_check()
        object_info = self.client.object_info()
        golden_results = {}
        for workflow_id in SUPPORTED_WORKFLOWS:
            try:
                payload = bind_golden_workflow({
                    "reference_assets": [
                        {"path_or_ref": "preflight-first.png"},
                        {"path_or_ref": "preflight-last.png"},
                    ][:int(golden_entry(workflow_id)["required_reference_count"])],
                    "generation_parameters": {
                        "resolution": "1344x768", "fps": 24, "duration": 4.0,
                        "quality": "diagnostic", "seed": 42,
                    },
                    "prompt_payload": {"prompt": "preflight"},
                }, workflow_id)
                golden_results[workflow_id] = validate_production_payload(
                    payload, object_info)
            except Exception as exc:  # noqa: BLE001 - normalized below
                golden_results[workflow_id] = {"ready": False, "errors": [str(exc)]}
        binding = {"ready": all(item.get("ready") for item in golden_results.values()),
                   "workflows": golden_results}
        if not binding["ready"]:
            raise ComfyUIExecutionError(
                "WORKFLOW_BINDING_ERROR: Golden graph validation failed: "
                + json.dumps(binding, ensure_ascii=False))
        return {"ready": True, "health": health, "object_info": object_info,
                "model_bindings": binding}

    def prepare(self, request: Any) -> Dict[str, Any]:
        if self.runtime_paths is not None:
            self.runtime_paths.validate_for_job()
        if self.production_binding and hasattr(self.client, "object_info"):
            self.preflight()
        data = request.to_dict() if isinstance(request, VideoGenerationRequest) else dict(request)
        errors = validate_request(data, self.contract)
        if errors:
            raise ValueError("VideoGenerationRequest contract violation: " + "; ".join(errors))
        workflow_id = data["workflow_id"]
        if workflow_id not in SUPPORTED_WORKFLOWS:
            raise WorkflowNotFoundError(
                f"PATCH2.7-C2-A scope: only {SUPPORTED_WORKFLOWS} supported; got {workflow_id}")
        registry = self.workflow_mapping["workflow_registry"]
        if workflow_id not in registry:
            raise WorkflowNotFoundError(f"unknown workflow_id: {workflow_id}")
        mode = registry[workflow_id]["input_mode"]
        refs = data.get("reference_assets") or []
        if mode == "I2VA" and len(refs) != 1:
            raise ValueError(
                f"{workflow_id} is {mode}: exactly 1 reference required; got {len(refs)}")
        if mode == "FL2VA" and len(refs) != 2:
            raise ValueError(
                f"{workflow_id} is {mode}: exactly 2 references (first+last) required; got {len(refs)}")
        supported_cameras = set(registry[workflow_id].get("supported_camera") or [])
        if data.get("camera_motion") not in supported_cameras:
            raise ValueError(
                f"camera_motion {data.get('camera_motion')!r} not supported by "
                f"{workflow_id}: {sorted(supported_cameras)}")
        golden = golden_entry(workflow_id)
        payload = bind_golden_workflow(data, workflow_id)
        source = str(golden["golden_path"])
        return {
            "job_id": f"native-{uuid.uuid4().hex[:12]}",
            "study_id": data["study_id"],
            "workflow_id": workflow_id,
            "workflow_asset": source,
            "translated_payload": payload,
            "execution_workflow_sha256": canonical_workflow_sha256(payload),
            "binding": {
                "source_of_truth": source,
                "canonical_source": source,
                "parameter_binder": golden["binder"],
                "base_structure_hash": golden.get("base_structure_hash"),
                "browser_state_ignored": True,
            },
            "control": {
                "submit_timeout_seconds": 60.0,
                "poll_interval_seconds": 5.0,
                "history_timeout_seconds": 1800.0,
            },
        }
        # 05_Slow_Walkthrough is the historical, real native-runtime proof.
        # Keep it on the exact frozen 15-node UI asset and the existing
        # NativeRuntimeAdapter binder.  The production binding builder is
        # intentionally bypassed for this workflow so diagnostics and /prompt
        # cannot drift into a second RH loader graph.
        if self.production_binding and workflow_id != "05_Slow_Walkthrough":
            production_entry = load_registry()["workflows"][workflow_id]
            asset_rel = production_entry["canonical_source"]
            asset_path = REPO_ROOT / asset_rel
            if not asset_path.is_file():
                raise WorkflowNotFoundError(f"production workflow asset missing: {asset_path}")
            payload = build_production_payload(data, workflow_id)
            return {
                "job_id": f"native-{uuid.uuid4().hex[:12]}",
                "study_id": data["study_id"],
                "workflow_id": workflow_id,
                "workflow_asset": asset_rel,
                "translated_payload": payload,
                "execution_workflow_sha256": canonical_workflow_sha256(payload),
                "binding": {
                    "source_of_truth": "configs/production_workflow_registry.json",
                    "canonical_source": asset_rel,
                    "payload_template": production_entry["payload_template"],
                    "model_bindings": production_model_contract(
                        data.get("h3_profile") or data.get("model_profile")
                        or data.get("hardware_profile") or "COMPATIBILITY",
                        gpu_vram_gb=data.get("gpu_vram_gb"),
                        system_ram_gb=data.get("system_ram_gb")),
                    "browser_state_ignored": True,
                },
                "control": {
                    "submit_timeout_seconds": 60.0,
                    "poll_interval_seconds": 5.0,
                    "history_timeout_seconds": 1800.0,
                },
            }
        asset_rel = registry[workflow_id]["native_asset"]
        asset_path = REPO_ROOT / asset_rel
        if not asset_path.is_file():
            raise WorkflowNotFoundError(f"native workflow asset missing: {asset_path}")

        payload = self._build_comfy_payload(data, workflow_id, asset_path)
        source_of_truth = (
            "production_workflows/golden/05_Slow_Walkthrough.json"
            if workflow_id == "05_Slow_Walkthrough" and GOLDEN_05_PATH.is_file()
            else asset_rel
        )
        return {
            "job_id": f"native-{uuid.uuid4().hex[:12]}",
            "study_id": data["study_id"],
            "workflow_id": workflow_id,
            "workflow_asset": source_of_truth,
            "translated_payload": payload,
            "execution_workflow_sha256": canonical_workflow_sha256(payload),
            "binding": {
                "source_of_truth": source_of_truth,
                "canonical_source": source_of_truth,
                "parameter_binder": "NativeRuntimeAdapter._build_comfy_payload",
                "browser_state_ignored": True,
                "historical_native_contract": "PATCH2.7-C2-B / 05 I2VA",
            },
            "control": {
                "submit_timeout_seconds": 60.0,
                "poll_interval_seconds": 5.0,
                "history_timeout_seconds": 1800.0,
            },
        }

    def _build_comfy_payload(self, request: Dict[str, Any],
                             workflow_id: str, asset_path: Path) -> Dict[str, Any]:
        ui = json_load(asset_path)
        mode = request.get("prompt_payload", {}).get("mode", "I2VA")
        if mode == "FL2VA":
            # 02 uses the file's own (verified consistent) links.
            link_map = _links_from_file(ui) or dict(_LINKS)
        else:
            # All I2VA workflows share the identical validated 15-node graph;
            # the template avoids depending on asset link-id corruption (04).
            link_map = dict(_LINKS)
        params = request["generation_parameters"]
        prompt = request["prompt_payload"]["prompt"]
        width, height = parse_resolution(params.get("resolution", "1344x768"))
        length = length_for(params.get("duration", 4.0), params.get("fps", 24))
        seed = int(params.get("seed", 42))
        fps = float(params.get("fps", 24))
        ref_names = [Path(r.get("path_or_ref", "reference.png")).name
                     for r in request["reference_assets"]]

        # After the owner-authorized historical run succeeds, the exact API
        # graph becomes the sole 05 source.  Only the proven mutable controls
        # are rebound; node types, links, loader classes and topology remain
        # frozen in the captured graph.
        if workflow_id == "05_Slow_Walkthrough" and GOLDEN_05_PATH.is_file():
            prompt_payload = json_load(GOLDEN_05_PATH)
            classes = [node.get("class_type") for node in prompt_payload.values()]
            if len(prompt_payload) != 15 or "RHMiniMaxH3TextEncoderLoader" in classes:
                raise WorkflowNotFoundError("05 golden workflow contract is invalid")
            prompt_payload["1"]["inputs"]["image"] = ref_names[0]
            prompt_payload["6"]["inputs"].update({
                "prompt": prompt,
                "width": width,
                "height": height,
                "length": length,
            })
            prompt_payload["9"]["inputs"]["noise_seed"] = seed
            prompt_payload["14"]["inputs"]["fps"] = fps
            prompt_payload["15"]["inputs"]["filename_prefix"] = (
                f"video/{workflow_id}_C2B_{seed}"
            )
            return prompt_payload

        widgets: Dict[str, list] = {}
        for node in ui.get("nodes", []):
            widgets[str(node["id"])] = list(node.get("widgets_values") or [])

        prompt_payload: Dict[str, Any] = {}
        for node in ui.get("nodes", []):
            nid = str(node["id"])
            cls = node["type"]
            names = _WIDGET_INPUTS.get(cls, [])
            inputs: Dict[str, Any] = {}
            wv = widgets.get(nid, [])
            for i, name in enumerate(names):
                if i < len(wv):
                    inputs[name] = wv[i]
            for name, ref in link_map.get(nid, {}).items():
                inputs[name] = ref
            prompt_payload[nid] = {"class_type": cls, "inputs": inputs}

        # ---- parameter injection (frozen asset untouched) ----
        h3_inputs = link_map.get("6", {})
        first_link = h3_inputs.get("first_frame")
        last_link = h3_inputs.get("last_frame")
        first_node = str(first_link[0]) if first_link else "1"
        last_node = str(last_link[0]) if last_link else None

        prompt_payload[first_node]["inputs"]["image"] = ref_names[0]
        if last_node is not None:
            prompt_payload[last_node]["inputs"]["image"] = ref_names[1]
        prompt_payload["6"]["inputs"].update({
            "prompt": prompt,
            "width": width,
            "height": height,
            "length": length,
        })
        prompt_payload["9"]["inputs"]["noise_seed"] = seed
        prompt_payload["14"]["inputs"]["fps"] = fps
        prompt_payload["15"]["inputs"]["filename_prefix"] = (
            f"video/{workflow_id}_C2B_{seed}")
        return prompt_payload

    # ------------------------------------------------------------------ #
    # lifecycle
    # ------------------------------------------------------------------ #
    def attach_job_identity(self, native_request: Dict[str, Any],
                            avs_job_id: str) -> Dict[str, Any]:
        """Bind correlation to the already-built graph without changing topology."""
        payload = native_request["translated_payload"]
        save_nodes = [node for node in payload.values()
                      if node.get("class_type") == "SaveVideo"]
        if save_nodes:
            inputs = save_nodes[0].setdefault("inputs", {})
            prefix = str(inputs.get("filename_prefix") or "video/output")
            if avs_job_id not in prefix:
                inputs["filename_prefix"] = f"{prefix}_{avs_job_id}"
        native_request["avs_job_id"] = str(avs_job_id)
        native_request["execution_workflow_sha256"] = canonical_workflow_sha256(payload)
        return native_request

    def submit(self, native_request: Dict[str, Any]) -> str:
        kwargs = {
            "client_id": str(uuid.uuid4()),
            "avs_job_id": native_request.get("avs_job_id"),
            "execution_workflow_sha256": native_request.get(
                "execution_workflow_sha256"),
        }
        try:
            result = self.client.submit_workflow(
                native_request["translated_payload"], **kwargs)
        except TypeError:
            # Keep CPU/legacy duck-typed clients usable while the production
            # client carries the correlation metadata.
            result = self.client.submit_workflow(
                native_request["translated_payload"],
                client_id=kwargs["client_id"],
            )
        except ComfyUISubmissionUnknown as exc:
            reconcile = getattr(self.client, "reconcile_prompt", None)
            if reconcile is None:
                raise
            found = reconcile(
                avs_job_id=native_request.get("avs_job_id"),
                execution_workflow_sha256=native_request.get(
                    "execution_workflow_sha256"),
                legacy_seed=(native_request.get("translated_payload", {})
                             .get("9", {}).get("inputs", {}).get("noise_seed")),
            )
            if found.get("status") in ("RUNNING", "COMPLETED") and found.get("prompt_id"):
                result = {"prompt_id": found["prompt_id"],
                          "reconciled": True, "reconciliation": found}
            elif found.get("status") == "FAILED":
                raise ComfyUIExecutionError(
                    "ComfyUI accepted the task but reported failure during "
                    f"reconciliation: {found.get('entry')}") from exc
            else:
                raise ComfyUICommunicationTimeout(
                    "ComfyUI prompt acknowledgement was lost and the task "
                    "could not yet be found in queue/history") from exc
        return result["prompt_id"]

    def poll(self, prompt_id: str, timeout_seconds: float = 1800.0,
             poll_interval: float = 5.0, on_event=None) -> Dict[str, Any]:
        if on_event is None:
            return self.client.wait_completion(prompt_id, timeout_seconds, poll_interval)
        try:
            return self.client.wait_completion(prompt_id, timeout_seconds, poll_interval,
                                               on_event=lambda event: on_event(map_comfy_event(event)))
        except TypeError:
            # Preserve compatibility with the existing CPU fake clients and
            # older third-party Comfy clients which predate the callback.
            return self.client.wait_completion(prompt_id, timeout_seconds, poll_interval)

    def collect(self, history_result: Dict[str, Any], job_id: str,
                workflow_id: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self.client.collect_output(history_result, job_id, workflow_id, metadata)

    # ------------------------------------------------------------------ #
    # RuntimeAdapter interface
    # ------------------------------------------------------------------ #
    def generate(self, request: Any, prepared: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        native_req = prepared or self.prepare(request)
        if native_req.get("execution_workflow_sha256") != canonical_workflow_sha256(
                native_req["translated_payload"]):
            raise ComfyUIExecutionError("EXECUTION_WORKFLOW_IDENTITY_MISMATCH")
        job_id = native_req["job_id"]
        self.jobs[job_id] = {
            "id": job_id,
            "adapter": self.name,
            "status": "QUEUED",
            "prompt_id": None,
            "stages": ["QUEUED"],
            "failure_reason": "",
            "error_code": "",
            "output": None,
            "created_at": self.clock(),
            "request": native_req,
        }
        try:
            self.jobs[job_id]["status"] = "PREPARING"
            self.jobs[job_id]["stages"].append("PREPARING")
            prompt_id = self.submit(native_req)
            self.jobs[job_id]["prompt_id"] = prompt_id
            self.jobs[job_id]["submission_state"] = "ACKNOWLEDGED"
            callback = getattr(self, "submission_callback", None)
            if callback is not None:
                callback({"prompt_id": prompt_id,
                          "avs_job_id": native_req.get("avs_job_id"),
                          "execution_workflow_sha256": native_req.get(
                              "execution_workflow_sha256"),
                          "status": "ACKNOWLEDGED"})
            self.jobs[job_id]["status"] = "EXECUTING"
            self.jobs[job_id]["stages"].append("EXECUTING")
            state = self.poll(
                prompt_id,
                timeout_seconds=native_req["control"]["history_timeout_seconds"],
                poll_interval=native_req["control"]["poll_interval_seconds"],
                on_event=getattr(self, "progress_callback", None),
            )
            if state["status"] != "COMPLETED":
                raise ComfyUIExecutionError(
                    f"ComfyUI execution failed for {prompt_id}: {state.get('messages')}")
            history = self.client.get_history(prompt_id)
            request_data = self.jobs[job_id]["request"]
            workflow_id = request_data.get("workflow_id", "01_Exterior_Hero")
            metadata = {
                "study_id": native_req["study_id"],
                "workflow_id": workflow_id,
                "camera_motion": self._request_field(request, "camera_motion", "slow_push"),
                "resolution": self._request_param(request, "resolution", "1344x768"),
                "fps": self._request_param(request, "fps", 24),
                "duration": self._request_param(request, "duration", 4.0),
                "quality": self._request_param(request, "quality", "diagnostic"),
                "seed": self._request_param(request, "seed", 42),
                "prompt_hash": self._request_prompt_hash(request),
            }
            output = self.collect(history, job_id, workflow_id, metadata)
            self.jobs[job_id]["output"] = output
            self.jobs[job_id]["status"] = "COMPLETED"
            self.jobs[job_id]["stages"].append("COMPLETED")
        except ComfyUICommunicationTimeout as exc:
            self._fail(job_id, "communication timeout; reconciliation required",
                       "COMFY_COMMUNICATION_TIMEOUT", str(exc))
            raise
        except ComfyUIOfflineError as exc:
            self._fail(job_id, "ComfyUI offline", "", str(exc))
            raise
        except WorkflowNotFoundError as exc:
            self._fail(job_id, "workflow not found", "WORKFLOW_NOT_FOUND", str(exc))
            raise
        except GenerationTimeoutError as exc:
            self._fail(job_id, "generation timeout", "TIMEOUT_ERROR", str(exc))
            raise
        except ComfyUIExecutionError as exc:
            code = self._execution_error_code(str(exc))
            self._fail(job_id, "execution error", code, str(exc))
            raise
        except Exception as exc:
            self._fail(job_id, "unexpected error", "OUTPUT_ERROR", str(exc))
            raise
        return self.status(job_id)

    def status(self, job_id: str) -> Dict[str, Any]:
        job = self.jobs.get(job_id)
        if job is None:
            raise KeyError(f"runtime job not found: {job_id}")
        return {
            "job_id": job["id"],
            "adapter": job["adapter"],
            "status": job["status"],
            "prompt_id": job.get("prompt_id"),
            "stages": list(job["stages"]),
            "existing_job_status": self._existing_status(job),
            "failure_reason": job["failure_reason"],
            "error_code": job["error_code"],
            "has_output": job["status"] == "COMPLETED",
            "progress": job.get("progress"),
            "current_stage": job.get("current_stage", "执行工作流"),
            "step": job.get("step"),
            "total_steps": job.get("total_steps"),
            "eta_seconds": job.get("eta_seconds"),
            "execution_workflow_sha256": (
                job.get("request", {}).get("execution_workflow_sha256")
            ),
        }

    def cancel(self, job_id: str) -> Dict[str, Any]:
        job = self.jobs.get(job_id)
        if job is None:
            raise KeyError(f"runtime job not found: {job_id}")
        if job["status"] in ("COMPLETED", "FAILED", "CANCELLED"):
            raise ValueError(f"job {job_id} already terminal ({job['status']})")
        job["status"] = "CANCELLED"
        job["failure_reason"] = "cancelled by user"
        job["stages"].append("CANCELLED")
        return self.status(job_id)

    def get_output(self, job_id: str) -> Dict[str, Any]:
        job = self.jobs.get(job_id)
        if job is None:
            raise KeyError(f"runtime job not found: {job_id}")
        if job["status"] != "COMPLETED":
            raise ValueError(f"output available only when COMPLETED; job is {job['status']}")
        return job["output"]

    def _existing_status(self, job: Dict[str, Any]) -> str:
        """Adapter lifecycle -> existing job status (mapping only)."""
        status = job["status"]
        if status == "COMPLETED":
            return "COMPLETED"
        if status == "CANCELLED":
            return "GPU_FAILED"
        if status == "FAILED":
            fail_codes = ("WORKFLOW_NOT_FOUND", "TIMEOUT_ERROR",
                          "MISSING_RUNTIME_NODE", "WORKFLOW_RUNTIME_MISMATCH",
                          "OUTPUT_ERROR", "INVALID_REQUEST", "ASSET_NOT_FOUND",
                          "COMFYUI_CRASHED")
            return "FAILED" if job.get("error_code") in fail_codes else "GPU_FAILED"
        if status in ("QUEUED", "PREPARING"):
            return "PREPARING"
        return "LOADING_MODEL"  # EXECUTING coarse phase -> representative stage

    # ------------------------------------------------------------------ #
    def _fail(self, job_id: str, reason: str, error_code: str, detail: str) -> None:
        job = self.jobs[job_id]
        job["status"] = "FAILED"
        job["failure_reason"] = f"{reason}: {detail}"
        job["error_code"] = error_code
        job["stages"].append("FAILED")

    @staticmethod
    def _execution_error_code(message: str) -> str:
        low = message.lower()
        if "missing_node_type" in low or ("node type" in low and "not found" in low):
            return "MISSING_RUNTIME_NODE"
        if "out of memory" in low or "cuda out of memory" in low or "oom" in low:
            return "RESOURCE_ERROR"
        if "node error" in low or "execution failed" in low:
            return "WORKFLOW_EXECUTION_ERROR"
        if "model" in low and "load" in low:
            return "MODEL_LOAD_ERROR"
        return "WORKFLOW_EXECUTION_ERROR"

    @staticmethod
    def _request_param(request: Any, key: str, default: Any) -> Any:
        data = request.to_dict() if hasattr(request, "to_dict") else dict(request or {})
        return data.get("generation_parameters", {}).get(key, default)

    @staticmethod
    def _request_field(request: Any, key: str, default: Any) -> Any:
        data = request.to_dict() if hasattr(request, "to_dict") else dict(request or {})
        return data.get(key, default)

    @staticmethod
    def _request_prompt_hash(request: Any) -> Any:
        data = request.to_dict() if hasattr(request, "to_dict") else dict(request or {})
        return data.get("prompt_payload", {}).get("prompt_hash")


def json_load(path: Path) -> dict:
    import json
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _links_from_file(ui: dict) -> Dict[str, Dict[str, list]]:
    """Derive node_id -> {input_name: [src_node, src_output_idx]} from UI JSON.

    Type-aware: when a stored link id resolves to a source whose output type does
    not match the input type (a save artifact seen in the frozen 04 asset), the
    matching unconsumed output is used instead. No workflow JSON is modified.
    """
    out_by_link: Dict[str, dict] = {}
    for node in ui.get("nodes", []):
        for idx, out in enumerate(node.get("outputs") or []):
            for lid in out.get("links") or []:
                out_by_link[str(lid)] = {
                    "node": str(node["id"]), "idx": idx, "type": out.get("type"),
                }

    pending: list = []
    consumed: set = set()
    node_links: Dict[str, Dict[str, list]] = {}
    for node in ui.get("nodes", []):
        nid = str(node["id"])
        for inp in node.get("inputs") or []:
            lid = inp.get("link")
            if lid is None:
                continue
            src = out_by_link.get(str(lid))
            if src is None:
                continue
            if src["type"] == inp.get("type"):
                node_links.setdefault(nid, {})[inp["name"]] = [src["node"], src["idx"]]
                consumed.add(str(lid))
            else:
                pending.append((nid, inp["name"], inp.get("type"), str(lid)))

    # Repair pass: assign the matching unconsumed output for type-mismatched inputs.
    for nid, name, expected_type, _orig_lid in pending:
        for lid, src in out_by_link.items():
            if lid in consumed or src["type"] != expected_type:
                continue
            node_links.setdefault(nid, {})[name] = [src["node"], src["idx"]]
            consumed.add(lid)
            break
    return node_links


__all__ = ["NativeRuntimeAdapter", "parse_resolution", "length_for", "_links_from_file"]
