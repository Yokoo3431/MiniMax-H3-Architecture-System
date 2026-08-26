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
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from urllib.parse import urlencode
from typing import Any, Dict, Optional
from pathlib import Path


def _is_timeout_error(exc: BaseException) -> bool:
    """Recognize socket/urllib timeout wrappers without hiding other errors."""
    if isinstance(exc, (TimeoutError,)):
        return True
    reason = getattr(exc, "reason", None)
    return isinstance(reason, TimeoutError) or "timed out" in str(exc).lower()


def _queue_prompt_id(item: Any) -> Optional[str]:
    """Read the prompt id from current ComfyUI queue tuple/object shapes."""
    if isinstance(item, (list, tuple)):
        for value in item:
            if isinstance(value, str) and len(value) >= 8:
                return value
            if isinstance(value, dict):
                found = _queue_prompt_id(value)
                if found:
                    return found
    if isinstance(item, dict):
        for key in ("prompt_id", "promptId", "id"):
            value = item.get(key)
            if value:
                return str(value)
    return None


def _contains_all(value: Any, needles: list[str]) -> bool:
    text = json.dumps(value, ensure_ascii=False, default=str).lower()
    return all(needle.lower() in text for needle in needles)


def _contains_value(value: Any, needle: str) -> bool:
    return needle.lower() in json.dumps(value, ensure_ascii=False, default=str).lower()


class ComfyUIOfflineError(RuntimeError):
    """ComfyUI server unreachable."""


class ComfyUICommunicationTimeout(ComfyUIOfflineError):
    """A bounded metadata/observation request timed out.

    This is deliberately different from ``ComfyUIOfflineError``: the server
    may still be healthy and an accepted prompt may still be running.
    """


class ComfyUISubmissionUnknown(ComfyUICommunicationTimeout):
    """POST /prompt timed out after the server may have accepted the job."""


class ComfyUIExecutionError(RuntimeError):
    """ComfyUI reported a node/execution error."""


class GenerationTimeoutError(RuntimeError):
    """Job did not finish within the configured timeout."""


class WorkflowNotFoundError(RuntimeError):
    """The referenced native workflow asset is missing."""


