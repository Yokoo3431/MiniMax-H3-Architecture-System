"""Managed media probing for the public output contract.

The probe is deliberately metadata-only: it never returns a filesystem path,
raw subprocess output, or media bytes.  Native ``ffprobe`` is preferred when
the selected Runtime exposes it; the same managed Runtime's FFmpeg binary is
the compatibility fallback used by the existing video validation boundary.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any, Optional, Tuple

from runtime.adapters.runtime_paths import RuntimePathContract


_DURATION_RE = re.compile(r"Duration:\s*([0-9:.]+)")
_VIDEO_RE = re.compile(r"Video:\s*([^,\s]+).*?(\d{2,5})x(\d{2,5})")
_FPS_RE = re.compile(r"(\d+(?:\.\d+)?)\s+fps")


def _managed_executable(runtime_paths: Optional[RuntimePathContract]) -> Tuple[str, Path] | None:
    """Return a managed probe executable without consulting arbitrary PATH."""
    if runtime_paths is not None:
        if runtime_paths.ffprobe and runtime_paths.ffprobe.is_file():
            return "ffprobe", runtime_paths.ffprobe
        if runtime_paths.ffmpeg and runtime_paths.ffmpeg.is_file():
            return "ffmpeg", runtime_paths.ffmpeg
    try:
        import imageio_ffmpeg

        executable = Path(imageio_ffmpeg.get_ffmpeg_exe())
        if executable.is_file():
            return "ffmpeg", executable
    except Exception:
        pass
    if runtime_paths is not None and runtime_paths.embedded_python.is_file():
        try:
            completed = subprocess.run(
                [str(runtime_paths.embedded_python), "-c",
                 "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"],
                capture_output=True, text=True, timeout=10.0, check=False,
            )
            if completed.returncode == 0:
                executable = Path(completed.stdout.strip().splitlines()[-1])
                if executable.is_file():
                    return "ffmpeg", executable
        except (IndexError, OSError, subprocess.TimeoutExpired):
            pass
    return None


def _ratio(value: Any) -> Optional[float]:
    if isinstance(value, str) and "/" in value:
        numerator, denominator = value.split("/", 1)
        try:
            denominator_value = float(denominator)
            return round(float(numerator) / denominator_value, 2) if denominator_value else None
        except (TypeError, ValueError):
            return None
    try:
        return round(float(value), 2) if value is not None else None
    except (TypeError, ValueError):
        return None


def _from_ffprobe(payload: dict[str, Any]) -> dict[str, Any]:
    streams = payload.get("streams") if isinstance(payload.get("streams"), list) else []
    video = next((stream for stream in streams
                  if isinstance(stream, dict) and stream.get("codec_type") == "video"), None)
    if not isinstance(video, dict):
        raise ValueError("video stream missing")
    media_format = payload.get("format") if isinstance(payload.get("format"), dict) else {}
    duration = video.get("duration") or media_format.get("duration")
    duration_value = float(duration) if duration is not None else None
    if duration_value is None or duration_value <= 0:
        raise ValueError("duration missing")
    width = int(video.get("width") or 0)
    height = int(video.get("height") or 0)
    fps = _ratio(video.get("avg_frame_rate") or video.get("r_frame_rate"))
    if width <= 0 or height <= 0 or fps is None or fps <= 0:
        raise ValueError("video dimensions or fps missing")
    return {
        "available": True,
        "duration_seconds": round(duration_value, 3),
        "width": width,
        "height": height,
        "fps": fps,
        "video_codec": video.get("codec_name"),
        "audio_stream": any(isinstance(stream, dict) and stream.get("codec_type") == "audio"
                             for stream in streams),
        "probe_tool": "managed_ffprobe",
    }


def _from_ffmpeg_text(text: str) -> dict[str, Any]:
    duration_match = _DURATION_RE.search(text)
    video_match = _VIDEO_RE.search(text)
    fps_match = _FPS_RE.search(text)
    if not duration_match or not video_match or not fps_match:
        raise ValueError("managed FFmpeg metadata incomplete")
    hours, minutes, seconds = duration_match.group(1).split(":")
    duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    fps = float(fps_match.group(1))
    return {
        "available": True,
        "duration_seconds": round(duration, 3),
        "width": int(video_match.group(2)),
        "height": int(video_match.group(3)),
        "fps": round(fps, 2),
        "video_codec": video_match.group(1),
        "audio_stream": "Audio:" in text,
        "probe_tool": "managed_ffmpeg_compatibility",
    }


def probe_media_file(path: Path, *, runtime_paths: Optional[RuntimePathContract] = None,
                     timeout_seconds: float = 20.0) -> dict[str, Any]:
    """Return verified media metadata with a stable, path-free failure shape."""
    result = {"available": False, "error_code": "MEDIA_PROBE_UNAVAILABLE"}
    try:
        media = Path(path)
        if not media.is_file() or media.stat().st_size <= 0:
            result["error_code"] = "MEDIA_MISSING"
            return result
        tool = _managed_executable(runtime_paths)
        if tool is None:
            return result
        name, executable = tool
        if name == "ffprobe":
            completed = subprocess.run(
                [str(executable), "-v", "error", "-print_format", "json",
                 "-show_streams", "-show_format", str(media)],
                capture_output=True, text=True, timeout=timeout_seconds, check=False,
            )
            if completed.returncode != 0:
                result["error_code"] = "MEDIA_PROBE_FAILED"
                return result
            return _from_ffprobe(json.loads(completed.stdout))

        completed = subprocess.run(
            [str(executable), "-hide_banner", "-i", str(media), "-f", "null", "-"],
            capture_output=True, text=True, timeout=timeout_seconds, check=False,
        )
        if completed.returncode != 0:
            result["error_code"] = "MEDIA_PROBE_FAILED"
            return result
        return _from_ffmpeg_text(completed.stderr)
    except subprocess.TimeoutExpired:
        result["error_code"] = "MEDIA_PROBE_TIMEOUT"
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        result["error_code"] = "MEDIA_PROBE_INVALID"
    return result


__all__ = ["probe_media_file"]
