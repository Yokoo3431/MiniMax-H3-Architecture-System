"""Safe identity helpers for reconciling completed Comfy outputs.

This module deliberately handles only execution identity and relative output
metadata. It never stores prompts or absolute filesystem paths.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Mapping


class ResultIdentityError(ValueError):
    """A Comfy result cannot be proven to belong to the requested Job."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def classify_result_failure(code: Any, *, runtime_target: str = "") -> str:
    """Map bounded pipeline codes to the stable forensic classifications."""
    value = str(code or "").upper()
    if value.startswith(("SAVE_VIDEO_NODE_FAILURE", "SAVE_VIDEO_EXECUTION_ERROR")):
        return "SAVE_VIDEO_NODE_FAILURE"
    if value.startswith("SAVE_VIDEO"):
        return "UNKNOWN"
    if value in {"OUTPUT_FILE_CREATED_BUT_NOT_DISCOVERED", "OUTPUT_FILE_MISSING"}:
        return "OUTPUT_FILE_CREATED_BUT_NOT_DISCOVERED"
    if "PROMPT" in value or "HISTORY" in value:
        return "PROMPT_OUTPUT_ASSOCIATION_FAILURE"
    if "IDENTITY" in value or value == "OUTPUT_IDENTITY_AMBIGUOUS":
        if "RUNTIME" in value and runtime_target == "experimental":
            return "EXPERIMENTAL_RUNTIME_OUTPUT_LAYOUT_MISMATCH"
        return "OUTPUT_IDENTITY_MISMATCH"
    if "RUNTIME_OUTPUT_LAYOUT" in value and runtime_target == "experimental":
        return "EXPERIMENTAL_RUNTIME_OUTPUT_LAYOUT_MISMATCH"
    if (value.startswith("MEDIA_PROBE") or value.startswith("FFMPEG")
            or value == "OUTPUT_FILE_EMPTY"):
        return "MEDIA_PROBE_FAILURE"
    if value.startswith("PACKAGING") or value.startswith("OUTPUT_DELIVERY"):
        return "PACKAGING_COPY_FAILURE"
    if value.startswith("RESULT_PERSISTENCE"):
        return "RESULT_PERSISTENCE_FAILURE"
    if value.startswith("HTTP_MEDIA"):
        return "HTTP_SERVING_FAILURE"
    if "PATH" in value or "FILENAME" in value:
        if runtime_target == "experimental" and value.startswith("OUTPUT_PATH"):
            return "EXPERIMENTAL_RUNTIME_OUTPUT_LAYOUT_MISMATCH"
        return "PATH_OR_FILENAME_FAILURE"
    if "RUNTIME_OUTPUT" in value and runtime_target == "experimental":
        return "EXPERIMENTAL_RUNTIME_OUTPUT_LAYOUT_MISMATCH"
    return "UNKNOWN"


def _relative_posix(value: Any, *, field: str) -> str:
    text = str(value or "").replace("\\", "/").strip()
    win = PureWindowsPath(text)
    path = PurePosixPath(text)
    if (not text or "\x00" in text or path.is_absolute() or win.is_absolute()
            or win.drive or any(part in ("", ".", "..") for part in path.parts)):
        raise ResultIdentityError(
            "OUTPUT_PATH_INVALID", f"{field} must be a safe relative path")
    return path.as_posix()


def expected_save_video_identity(
        workflow: Mapping[str, Any], job_id: str,
        workflow_sha256: str | None = None) -> dict[str, Any]:
    """Extract the unique SaveVideo output contract from an API graph."""
    graph = workflow.get("execution_payload") or workflow.get("workflow") or workflow
    if isinstance(graph, Mapping) and isinstance(graph.get("nodes"), Mapping):
        graph = graph["nodes"]
    if not isinstance(graph, Mapping):
        raise ResultIdentityError("SAVE_VIDEO_CONTRACT_MISSING",
                                  "execution graph is unavailable")

    matches: list[tuple[str, Mapping[str, Any]]] = []
    for node_id, node in graph.items():
        if (isinstance(node, Mapping)
                and str(node.get("class_type") or "") in {"SaveVideo", "SaveVideoV2"}):
            matches.append((str(node_id), node))
    if len(matches) != 1:
        raise ResultIdentityError(
            "SAVE_VIDEO_CONTRACT_AMBIGUOUS" if matches else "SAVE_VIDEO_CONTRACT_MISSING",
            "execution graph must contain exactly one SaveVideo output node")

    node_id, node = matches[0]
    inputs = node.get("inputs") or {}
    prefix = _relative_posix(inputs.get("filename_prefix"), field="filename_prefix")
    if job_id and job_id not in PurePosixPath(prefix).name:
        raise ResultIdentityError(
            "OUTPUT_PREFIX_JOB_MISMATCH",
            "SaveVideo filename prefix does not contain the durable Job identity")
    return {
        "node_id": node_id,
        "node_type": str(node.get("class_type")),
        "filename_prefix": prefix,
        "workflow_sha256": str(workflow_sha256 or ""),
    }