class ComfyUIClient:
    """Thin HTTP client for the ComfyUI Native runtime (127.0.0.1)."""

    def __init__(self, base_url: str = "http://127.0.0.1:8189",
                 timeout: Optional[float] = None,
                 output_root: Optional[str] = None,
                 *, strict_output: bool = False,
                 ffmpeg_path: Optional[str] = None,
                 health_timeout: float = 5.0,
                 submission_timeout: Optional[float] = None,
                 metadata_timeout: float = 10.0,
                 observation_timeout: float = 15.0,
                 output_timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        # ``timeout=`` remains a compatibility override for existing callers.
        # New code uses an explicit policy per request class.
        legacy_timeout = 30.0 if timeout is None else float(timeout)
        self.timeout = legacy_timeout
        self.health_timeout = float(health_timeout)
        self.submission_timeout = float(
            legacy_timeout if submission_timeout is None else submission_timeout)
        self.metadata_timeout = float(metadata_timeout)
        self.observation_timeout = float(observation_timeout)
        self.output_timeout = float(output_timeout)
        self.output_root = output_root or os.environ.get("H3_COMFY_OUTPUT", "")
        self.strict_output = bool(strict_output)
        self.ffmpeg_path = str(ffmpeg_path) if ffmpeg_path else None

    # ------------------------------------------------------------------ #
    def _request(self, method: str, path: str,
                 payload: Optional[Dict[str, Any]] = None,
                 *, operation: str = "metadata",
                 timeout: Optional[float] = None) -> Any:
        url = f"{self.base_url}{path}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        request_timeout = timeout if timeout is not None else {
            "health": self.health_timeout,
            "submission": self.submission_timeout,
            "observation": self.observation_timeout,
            "output": self.output_timeout,
        }.get(operation, self.metadata_timeout)
        try:
            with urllib.request.urlopen(req, timeout=request_timeout) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise ComfyUIExecutionError(f"ComfyUI HTTP {exc.code}: {body[:500]}") from exc
        except (urllib.error.URLError, ConnectionError, TimeoutError) as exc:
            if _is_timeout_error(exc):
                if method.upper() == "POST" and path == "/prompt":
                    raise ComfyUISubmissionUnknown(
                        f"ComfyUI /prompt acknowledgement timed out after "
                        f"{request_timeout:.0f}s; acceptance is unknown") from exc
                raise ComfyUICommunicationTimeout(
                    f"ComfyUI {operation} request timed out after "
                    f"{request_timeout:.0f}s: {path}") from exc
            raise ComfyUIOfflineError(
                f"ComfyUI offline at {self.base_url}: {exc}") from exc

    # ------------------------------------------------------------------ #
    def health_check(self) -> Dict[str, Any]:
        """GET /system_stats -> runtime availability."""
        stats = self._request("GET", "/system_stats", operation="health")
        system = stats.get("system", {})
        return {
            "available": True,
            "comfyui_version": system.get("comfyui_version"),
            "required_frontend_version": system.get("required_frontend_version"),
            "ram_total": system.get("ram_total"),
            "ram_free": system.get("ram_free"),
        }

    def object_info(self) -> Dict[str, Any]:
        """Return ComfyUI's live node/input registry without submitting work."""
        result = self._request("GET", "/object_info", operation="metadata")
        if not isinstance(result, dict):
            raise ComfyUIExecutionError("ComfyUI /object_info returned a non-object response")
        return result

    def input_file_available(self, filename: str) -> bool:
        """Verify that the active ComfyUI process can read an input file.

        This is deliberately a lightweight read-only check.  It proves the
        same server that will receive ``/prompt`` can resolve the staged
        filename, instead of relying only on the Studio filesystem path.
        """
        query = urlencode({"filename": str(filename), "type": "input"})
        url = f"{self.base_url}/view?{query}"
        try:
            with urllib.request.urlopen(url, timeout=self.metadata_timeout) as resp:
                return int(getattr(resp, "status", 200)) == 200
        except urllib.error.HTTPError as exc:
            if exc.code in (400, 404):
                return False
            body = exc.read().decode("utf-8", errors="replace")
            raise ComfyUIExecutionError(
                f"ComfyUI input verification HTTP {exc.code}: {body[:300]}") from exc
        except (urllib.error.URLError, ConnectionError, TimeoutError) as exc:
            if _is_timeout_error(exc):
                raise ComfyUICommunicationTimeout(
                    f"ComfyUI input verification timed out after "
                    f"{self.metadata_timeout:.0f}s: {filename}") from exc
            raise ComfyUIOfflineError(
                f"ComfyUI offline at {self.base_url}: {exc}") from exc

    def submit_workflow(self, workflow_payload: Dict[str, Any],
                        client_id: Optional[str] = None,
                        *, avs_job_id: Optional[str] = None,
                        execution_workflow_sha256: Optional[str] = None) -> Dict[str, Any]:
        """POST /prompt -> prompt_id (raises ComfyUIExecutionError on node errors)."""
        body = {"prompt": workflow_payload}
        if client_id:
            body["client_id"] = client_id
        correlation = {key: value for key, value in {
            "avs_job_id": avs_job_id,
            "execution_workflow_sha256": execution_workflow_sha256,
        }.items() if value}
        if correlation:
            # ComfyUI preserves extra_data in queue/history on supported
            # versions. It does not alter graph topology or node execution.
            body["extra_data"] = {"architect_video_studio": correlation}
        result = self._request("POST", "/prompt", body, operation="submission")
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
        history = self._request("GET", f"/history/{prompt_id}", operation="observation")
        if prompt_id not in history:
            return {"status": "RUNNING", "prompt_id": prompt_id, "completed": False,
                    "event": {"type": "executing"}}
        entry = history[prompt_id]
        status = entry.get("status", {})
        status_str = status.get("status_str", "unknown")
        completed = bool(status.get("completed"))
        messages = status.get("messages", [])
        errors = []
        for msg in messages:
            if msg and isinstance(msg, list) and msg[0] in ("execution_error", "execution_interrupted"):
                errors.append(msg)
        event = {"type": "execution_success" if status_str == "success" and completed else "executing"}
        progress = status.get("progress")
        if progress is not None:
            event = {"type": "progress", "data": progress if isinstance(progress, dict) else {"progress": progress}}
        if status_str == "success" and completed:
            return {"status": "COMPLETED", "prompt_id": prompt_id, "completed": True, "event": event}
        if status_str == "error" or errors:
            return {"status": "ERROR", "prompt_id": prompt_id,
                    "completed": False, "messages": messages,
                    "event": {"type": "execution_error", "data": {"message": str(messages)}}}
        return {"status": "RUNNING", "prompt_id": prompt_id, "completed": False, "event": event}

    def get_history(self, prompt_id: str) -> Dict[str, Any]:
        """GET /history/<prompt_id> -> full execution result."""
        history = self._request("GET", f"/history/{prompt_id}", operation="output")
        return history.get(prompt_id, {})

    def list_history(self) -> Dict[str, Any]:
        """GET /history -> all execution results (read-only)."""
        return self._request("GET", "/history", operation="metadata")

    def get_queue(self) -> Dict[str, Any]:
        """Return ComfyUI queue metadata for lost-ack reconciliation."""
        result = self._request("GET", "/queue", operation="metadata")
        return result if isinstance(result, dict) else {}

    def reconcile_prompt(self, *, prompt_id: Optional[str] = None,
                         avs_job_id: Optional[str] = None,
                         execution_workflow_sha256: Optional[str] = None,
                         legacy_seed: Optional[int] = None) -> Dict[str, Any]:
        """Find an accepted task without submitting it again.

        Correlation metadata is preferred. ``prompt_id`` is always safe to
        query directly. The seed fallback is intentionally accepted only when
        exactly one candidate matches, preventing accidental duplicate retry.
        """
        wanted = [str(value) for value in (avs_job_id, execution_workflow_sha256)
                  if value]
        queue = self.get_queue()
        queue_seed_candidates = []
        for bucket, status in (("queue_running", "RUNNING"),
                               ("queue_pending", "RUNNING")):
            for item in queue.get(bucket) or []:
                candidate_id = _queue_prompt_id(item)
                if prompt_id and candidate_id == str(prompt_id):
                    return {"status": status, "prompt_id": candidate_id,
                            "source": "queue", "entry": item}
                if candidate_id and wanted and _contains_all(item, wanted):
                    return {"status": status, "prompt_id": candidate_id,
                            "source": "queue", "entry": item}
                if candidate_id and legacy_seed is not None and _contains_value(
                        item, str(legacy_seed)):
                    queue_seed_candidates.append((candidate_id, item, status))
        if not wanted and not prompt_id and len(queue_seed_candidates) == 1:
            candidate_id, item, status = queue_seed_candidates[0]
            return {"status": status, "prompt_id": candidate_id,
                    "source": "queue", "entry": item}

        history = self.list_history()
        candidates = []
        for candidate_id, entry in history.items():
            if prompt_id and str(candidate_id) == str(prompt_id):
                candidates.append((str(candidate_id), entry))
            elif wanted and _contains_all(entry, wanted):
                candidates.append((str(candidate_id), entry))
        if not candidates and legacy_seed is not None:
            seed_matches = [(str(pid), entry) for pid, entry in history.items()
                            if _contains_value(entry, str(legacy_seed))]
            if len(seed_matches) == 1:
                candidates = seed_matches
        if len(candidates) != 1:
            return {"status": "UNKNOWN", "prompt_id": prompt_id,
                    "source": "queue/history", "candidates": len(candidates)}
        candidate_id, entry = candidates[0]
        status = entry.get("status", {}) if isinstance(entry, dict) else {}
        if status.get("status_str") == "success" and status.get("completed"):
            state = "COMPLETED"
        elif status.get("status_str") == "error":
            state = "FAILED"
        else:
            state = "RUNNING"
        return {"status": state, "prompt_id": candidate_id, "source": "history",
                "entry": entry}

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
        if self.strict_output:
            self._validate_real_video(video_path)
        runtime_info = {
            "adapter": "native",
            "gpu_invoked": True,
            "comfyui_invoked": True,
            "native_runtime_invoked": True,
            "prompt_id": history_result.get("prompt_id", ""),
            "output_validation": "PASS" if self.strict_output else "NOT_REQUESTED",
        }
        return {
            "job_id": job_id,
            "video_path": video_path,
            "preview_path": f"{video_path}.preview_frame0.png",
            "metadata": metadata or {},
            "runtime_info": runtime_info,
            "workflow_id": workflow_id,
        }

    def _validate_real_video(self, video_path: str) -> None:
        """Verify the actual output file before a job can become complete."""
        path = Path(video_path)
        if not path.is_file():
            raise ComfyUIExecutionError(f"output video was not written: {path}")
        if path.stat().st_size <= 0:
            raise ComfyUIExecutionError(f"output video is empty: {path}")
        ffmpeg = self.ffmpeg_path or shutil.which("ffmpeg")
        if not ffmpeg:
            try:
                import imageio_ffmpeg
                ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
            except Exception:  # optional fallback; the error below is clearer
                ffmpeg = None
        if not ffmpeg or not Path(ffmpeg).is_file():
            raise ComfyUIExecutionError(
                "ffmpeg is unavailable; cannot validate the generated video")
        try:
            result = subprocess.run(
                [ffmpeg, "-v", "error", "-i", str(path), "-f", "null", "-"],
                capture_output=True, text=True, timeout=30,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ComfyUIExecutionError(
                f"video validation could not run for {path}: {exc}") from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "ffmpeg rejected the file").strip()
            raise ComfyUIExecutionError(
                f"generated video is not decodable: {path}: {detail[:500]}")

    def wait_completion(self, prompt_id: str, timeout_seconds: float = 1500.0,
                        poll_interval: float = 5.0, on_event=None) -> Dict[str, Any]:
        """Poll until COMPLETED/ERROR; raises GenerationTimeoutError."""
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            try:
                state = self.get_status(prompt_id)
            except ComfyUICommunicationTimeout:
                # A transient metadata timeout says nothing about the child
                # service or the accepted job. Keep the job alive and expose
                # a syncing event until the bounded execution deadline.
                if on_event is not None:
                    on_event({"type": "syncing", "message": "生成中 · 正在同步进度"})
                time.sleep(min(poll_interval, max(1.0, deadline - time.time())))
                continue
            if on_event is not None:
                on_event(state.get("event") or {"type": "executing"})
            if state["status"] in ("COMPLETED", "ERROR"):
                return state
            time.sleep(min(poll_interval, max(1.0, deadline - time.time())))
        raise GenerationTimeoutError(
            f"generation timeout after {timeout_seconds:.0f}s for prompt_id {prompt_id}")
