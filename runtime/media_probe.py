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
_FRAME_COUNT_RE = re.compile(r"\bframe=\s*(\d+)")

_PYAV_PROBE_SCRIPT = r"""
import json
import sys

try:
    import av
    with av.open(sys.argv[1], mode="r") as container:
        video = next((stream for stream in container.streams
                      if stream.type == "video"), None)
        if video is None:
            raise ValueError("video stream missing")
        rate = float(video.average_rate) if video.average_rate else None
        duration = (float(container.duration / av.time_base)
                    if container.duration else None)
        if duration is None and video.duration and video.time_base:
            duration = float(video.duration * video.time_base)
        frame_count = sum(1 for _ in container.decode(video))
        print(json.dumps({
            "container_format": str(container.format.name or ""),
            "video_codec": str(video.codec_context.name or ""),
            "width": int(video.codec_context.width or 0),
            "height": int(video.codec_context.height or 0),
            "fps": rate,
            "duration_seconds": duration,
            "frame_count": frame_count,
            "audio_stream": any(stream.type == "audio"
                                 for stream in container.streams),
        }, separators=(",", ":")))
except Exception:
    sys.exit(2)
"""


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
        # probe_media_file requests -count_frames, so nb_read_frames is the
        # decoded stream count, unlike container-level nb_frames metadata.
        "frame_count": int(video["nb_read_frames"])
        if str(video.get("nb_read_frames") or "").isdigit() else None,
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
    frame_matches = _FRAME_COUNT_RE.findall(text)
    return {
        "available": True,
        "duration_seconds": round(duration, 3),
        "width": int(video_match.group(2)),
        "height": int(video_match.group(3)),
        "fps": round(fps, 2),
        "video_codec": video_match.group(1),
        "audio_stream": "Audio:" in text,
        "frame_count": int(frame_matches[-1]) if frame_matches else None,
        "probe_tool": "managed_ffmpeg_decode_count_fallback"
        if frame_matches else "managed_ffmpeg_compatibility",
    }


def _probe_with_runtime_python(media: Path, python_executable: Path,
                               timeout_seconds: float) -> dict[str, Any]:
    """Use the selected isolated runtime's PyAV, never ambient PATH tools."""
    result = {"available": False, "error_code": "MEDIA_PROBE_UNAVAILABLE"}
    try:
        completed = subprocess.run(
            [str(python_executable), "-I", "-c", _PYAV_PROBE_SCRIPT, str(media)],
            capture_output=True, text=True, timeout=timeout_seconds, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        result["error_code"] = "MEDIA_PROBE_TIMEOUT"
        return result
    except OSError:
        return result
    if completed.returncode != 0:
        result["error_code"] = "MEDIA_PROBE_FAILED"
        return result
    try:
        payload = json.loads(completed.stdout)
        width = int(payload.get("width") or 0)
        height = int(payload.get("height") or 0)
        fps = float(payload.get("fps") or 0)
        duration = float(payload.get("duration_seconds") or 0)
        frame_count = int(payload.get("frame_count") or 0)
        if (width <= 0 or height <= 0 or fps <= 0 or duration <= 0
                or frame_count <= 0):
            raise ValueError("incomplete video metadata")
        return {
            "available": True,
            "duration_seconds": round(duration, 3),
            "width": width,
            "height": height,
            "fps": round(fps, 2),
            "video_codec": str(payload.get("video_codec") or "")[:32],
            "audio_stream": bool(payload.get("audio_stream")),
            "frame_count": frame_count,
            "container_format": str(payload.get("container_format") or "")[:64],
            "probe_tool": "pinned_runtime_pyav",
        }
    except (json.JSONDecodeError, TypeError, ValueError):
        result["error_code"] = "MEDIA_PROBE_INVALID"
        return result


def probe_media_file(path: Path, *, runtime_paths: Optional[RuntimePathContract] = None,
                     python_executable: Optional[Path | str] = None,
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
            if python_executable is not None:
                executable = Path(python_executable).expanduser()
                if executable.is_file():
                    return _probe_with_runtime_python(
                        media, executable, timeout_seconds)
            return result
        name, executable = tool
        if name == "ffprobe":
            completed = subprocess.run(
                [str(executable), "-v", "error", "-count_frames", "-print_format", "json",
                 "-show_streams", "-show_format", str(media)],
                capture_output=True, text=True, timeout=timeout_seconds, check=False,
            )
            if completed.returncode != 0:
                result["error_code"] = "MEDIA_PROBE_FAILED"
            else:
                return _from_ffprobe(json.loads(completed.stdout))
        else:
            completed = subprocess.run(
                [str(executable), "-hide_banner", "-progress", "pipe:1", "-nostats",
                 "-i", str(media), "-map", "0:v:0", "-fps_mode", "passthrough",
                 "-f", "null", "-"],
                capture_output=True, text=True, timeout=timeout_seconds, check=False,
            )
            if completed.returncode != 0:
                result["error_code"] = "MEDIA_PROBE_FAILED"
            else:
                # FFmpeg's progress channel reports decoded/output frame
                # counts; stderr continues to provide stream metadata. Only
                # promote a count after FFmpeg's explicit terminal marker.
                value = _from_ffmpeg_text(completed.stderr)
                progress_lines = (completed.stdout or "").splitlines()
                frame_matches = _FRAME_COUNT_RE.findall(completed.stdout or "")
                completed_progress = any(
                    line.strip() == "progress=end" for line in progress_lines)
                if completed_progress and frame_matches:
                    value["frame_count"] = int(frame_matches[-1])
                    value["probe_tool"] = "managed_ffmpeg_decode_count_fallback"
                else:
                    value["frame_count"] = None
                    value["probe_tool"] = "managed_ffmpeg_compatibility"
                return value
    except subprocess.TimeoutExpired:
        result["error_code"] = "MEDIA_PROBE_TIMEOUT"
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        result["error_code"] = "MEDIA_PROBE_INVALID"
    if python_executable is not None:
        executable = Path(python_executable).expanduser()
        if executable.is_file():
            return _probe_with_runtime_python(media, executable, timeout_seconds)
    return result


__all__ = ["probe_media_file"]
