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

import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import yaml

from runtime.adapters.comfyui_client import (
    ComfyUIClient,
    ComfyUIExecutionError,
    ComfyUIOfflineError,
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

WORKFLOW_MAPPING = REPO_ROOT / "runtime" / "contracts" / "workflow_mapping.yaml"

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
                 comfy_input_dir: Optional[str] = None) -> None:
        super().__init__(contract_path)
        self.client = client or ComfyUIClient()
        self.workflow_mapping = yaml.safe_load(
            Path(workflow_mapping_path).read_text(encoding="utf-8"))
        self.clock = clock or time.time
        self.comfy_input_dir = Path(comfy_input_dir) if comfy_input_dir else None
        self.jobs: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------------ #
    # prepare
    # ------------------------------------------------------------------ #
    def prepare(self, request: Any) -> Dict[str, Any]:
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
        asset_rel = registry[workflow_id]["native_asset"]
        asset_path = REPO_ROOT / asset_rel
        if not asset_path.is_file():
            raise WorkflowNotFoundError(f"native workflow asset missing: {asset_path}")

        payload = self._build_comfy_payload(data, workflow_id, asset_path)
        return {
            "job_id": f"native-{uuid.uuid4().hex[:12]}",
            "study_id": data["study_id"],
            "workflow_id": workflow_id,
            "workflow_asset": asset_rel,
            "translated_payload": payload,
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
    def submit(self, native_request: Dict[str, Any]) -> str:
        result = self.client.submit_workflow(
            native_request["translated_payload"],
            client_id=str(uuid.uuid4()),
        )
        return result["prompt_id"]

    def poll(self, prompt_id: str, timeout_seconds: float = 1800.0,
             poll_interval: float = 5.0) -> Dict[str, Any]:
        return self.client.wait_completion(prompt_id, timeout_seconds, poll_interval)

    def collect(self, history_result: Dict[str, Any], job_id: str,
                workflow_id: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self.client.collect_output(history_result, job_id, workflow_id, metadata)

    # ------------------------------------------------------------------ #
    # RuntimeAdapter interface
    # ------------------------------------------------------------------ #
    def generate(self, request: Any) -> Dict[str, Any]:
        native_req = self.prepare(request)
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
            self.jobs[job_id]["status"] = "EXECUTING"
            self.jobs[job_id]["stages"].append("EXECUTING")
            state = self.poll(
                prompt_id,
                timeout_seconds=native_req["control"]["history_timeout_seconds"],
                poll_interval=native_req["control"]["poll_interval_seconds"],
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
                          "OUTPUT_ERROR", "INVALID_REQUEST", "ASSET_NOT_FOUND")
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
