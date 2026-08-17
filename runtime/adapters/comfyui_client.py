"""ComfyUI HTTP client boundary (RC3.4 PATCH2.7-C2-A).

Responsible ONLY for ComfyUI HTTP communication:
    health_check / submit_workflow / get_status / get_history / collect_output

No GPU / CUDA / model code. Uses stdlib urllib (zero new dependencies).
The client is the ONLY place that talks to ComfyUI; the adapter never exposes
ComfyUI API shapes to the product layer.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional


class ComfyUIOfflineError(RuntimeError):
    """ComfyUI server unreachable."""


class ComfyUIExecutionError(RuntimeError):
    """ComfyUI reported a node/execution error."""


class GenerationTimeoutError(RuntimeError):
    """Job did not finish within the configured timeout."""


class WorkflowNotFoundError(RuntimeError):
    """The referenced native workflow asset is missing."""


class ComfyUIClient:
    """Thin HTTP client for the ComfyUI Native runtime (127.0.0.1)."""

    def __init__(self, base_url: str = "http://127.0.0.1:8189",
                 timeout: float = 30.0,
                 output_root: Optional[str] = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.output_root = output_root or os.environ.get(
            "H3_COMFY_OUTPUT", "<NATIVE_ROOT>/ComfyUI/output")

    # ------------------------------------------------------------------ #
    def _request(self, method: str, path: str,
                 payload: Optional[Dict[str, Any]] = None) -> Any:
        url = f"{self.base_url}{path}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise ComfyUIExecutionError(f"ComfyUI HTTP {exc.code}: {body[:500]}") from exc
        except (urllib.error.URLError, ConnectionError, TimeoutError) as exc:
            raise ComfyUIOfflineError(
                f"ComfyUI offline at {self.base_url}: {exc}") from exc

    # ------------------------------------------------------------------ #
    def health_check(self) -> Dict[str, Any]:
        """GET /system_stats -> runtime availability."""
        stats = self._request("GET", "/system_stats")
        system = stats.get("system", {})
        return {
            "available": True,
            "comfyui_version": system.get("comfyui_version"),
            "required_frontend_version": system.get("required_frontend_version"),
            "ram_total": system.get("ram_total"),
            "ram_free": system.get("ram_free"),
        }

    def submit_workflow(self, workflow_payload: Dict[str, Any],
                        client_id: Optional[str] = None) -> Dict[str, Any]:
        """POST /prompt -> prompt_id (raises ComfyUIExecutionError on node errors)."""
        body = {"prompt": workflow_payload}
        if client_id:
            body["client_id"] = client_id
        result = self._request("POST", "/prompt", body)
        node_errors = result.get("node_errors") or {}
        if node_errors:
            raise ComfyUIExecutionError(
                "ComfyUI node errors on submit: " + json.dumps(node_errors, ensure_ascii=False))
        prompt_id = result.get("prompt_id")
        if not prompt_id:
            raise ComfyUIExecutionError(f"no prompt_id in /prompt response: {result}")
        return {"prompt_id": prompt_id, "number": result.get("number")}

    def get_status(self, prompt_id: str) -> Dict[str, Any]:
        """GET /history/<prompt_id> -> runtime status (RUNNING/COMPLETED/ERROR)."""
        history = self._request("GET", f"/history/{prompt_id}")
        if prompt_id not in history:
            return {"status": "RUNNING", "prompt_id": prompt_id, "completed": False}
        entry = history[prompt_id]
        status = entry.get("status", {})
        status_str = status.get("status_str", "unknown")
        completed = bool(status.get("completed"))
        messages = status.get("messages", [])
        errors = []
        for msg in messages:
            if msg and isinstance(msg, list) and msg[0] in ("execution_error", "execution_interrupted"):
                errors.append(msg)
        if status_str == "success" and completed:
            return {"status": "COMPLETED", "prompt_id": prompt_id, "completed": True}
        if status_str == "error" or errors:
            return {"status": "ERROR", "prompt_id": prompt_id,
                    "completed": False, "messages": messages}
        return {"status": "RUNNING", "prompt_id": prompt_id, "completed": False}

    def get_history(self, prompt_id: str) -> Dict[str, Any]:
        """GET /history/<prompt_id> -> full execution result."""
        history = self._request("GET", f"/history/{prompt_id}")
        return history.get(prompt_id, {})

    def list_history(self) -> Dict[str, Any]:
        """GET /history -> all execution results (read-only)."""
        return self._request("GET", "/history")

    def collect_output(self, history_result: Dict[str, Any],
                       job_id: str, workflow_id: str,
                       metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """history result -> VideoGenerationOutput contract dict."""
        outputs = history_result.get("outputs") or {}
        video_info = None
        for node_out in outputs.values():
            entries = (node_out.get("videos") or []) + (node_out.get("images") or [])
            for v in entries:
                name = str(v.get("filename", "")).lower()
                is_animated = bool(v.get("animated"))
                if (name.endswith(".mp4") or v.get("format") in ("mp4", "video")
                        or is_animated) and v.get("type") == "output":
                    video_info = v
                    break
            if video_info:
                break
        if video_info is None:
            raise ComfyUIExecutionError(
                f"no video output found in history outputs: {json.dumps(outputs, ensure_ascii=False)[:500]}")

        subfolder = video_info.get("subfolder", "")
        filename = video_info.get("filename", "output.mp4")
        rel = f"{subfolder}/{filename}".lstrip("/")
        video_path = f"{self.output_root.rstrip('/')}/{rel}".replace("\\", "/")
        runtime_info = {
            "adapter": "native",
            "gpu_invoked": True,
            "comfyui_invoked": True,
            "native_runtime_invoked": True,
            "prompt_id": history_result.get("prompt_id", ""),
        }
        return {
            "job_id": job_id,
            "video_path": video_path,
            "preview_path": f"{video_path}.preview_frame0.png",
            "metadata": metadata or {},
            "runtime_info": runtime_info,
            "workflow_id": workflow_id,
        }

    def wait_completion(self, prompt_id: str, timeout_seconds: float = 1500.0,
                        poll_interval: float = 5.0) -> Dict[str, Any]:
        """Poll until COMPLETED/ERROR; raises GenerationTimeoutError."""
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            state = self.get_status(prompt_id)
            if state["status"] in ("COMPLETED", "ERROR"):
                return state
            time.sleep(min(poll_interval, max(1.0, deadline - time.time())))
        raise GenerationTimeoutError(
            f"generation timeout after {timeout_seconds:.0f}s for prompt_id {prompt_id}")
