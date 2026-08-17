"""Runtime Adapter boundary (RC3.4 PATCH2.7-A).

Independent boundary between the Architect Video Studio UI/API and the future
real video generation runtime (ComfyUI Native). This phase ships ONLY the
contract and a MockRuntimeAdapter:

    - no GPU / CUDA call
    - no ComfyUI call
    - no Native runtime call
    - no model loading

The existing state machine (apps/architect_video_studio/state_machine) is NOT
modified. Runtime status -> existing job status is a mapping-only concern
(contracts/video_generation_request.yaml -> state_mapping).
"""

from __future__ import annotations

import abc
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONTRACT = REPO_ROOT / "runtime" / "contracts" / "video_generation_request.yaml"

TERMINAL_RUNTIME_STATUSES = {"COMPLETED", "FAILED", "CANCELLED"}


def load_contract(path: Path = DEFAULT_CONTRACT) -> dict:
    if not Path(path).is_file():
        raise FileNotFoundError(f"runtime contract missing: {path}")
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def _allowed(node: Any) -> List[str]:
    """Extract the 'allowed' list from a contract enum node."""
    if isinstance(node, dict):
        allowed = node.get("allowed") or []
        return list(allowed) if isinstance(allowed, list) else []
    return []


def validate_request(request: Dict[str, Any],
                     contract: Optional[dict] = None) -> List[str]:
    """Returns a list of contract violations (empty == valid)."""
    contract = contract or load_contract()
    req = contract["video_generation_request"]
    errors: List[str] = []

    for key in ("study_id", "reference_assets", "workflow_id", "camera_motion",
                "generation_parameters", "prompt_payload", "output_spec", "gates"):
        if not request.get(key):
            errors.append(f"missing required field: {key}")

    workflows = set(_allowed(req.get("workflow_id")))
    if request.get("workflow_id") and request["workflow_id"] not in workflows:
        errors.append(f"workflow_id {request['workflow_id']!r} not in {sorted(workflows)}")

    motions = set(_allowed(req.get("camera_motion")))
    if request.get("camera_motion") and request["camera_motion"] not in motions:
        errors.append(f"camera_motion {request['camera_motion']!r} not in {sorted(motions)}")

    refs = request.get("reference_assets") or []
    if not isinstance(refs, list) or not refs:
        errors.append("reference_assets must be a non-empty list")

    params = request.get("generation_parameters") or {}
    if params:
        resolution = params.get("resolution", "1344x768")
        res_allowed = (req.get("generation_parameters", {}).get("fields", {})
                       .get("resolution", {}).get("allowed")) or ["1344x768", "1280x720"]
        if resolution not in set(res_allowed):
            errors.append(f"resolution {resolution!r} not allowed")
        if params.get("fps", 24) not in [24]:
            errors.append("fps must be 24")
        if params.get("quality") not in (None, "diagnostic", "production"):
            errors.append("quality must be diagnostic|production")
        if "seed" not in params:
            errors.append("generation_parameters.seed is required")

    prompt = request.get("prompt_payload") or {}
    if prompt:
        if prompt.get("mode") not in ("I2VA", "FL2VA"):
            errors.append("prompt_payload.mode must be I2VA|FL2VA")
        if not prompt.get("prompt"):
            errors.append("prompt_payload.prompt is required")
        if not prompt.get("prompt_hash"):
            errors.append("prompt_payload.prompt_hash is required")

    gates = request.get("gates") or {}
    for gate in ("reference_approved", "intent_confirmed", "prompt_verified", "risk_reviewed"):
        if gates.get(gate) is not True:
            errors.append(f"gate {gate} must be true")
    return errors


def map_runtime_status(runtime_status: str,
                       contract: Optional[dict] = None) -> str:
    """Runtime Status -> existing Job Status (mapping only, machine unchanged)."""
    contract = contract or load_contract()
    mapping = contract["state_mapping"]
    if runtime_status not in mapping:
        raise ValueError(f"unknown runtime status {runtime_status!r}")
    return mapping[runtime_status]


@dataclass
class VideoGenerationRequest:
    """Typed wrapper over the YAML contract (VideoGenerationRequest)."""

    study_id: str
    reference_assets: List[Dict[str, Any]]
    workflow_id: str
    camera_motion: str
    generation_parameters: Dict[str, Any]
    prompt_payload: Dict[str, Any]
    output_spec: Dict[str, Any] = field(default_factory=lambda: {
        "container": "mp4", "codec": "h264", "fps": 24,
        "resolution": "1344x768", "report_format": "json",
    })
    gates: Dict[str, bool] = field(default_factory=lambda: {
        "reference_approved": True,
        "intent_confirmed": True,
        "prompt_verified": True,
        "risk_reviewed": True,
    })

    def to_dict(self) -> Dict[str, Any]:
        return {
            "study_id": self.study_id,
            "reference_assets": self.reference_assets,
            "workflow_id": self.workflow_id,
            "camera_motion": self.camera_motion,
            "generation_parameters": self.generation_parameters,
            "prompt_payload": self.prompt_payload,
            "output_spec": self.output_spec,
            "gates": self.gates,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VideoGenerationRequest":
        return cls(
            study_id=data["study_id"],
            reference_assets=data["reference_assets"],
            workflow_id=data["workflow_id"],
            camera_motion=data["camera_motion"],
            generation_parameters=data["generation_parameters"],
            prompt_payload=data["prompt_payload"],
            output_spec=data.get("output_spec"),
            gates=data.get("gates"),
        )


@dataclass
class VideoGenerationOutput:
    """Output contract (current: mock path; future: native path)."""

    job_id: str
    video_path: str
    preview_path: str
    metadata: Dict[str, Any]
    runtime_info: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "video_path": self.video_path,
            "preview_path": self.preview_path,
            "metadata": self.metadata,
            "runtime_info": self.runtime_info,
        }