def summarize_history_outputs(history: Mapping[str, Any], *, limit: int = 32
                              ) -> list[dict[str, Any]]:
    """Return bounded, path-free output metadata from a Comfy history entry."""
    outputs = history.get("outputs") or {}
    if not isinstance(outputs, Mapping):
        return []
    rows: list[dict[str, Any]] = []
    for node_id, node_output in outputs.items():
        if not isinstance(node_output, Mapping):
            continue
        for field in ("videos", "images", "gifs"):
            entries = node_output.get(field) or []
            if not isinstance(entries, (list, tuple)):
                continue
            for entry in entries:
                if not isinstance(entry, Mapping):
                    continue
                filename = str(entry.get("filename") or "")
                subfolder = str(entry.get("subfolder") or "")
                safe_filename = PureWindowsPath(filename).name
                safe_filename = PurePosixPath(safe_filename.replace("\\", "/")).name
                safe_subfolder = ""
                if subfolder:
                    try:
                        safe_subfolder = _relative_posix(
                            subfolder, field="subfolder")
                    except ResultIdentityError:
                        safe_subfolder = "<INVALID>"
                size = entry.get("size")
                rows.append({
                    "node_id": str(node_id),
                    "field": field,
                    "filename": safe_filename[:240],
                    "subfolder": safe_subfolder[:240],
                    "type": str(entry.get("type") or "")[:32],
                    "format": str(entry.get("format") or "")[:64],
                    "size": int(size) if isinstance(size, (int, float)) and size >= 0 else None,
                })
                if len(rows) >= max(1, int(limit)):
                    return rows
    return rows


def select_history_video(history: Mapping[str, Any], *, prompt_id: str,
                         expected: Mapping[str, Any]) -> dict[str, Any]:
    """Select one video only when Comfy history matches the saved output node."""
    if not str(prompt_id or "").strip():
        raise ResultIdentityError(
            "PROMPT_IDENTITY_MISSING",
            "the exact Comfy prompt identity is required for output association")
    observed_prompt = str(history.get("prompt_id") or "")
    if observed_prompt and observed_prompt != str(prompt_id):
        raise ResultIdentityError(
            "PROMPT_OUTPUT_ASSOCIATION_FAILURE",
            "history prompt identity does not match the Studio Job")

    outputs = history.get("outputs") or {}
    if not isinstance(outputs, Mapping):
        raise ResultIdentityError("HISTORY_OUTPUTS_MISSING",
                                  "completed history has no output map")
    node_id = str(expected.get("node_id") or "")
    node_output = outputs.get(node_id)
    if not isinstance(node_output, Mapping):
        raise ResultIdentityError(
            "PROMPT_OUTPUT_ASSOCIATION_FAILURE",
            "completed history has no output for the Job's SaveVideo node")

    prefix = _relative_posix(expected.get("filename_prefix"),
                             field="filename_prefix")
    prefix_path = PurePosixPath(prefix)
    expected_name = prefix_path.name
    expected_folder = "" if str(prefix_path.parent) == "." else prefix_path.parent.as_posix()
    entries: list[Mapping[str, Any]] = []
    for field in ("videos", "images", "gifs"):
        values = node_output.get(field) or []
        if isinstance(values, (list, tuple)):
            entries.extend(item for item in values if isinstance(item, Mapping))

    videos = []
    for item in entries:
        filename = str(item.get("filename") or "")
        subfolder = str(item.get("subfolder") or "").replace("\\", "/").strip("/")
        safe_name = PureWindowsPath(filename).name
        safe_name = PurePosixPath(safe_name.replace("\\", "/")).name
        output_type = str(item.get("type") or "").lower()
        fmt = str(item.get("format") or "").lower()
        is_video = (safe_name.lower().endswith((".mp4", ".webm", ".mkv", ".mov"))
                    or "video" in fmt or bool(item.get("animated")))
        if output_type == "output" and is_video:
            videos.append((item, safe_name, subfolder))

    matching = []
    for item, filename, subfolder in videos:
        try:
            normalized_folder = _relative_posix(subfolder, field="subfolder") if subfolder else ""
        except ResultIdentityError:
            continue
        if (normalized_folder == expected_folder
                and filename.startswith(expected_name)):
            matching.append(item)

    if not matching:
        code = "OUTPUT_FILE_CREATED_BUT_NOT_DISCOVERED" if videos else "SAVE_VIDEO_OUTPUT_MISSING"
        raise ResultIdentityError(
            code, "completed history has no video matching the Job's SaveVideo prefix")
    if len(matching) != 1:
        raise ResultIdentityError(
            "OUTPUT_IDENTITY_AMBIGUOUS",
            "more than one history video matches the Job's SaveVideo prefix")
    return dict(matching[0])


def sanitize_result_error(message: Any, *, limit: int = 320) -> str:
    """Redact absolute paths and cap runtime messages before persistence."""
    text = str(message or "").replace("\x00", " ")
    # Paths may contain spaces on Windows; redact from the drive/root marker
    # through the line boundary instead of leaking an unparsed suffix.
    text = re.sub(r"(?i)\b[A-Z]:[\\/][^\r\n\"'<>|]*", "<PATH>", text)
    text = re.sub(r"\\\\[^\r\n\"'<>|]*", "<PATH>", text)
    text = re.sub(r"(?<!:)\/[^\r\n\"'<>|]*", "<PATH>", text)
    text = re.sub(r"(?i)\b(bearer\s+)[^\s,;]+", r"\1<REDACTED>", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max(1, int(limit))]


__all__ = [
    "ResultIdentityError", "classify_result_failure", "expected_save_video_identity",
    "sanitize_result_error", "select_history_video",
    "summarize_history_outputs",
]
