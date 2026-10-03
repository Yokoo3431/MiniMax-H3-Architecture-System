"""Bounded CPU assembly for A9 long-form shot results.

Only already completed, strongly identified Studio Results are inputs. This
module never calls ComfyUI, creates Jobs, or submits generation requests.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import struct
import subprocess
import threading
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from runtime.media_probe import probe_media_file


MIN_FREE_BYTES = 2 * 1024**3
MAX_ASSEMBLY_BYTES = 2 * 1024**3
MAX_SOURCE_BYTES = 8 * 1024**3
MAX_TOTAL_DURATION_SECONDS = 600.0
MAX_CONTINUITY_SOURCE_BYTES = 2 * 1024**3
MAX_CONTINUITY_FRAME_BYTES = 20 * 1024**2
MAX_CONTINUITY_FRAME_PIXELS = 16_777_216
ASSEMBLY_TIMEOUT_SECONDS = 15 * 60
CONTINUITY_EXTRACT_TIMEOUT_SECONDS = 180


class LongFormAssemblyError(ValueError):
    """Path-free assembly failure suitable for persisted diagnostics."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class LongFormAssembler:
    def __init__(self, *, ffmpeg_executable: Path | str | None,
                 runtime_paths: Any = None,
                 probe: Callable[..., dict[str, Any]] | None = None,
                 timeout_seconds: float = ASSEMBLY_TIMEOUT_SECONDS,
                 min_free_bytes: int = MIN_FREE_BYTES,
                 max_output_bytes: int = MAX_ASSEMBLY_BYTES) -> None:
        candidate = Path(ffmpeg_executable) if ffmpeg_executable else None
        self.ffmpeg = candidate.resolve() if candidate and candidate.is_file() else None
        self.runtime_paths = runtime_paths
        self.probe = probe or probe_media_file
        self.timeout_seconds = float(timeout_seconds)
        self.min_free_bytes = int(min_free_bytes)
        self.max_output_bytes = int(max_output_bytes)
        self._lock = threading.RLock()
        self._version_signature: str | None = None

    def _version(self) -> str:
        if not self.ffmpeg:
            raise LongFormAssemblyError("LONG_FORM_FFMPEG_UNAVAILABLE")
        if self._version_signature:
            return self._version_signature
        try:
            result = subprocess.run(
                [str(self.ffmpeg), "-version"], capture_output=True, text=True,
                timeout=10, check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise LongFormAssemblyError("LONG_FORM_FFMPEG_UNAVAILABLE") from exc
        signature = (result.stdout or "").splitlines()
        if result.returncode != 0 or not signature:
            raise LongFormAssemblyError("LONG_FORM_FFMPEG_UNAVAILABLE")
        self._version_signature = signature[0][:160]
        return self._version_signature

    def _probe(self, path: Path) -> dict[str, Any]:
        try:
            try:
                result = self.probe(path, runtime_paths=self.runtime_paths,
                                    timeout_seconds=90.0)
            except TypeError:
                result = self.probe(path)
        except Exception as exc:  # never persist raw paths/tool output
            raise LongFormAssemblyError("LONG_FORM_MEDIA_PROBE_FAILED") from exc
        if not isinstance(result, dict) or result.get("available") is not True:
            raise LongFormAssemblyError("LONG_FORM_MEDIA_PROBE_FAILED")
        return {key: result.get(key) for key in (
            "duration_seconds", "width", "height", "fps", "video_codec",
            "audio_stream", "frame_count", "container_format", "probe_tool")}

    def extract_last_frame(self, source: Path, *, frame_count: int,
                           output_path: Path) -> dict[str, Any]:
        """Extract the exact last decoded frame with a bounded single-frame output.

        FFmpeg decodes sequentially and selects the verified final frame index;
        it does not buffer a reversed copy of the clip in memory.
        """
        source = Path(source).resolve()
        try:
            frame_count = int(frame_count)
        except (TypeError, ValueError, OverflowError) as exc:
            raise LongFormAssemblyError("LONG_FORM_FRAME_COUNT_INVALID") from exc
        if not 1 <= frame_count <= 20_000:
            raise LongFormAssemblyError("LONG_FORM_FRAME_COUNT_INVALID")
        if (not source.is_file() or source.stat().st_size <= 0
                or source.stat().st_size > MAX_CONTINUITY_SOURCE_BYTES):
            raise LongFormAssemblyError("LONG_FORM_CONTINUITY_SOURCE_INVALID")
        root = Path(output_path).parent.resolve()
        root.mkdir(parents=True, exist_ok=True)
        target = Path(output_path).resolve()
        if not target.is_relative_to(root) or target == source:
            raise LongFormAssemblyError("LONG_FORM_FRAME_OUTPUT_INVALID")
        partial = root / f".{target.stem}.partial.png"
        if partial.exists():
            try:
                partial.unlink()
            except OSError as exc:
                raise LongFormAssemblyError("LONG_FORM_TEMP_OUTPUT_BUSY") from exc
        if shutil.disk_usage(root).free < self.min_free_bytes:
            raise LongFormAssemblyError("LONG_FORM_INSUFFICIENT_DISK_RESERVE")
        version = self._version()
        command = [
            str(self.ffmpeg), "-hide_banner", "-loglevel", "error", "-nostdin",
            "-y", "-threads", "2", "-i", str(source), "-map", "0:v:0",
            "-vf", f"select=eq(n\\,{frame_count - 1})", "-frames:v", "1",
            "-vsync", "0", str(partial),
        ]
        try:
            try:
                result = subprocess.run(
                    command, stdin=subprocess.DEVNULL, capture_output=True,
                    text=True, timeout=CONTINUITY_EXTRACT_TIMEOUT_SECONDS,
                    check=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except subprocess.TimeoutExpired as exc:
                raise LongFormAssemblyError(
                    "LONG_FORM_FRAME_EXTRACTION_TIMEOUT") from exc
            except OSError as exc:
                raise LongFormAssemblyError(
                    "LONG_FORM_FRAME_EXTRACTION_FAILED") from exc
            if result.returncode != 0 or not partial.is_file():
                raise LongFormAssemblyError("LONG_FORM_FRAME_EXTRACTION_FAILED")
            size = partial.stat().st_size
            if size <= 24 or size > MAX_CONTINUITY_FRAME_BYTES:
                raise LongFormAssemblyError("LONG_FORM_FRAME_SIZE_INVALID")
            with partial.open("rb") as stream:
                header = stream.read(24)
            if header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
                raise LongFormAssemblyError("LONG_FORM_FRAME_IMAGE_INVALID")
            width, height = struct.unpack(">II", header[16:24])
            if (not 1 <= width <= 8192 or not 1 <= height <= 8192
                    or width * height > MAX_CONTINUITY_FRAME_PIXELS):
                raise LongFormAssemblyError("LONG_FORM_FRAME_DIMENSIONS_INVALID")
            digest = self._sha256(partial)
            os.replace(partial, target)
        finally:
            partial.unlink(missing_ok=True)
        return {
            "asset_id": f"frame-{digest[:32]}",
            "content_sha256": digest,
            "width": width,
            "height": height,
            "size_bytes": size,
            "source_frame_idx": frame_count - 1,
            "ffmpeg_version": version,
        }

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    @staticmethod
    def _duration(value: Any) -> float:
        try:
            duration = float(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise LongFormAssemblyError("LONG_FORM_SOURCE_DURATION_INVALID") from exc
        if not 0.1 <= duration <= 900.0:
            raise LongFormAssemblyError("LONG_FORM_SOURCE_DURATION_INVALID")
        return duration

    def _build_command(self, sources: Sequence[Path], probes: Sequence[Mapping[str, Any]],
                       *, width: int, height: int, fps: int,
                       audio_policy: str, partial: Path) -> list[str]:
        args = [str(self.ffmpeg), "-hide_banner", "-loglevel", "error", "-y",
                "-threads", "2"]
        args.extend([part for path in sources for part in ("-i", str(path))])
        durations = [self._duration(item.get("duration_seconds")) for item in probes]
        audio_stream = [bool(item.get("audio_stream")) for item in probes]
        audio_input_index: list[int] = []
        for index, present in enumerate(audio_stream):
            if present:
                audio_input_index.append(index)
            else:
                silent_index = len(sources) + sum(not value for value in audio_stream[:index])
                args.extend(["-f", "lavfi", "-t", f"{durations[index]:.6f}", "-i",
                             "anullsrc=r=48000:cl=stereo"])
                audio_input_index.append(silent_index)
        filters: list[str] = []
        concat_inputs: list[str] = []
        for index, duration in enumerate(durations):
            filters.append(
                f"[{index}:v:0]trim=duration={duration:.6f},setpts=PTS-STARTPTS,"
                f"scale={width}:{height}:force_original_aspect_ratio=decrease:flags=lanczos,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,"
                f"fps={fps}[v{index}]"
            )
            concat_inputs.append(f"[v{index}]")
            if audio_policy == "KEEP_PER_SHOT_CUT":
                audio_index = audio_input_index[index]
                filters.append(
                    f"[{audio_index}:a:0]aresample=48000:async=1:first_pts=0,"
                    f"aformat=sample_fmts=fltp:channel_layouts=stereo,"
                    f"apad,atrim=duration={duration:.6f},asetpts=PTS-STARTPTS[a{index}]"
                )
                concat_inputs.append(f"[a{index}]")
        has_audio = audio_policy == "KEEP_PER_SHOT_CUT"
        filters.append(
            f"{''.join(concat_inputs)}concat=n={len(sources)}:v=1:a={1 if has_audio else 0}"
            f"[vout]{'[aout]' if has_audio else ''}"
        )
        args.extend(["-filter_complex", ";".join(filters), "-map", "[vout]"])
        if has_audio:
            args.extend(["-map", "[aout]"])
        args.extend(["-c:v", "libx264", "-preset", "medium", "-crf", "18",
                     "-pix_fmt", "yuv420p", "-fps_mode", "cfr", "-threads", "2"])
        if has_audio:
            args.extend(["-c:a", "aac", "-b:a", "192k"])
        else:
            args.append("-an")
        args.extend(["-movflags", "+faststart", str(partial)])
        return args

    def assemble(self, sources: Sequence[Path], source_probes: Sequence[Mapping[str, Any]],
                 *, width: int, height: int, fps: int, audio_policy: str,
                 output_path: Path) -> dict[str, Any]:
        if not self.ffmpeg or len(sources) < 3 or len(sources) != len(source_probes):
            raise LongFormAssemblyError("LONG_FORM_ASSEMBLY_INPUT_INVALID")
        if (audio_policy not in {"KEEP_PER_SHOT_CUT", "MUTE"}
                or fps not in {24, 48, 60}
                or width < 64 or height < 64 or width % 2 or height % 2):
            raise LongFormAssemblyError("LONG_FORM_ASSEMBLY_PROFILE_INVALID")
        resolved_sources: list[Path] = []
        source_bytes = 0
        for path in sources:
            resolved = Path(path).resolve()
            if not resolved.is_file() or resolved.stat().st_size <= 0:
                raise LongFormAssemblyError("LONG_FORM_SOURCE_MEDIA_MISSING")
            source_bytes += resolved.stat().st_size
            if source_bytes > MAX_SOURCE_BYTES:
                raise LongFormAssemblyError("LONG_FORM_SOURCE_SIZE_LIMIT")
            resolved_sources.append(resolved)
        if len(set(resolved_sources)) != len(resolved_sources):
            raise LongFormAssemblyError("LONG_FORM_SOURCE_IDENTITY_DUPLICATE")
        output_root = output_path.parent.resolve()
        output_root.mkdir(parents=True, exist_ok=True)
        candidate = output_path.resolve()
        if not candidate.is_relative_to(output_root):
            raise LongFormAssemblyError("LONG_FORM_OUTPUT_PATH_INVALID")
        if candidate in resolved_sources:
            raise LongFormAssemblyError("LONG_FORM_OUTPUT_MUST_BE_DISTINCT")
        durations = [self._duration(item.get("duration_seconds"))
                     for item in source_probes]
        if sum(durations) > MAX_TOTAL_DURATION_SECONDS:
            raise LongFormAssemblyError("LONG_FORM_TOTAL_DURATION_LIMIT")
        partial = output_root / f".{candidate.stem}.partial.mp4"
        if partial.exists():
            try:
                partial.unlink()
            except OSError as exc:
                raise LongFormAssemblyError("LONG_FORM_TEMP_OUTPUT_BUSY") from exc
        if shutil.disk_usage(output_root).free < self.min_free_bytes:
            raise LongFormAssemblyError("LONG_FORM_INSUFFICIENT_DISK_RESERVE")
        version = self._version()
        command = self._build_command(
            resolved_sources, source_probes, width=width, height=height, fps=fps,
            audio_policy=audio_policy, partial=partial)
        try:
            with self._lock:
                try:
                    result = subprocess.run(
                        command, stdin=subprocess.DEVNULL, capture_output=True,
                        text=True, timeout=self.timeout_seconds, check=False,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                except subprocess.TimeoutExpired as exc:
                    raise LongFormAssemblyError(
                        "LONG_FORM_ASSEMBLY_TIMEOUT") from exc
                except OSError as exc:
                    raise LongFormAssemblyError(
                        "LONG_FORM_ASSEMBLY_PROCESS_FAILED") from exc
            if result.returncode != 0 or not partial.is_file():
                raise LongFormAssemblyError("LONG_FORM_ASSEMBLY_FFMPEG_FAILED")
            if partial.stat().st_size <= 0 or partial.stat().st_size > self.max_output_bytes:
                raise LongFormAssemblyError("LONG_FORM_ASSEMBLY_SIZE_LIMIT")
            probed = self._probe(partial)
            if (int(probed.get("width") or 0) != width
                    or int(probed.get("height") or 0) != height
                    or abs(float(probed.get("fps") or 0) - fps) > 0.2
                    or (audio_policy == "KEEP_PER_SHOT_CUT"
                        and not probed.get("audio_stream"))
                    or (audio_policy == "MUTE" and probed.get("audio_stream"))):
                raise LongFormAssemblyError(
                    "LONG_FORM_ASSEMBLY_OUTPUT_CONTRACT_FAILED")
            os.replace(partial, candidate)
        finally:
            # Probing, replacement, and unexpected filesystem failures must
            # not leave orphaned partial media consuming the user's disk.
            partial.unlink(missing_ok=True)
        return {
            "status": "READY",
            "ffmpeg_version": version,
            "output_sha256": self._sha256(candidate),
            "size_bytes": candidate.stat().st_size,
            "media": probed,
        }