class RuntimeAdapter(abc.ABC):
    """Runtime adapter interface (generate / status / cancel)."""

    name = "base"

    def __init__(self, contract_path: Path = DEFAULT_CONTRACT) -> None:
        self.contract_path = Path(contract_path)
        self.contract = load_contract(self.contract_path)

    @abc.abstractmethod
    def generate(self, request: Any) -> Dict[str, Any]:
        """Submit a VideoGenerationRequest; returns a runtime job snapshot."""

    @abc.abstractmethod
    def status(self, job_id: str) -> Dict[str, Any]:
        """Return current runtime status for a job."""

    @abc.abstractmethod
    def cancel(self, job_id: str) -> Dict[str, Any]:
        """Cancel a non-terminal job; no auto retry."""

    def get_output(self, job_id: str) -> Dict[str, Any]:
        raise NotImplementedError

    def map_status(self, runtime_status: str) -> str:
        return map_runtime_status(runtime_status, self.contract)


class MockRuntimeAdapter(RuntimeAdapter):
    """Mock implementation. Returns mock jobs; never touches GPU/ComfyUI."""

    name = "mock"

    # elapsed-seconds thresholds for simulated stage progression
    STAGE_AT = {
        "QUEUED": 0.0,
        "PREPARING": 0.5,
        "LOADING_MODEL": 1.0,
        "SAMPLING": 2.0,
        "ENCODING": 3.0,
        "EXPORTING": 4.0,
        "COMPLETED": 5.0,
    }

    def __init__(self, contract_path: Path = DEFAULT_CONTRACT,
                 clock: Optional[Callable[[], float]] = None) -> None:
        super().__init__(contract_path)
        self.clock = clock or time.time
        self.jobs: Dict[str, Dict[str, Any]] = {}

    def generate(self, request: Any) -> Dict[str, Any]:
        data = request.to_dict() if isinstance(request, VideoGenerationRequest) else dict(request)
        errors = validate_request(data, self.contract)
        if errors:
            raise ValueError("VideoGenerationRequest contract violation: " + "; ".join(errors))
        now = self.clock()
        job_id = f"rt-{uuid.uuid4().hex[:12]}"
        self.jobs[job_id] = {
            "id": job_id,
            "adapter": self.name,
            "status": "QUEUED",
            "created_at": now,
            "started_at": now,
            "elapsed": 0.0,
            "stages": ["QUEUED"],
            "failure_reason": "",
            "request": data,
        }
        return self.status(job_id)

    def status(self, job_id: str) -> Dict[str, Any]:
        job = self.jobs.get(job_id)
        if job is None:
            raise KeyError(f"runtime job not found: {job_id}")
        if job["status"] not in TERMINAL_RUNTIME_STATUSES:
            elapsed = max(0.0, self.clock() - float(job["started_at"]))
            target = self._stage_for_elapsed(elapsed)
            if target != job["status"]:
                job["status"] = target
                job["elapsed"] = round(elapsed, 3)
                if target not in job["stages"]:
                    job["stages"].append(target)
        return {
            "job_id": job["id"],
            "adapter": job["adapter"],
            "status": job["status"],
            "elapsed": job["elapsed"],
            "stages": list(job["stages"]),
            "existing_job_status": self.map_status(job["status"]),
            "failure_reason": job["failure_reason"],
            "has_output": job["status"] == "COMPLETED",
        }

    def cancel(self, job_id: str) -> Dict[str, Any]:
        job = self.jobs.get(job_id)
        if job is None:
            raise KeyError(f"runtime job not found: {job_id}")
        if job["status"] in TERMINAL_RUNTIME_STATUSES:
            raise ValueError(f"job {job_id} already terminal ({job['status']}); cannot cancel")
        job["status"] = "CANCELLED"
        job["failure_reason"] = "cancelled by user"
        job["stages"].append("CANCELLED")
        return self.status(job_id)

    def get_output(self, job_id: str) -> Dict[str, Any]:
        snapshot = self.status(job_id)
        if snapshot["status"] != "COMPLETED":
            raise ValueError(
                f"output available only when COMPLETED; job is {snapshot['status']}")
        job = self.jobs[job_id]
        req = job["request"]
        params = req.get("generation_parameters", {})
        prompt = req.get("prompt_payload", {})
        out = VideoGenerationOutput(
            job_id=job_id,
            video_path=f"mock://{job_id}/output.mp4",
            preview_path=f"mock://{job_id}/preview_0.5.png",
            metadata={
                "study_id": req.get("study_id"),
                "workflow_id": req.get("workflow_id"),
                "camera_motion": req.get("camera_motion"),
                "resolution": params.get("resolution", "1344x768"),
                "fps": params.get("fps", 24),
                "duration": params.get("duration", 4.0),
                "quality": params.get("quality", "diagnostic"),
                "seed": params.get("seed"),
                "prompt_hash": prompt.get("prompt_hash"),
            },
            runtime_info={
                "adapter": self.name,
                "gpu_invoked": False,
                "comfyui_invoked": False,
                "native_runtime_invoked": False,
                "mock": True,
            },
        )
        return out.to_dict()

    def _stage_for_elapsed(self, elapsed: float) -> str:
        current = "QUEUED"
        for stage, threshold in self.STAGE_AT.items():
            if elapsed >= threshold:
                current = stage
        return current
