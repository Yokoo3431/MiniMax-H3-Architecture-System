"""Job-bound, resumable CPU video delivery processing for A8.

This module never contacts ComfyUI and never changes the native generation
Result.  Each derivative is tied to one completed Job and source-media SHA,
written inside that Job's package, and published only after metadata checks.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from runtime.media_probe import probe_media_file


PIPELINE_VERSION = "a8-delivery-v2"
TARGETS = {
    "NATIVE": None,
    "ULTRA_1080": (1920, 1080),
    # Preserve the previously frozen A4.1 2048x1152-class contract.
    "ULTRA_2K": (2048, 1152),
}
DELIVERY_FPS = (24, 48, 60)
MIN_FREE_BYTES = 2 * 1024**3
MAX_ARTIFACT_BYTES = 2 * 1024**3
MAX_JOB_DELIVERY_BYTES = 4 * 1024**3
MAX_SOURCE_BYTES = 2 * 1024**3
PROCESS_TIMEOUT_SECONDS = 15 * 60
_SHA256_RE = re.compile(r"^[a-fA-F0-9]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,96}$")


class DeliveryError(ValueError):
    """A path-free, stable error suitable for persistence and API responses."""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message or code)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def resolve_ffmpeg(runtime_paths: Any = None) -> Path | None:
    """Resolve FFmpeg only from the selected managed runtime, never ambient PATH."""
    configured = getattr(runtime_paths, "ffmpeg", None) if runtime_paths else None
    if configured and Path(configured).is_file():
        return Path(configured).resolve()
    python_executable = getattr(runtime_paths, "embedded_python", None) if runtime_paths else None
    if python_executable:
        python_path = Path(python_executable)
        candidates = sorted((python_path.parent / "Lib" / "site-packages"
                             / "imageio_ffmpeg" / "binaries").glob("ffmpeg*.exe"))
        if len(candidates) == 1 and candidates[0].is_file():
            return candidates[0].resolve()
    return None


class DeliveryPipeline:
    """CPU-only delivery pipeline with deterministic IDs and durable checkpoints."""

    def __init__(self, *, store: Any, runtime_paths: Any = None,
                 ffmpeg_executable: Path | str | None = None,
                 probe: Callable[..., dict[str, Any]] | None = None,
                 timeout_seconds: float = PROCESS_TIMEOUT_SECONDS,
                 min_free_bytes: int = MIN_FREE_BYTES,
                 max_artifact_bytes: int = MAX_ARTIFACT_BYTES,
                 max_job_delivery_bytes: int = MAX_JOB_DELIVERY_BYTES) -> None:
        self.store = store
        configured = Path(ffmpeg_executable) if ffmpeg_executable else resolve_ffmpeg(runtime_paths)
        self.ffmpeg = configured.resolve() if configured and configured.is_file() else None
        self.runtime_paths = runtime_paths
        self.probe = probe or probe_media_file
        self.timeout_seconds = float(timeout_seconds)
        self.min_free_bytes = int(min_free_bytes)
        self.max_artifact_bytes = int(max_artifact_bytes)
        self.max_job_delivery_bytes = int(max_job_delivery_bytes)
        self._locks: dict[str, threading.RLock] = {}
        self._locks_guard = threading.Lock()
        self._ffmpeg_version: str | None = None

    @property
    def available(self) -> bool:
        return bool(self.ffmpeg and self.ffmpeg.is_file())

    def _lock_for(self, key: str) -> threading.RLock:
        with self._locks_guard:
            return self._locks.setdefault(key, threading.RLock())

    def _version(self) -> str:
        if not self.available:
            raise DeliveryError("DELIVERY_FFMPEG_UNAVAILABLE")
        if self._ffmpeg_version:
            return self._ffmpeg_version
        try:
            completed = subprocess.run(
                [str(self.ffmpeg), "-version"], capture_output=True, text=True,
                timeout=10, check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise DeliveryError("DELIVERY_FFMPEG_UNAVAILABLE") from exc
        first_line = (completed.stdout or "").splitlines()
        if completed.returncode != 0 or not first_line:
            raise DeliveryError("DELIVERY_FFMPEG_UNAVAILABLE")
        # Only the version signature is persisted; never the executable path.
        self._ffmpeg_version = first_line[0][:160]
        return self._ffmpeg_version

    @staticmethod
    def _identity(job: Mapping[str, Any]) -> dict[str, Any]:
        trace = job.get("execution_trace") or {}
        runtime = trace.get("runtime_identity") or job.get("runtime_identity") or {}
        prompt_id = str(job.get("prompt_id") or trace.get("prompt_id") or "")
        workflow_sha = str(
            job.get("execution_workflow_sha256") or trace.get("workflow_sha256") or "")
        if not prompt_id or not _SHA256_RE.fullmatch(workflow_sha):
            raise DeliveryError("DELIVERY_EXECUTION_IDENTITY_INCOMPLETE")
        runtime_id = str(runtime.get("runtime_id") or "")
        runtime_role = str(runtime.get("runtime_role") or runtime.get("target") or "")
        backend = str(runtime.get("backend") or "")
        version = str(runtime.get("comfyui_version") or runtime.get("version") or "")
        if not runtime_id or runtime_role not in {"production", "experimental"} or not backend or not version:
            raise DeliveryError("DELIVERY_RUNTIME_IDENTITY_INCOMPLETE")
        return {
            "prompt_id": prompt_id,
            "workflow_sha256": workflow_sha.lower(),
            "runtime_identity": {
                "runtime_id": runtime_id,
                "runtime_role": runtime_role,
                "backend": backend,
                "comfyui_version": version,
                "comfyui_git_sha": str(runtime.get("comfyui_git_sha") or "") or None,
                "endpoint_identity": str(runtime.get("endpoint_identity") or "") or None,
                "config_fingerprint": str(runtime.get("config_fingerprint") or "") or None,
                "output_root_fingerprint": str(
                    runtime.get("output_root_fingerprint") or "") or None,
            },
        }

    @staticmethod
    def _probe(path: Path, runtime_paths: Any,
               probe: Callable[..., dict[str, Any]]) -> dict[str, Any]:
        try:
            try:
                value = probe(path, runtime_paths=runtime_paths, timeout_seconds=90.0)
            except TypeError:
                value = probe(path)
        except Exception as exc:  # callers persist a stable code, not raw tool output
            raise DeliveryError("DELIVERY_MEDIA_PROBE_FAILED") from exc
        if not isinstance(value, dict) or value.get("available") is not True:
            raise DeliveryError("DELIVERY_MEDIA_PROBE_FAILED")
        return {key: value.get(key) for key in (
            "available", "duration_seconds", "width", "height", "fps",
            "video_codec", "audio_stream", "frame_count", "container_format",
            "probe_tool") if key in value}

    @staticmethod
    def _source_identity(job: Mapping[str, Any], source: Path,
                         source_sha256: str, source_probe: Mapping[str, Any],
                         execution: Mapping[str, Any]) -> dict[str, Any]:
        params = job.get("generation_parameters") or {}
        trace = job.get("execution_trace") or {}
        native = trace.get("native_generation") or {}
        width = int(native.get("width") or params.get("width") or source_probe["width"])
        height = int(native.get("height") or params.get("height") or source_probe["height"])
        fps = float(native.get("fps") or params.get("fps") or source_probe["fps"])
        if (width != int(source_probe["width"])
                or height != int(source_probe["height"])
                or abs(fps - float(source_probe["fps"])) > 0.05):
            raise DeliveryError("DELIVERY_NATIVE_MEDIA_PROVENANCE_MISMATCH")
        return {
            "job_id": str(job.get("id") or ""),
            "prompt_id": execution["prompt_id"],
            "workflow_sha256": execution["workflow_sha256"],
            "runtime_identity": execution["runtime_identity"],
            "source_filename": source.name[:180],
            "source_sha256": source_sha256,
            "native_generation_resolution": {"width": width, "height": height},
            "native_generation_fps": fps,
            "native_duration_seconds": source_probe.get("duration_seconds"),
            "native_frame_count": source_probe.get("frame_count"),
            "audio_stream": bool(source_probe.get("audio_stream")),
        }

    @staticmethod
    def _delivery_id(identity: Mapping[str, Any], target_resolution: str,
                     target_fps: int, ffmpeg_version: str) -> str:
        payload = {
            "pipeline_version": PIPELINE_VERSION,
            "identity": identity,
            "target_resolution": target_resolution,
            "delivery_fps": target_fps,
            "ffmpeg_version": ffmpeg_version,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return "delivery-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]

    @staticmethod
    def _confined(path: Path, root: Path) -> Path:
        root = root.resolve()
        resolved = path.resolve()
        if not resolved.is_relative_to(root):
            raise DeliveryError("DELIVERY_PATH_OUTSIDE_JOB_PACKAGE")
        return resolved

    def _save(self, path: Path, manifest: dict[str, Any]) -> None:
        manifest["updated_at"] = _now()
        self.store.save_json(path, manifest)

    def _check_resources(self, root: Path, candidate: Path | None = None) -> None:
        usage = shutil.disk_usage(root)
        if usage.free < self.min_free_bytes:
            raise DeliveryError("DELIVERY_INSUFFICIENT_DISK_RESERVE")
        if candidate and candidate.is_file() and candidate.stat().st_size > self.max_artifact_bytes:
            raise DeliveryError("DELIVERY_ARTIFACT_SIZE_LIMIT")
        delivery_root = root
        if root.name.startswith("delivery-") and root.parent.name == "work":
            delivery_root = root.parent.parent
        retained_bytes = 0
        if delivery_root.is_dir():
            for path in delivery_root.rglob("*"):
                if path.is_file() and not path.is_symlink():
                    retained_bytes += path.stat().st_size
                    if retained_bytes > self.max_job_delivery_bytes:
                        raise DeliveryError("DELIVERY_JOB_STORAGE_LIMIT")

    def _run_ffmpeg(self, args: list[str], output: Path, work_dir: Path) -> None:
        """Run bounded CPU FFmpeg; terminate only this child on timeout/cap."""
        if not self.available:
            raise DeliveryError("DELIVERY_FFMPEG_UNAVAILABLE")
        log_path = work_dir / "ffmpeg.stderr.tmp"
        if log_path.exists():
            log_path.unlink()
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        proc = None
        try:
            with log_path.open("wb") as log:
                proc = subprocess.Popen(
                    args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=log, creationflags=creationflags,
                )
                started = time.monotonic()
                while proc.poll() is None:
                    if time.monotonic() - started > self.timeout_seconds:
                        proc.kill()
                        proc.wait(timeout=10)
                        raise DeliveryError("DELIVERY_PROCESS_TIMEOUT")
                    self._check_resources(work_dir)
                    if output.is_file() and output.stat().st_size > self.max_artifact_bytes:
                        proc.kill()
                        proc.wait(timeout=10)
                        raise DeliveryError("DELIVERY_ARTIFACT_SIZE_LIMIT")
                    time.sleep(0.25)
                if proc.returncode != 0:
                    raise DeliveryError("DELIVERY_FFMPEG_STAGE_FAILED")
            if not output.is_file() or output.stat().st_size <= 0:
                raise DeliveryError("DELIVERY_FFMPEG_OUTPUT_MISSING")
            self._check_resources(work_dir, output)
        except DeliveryError:
            if proc is not None and proc.poll() is None:
                proc.kill()
                proc.wait(timeout=10)
            raise
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise DeliveryError("DELIVERY_FFMPEG_STAGE_FAILED") from exc
        finally:
            log_path.unlink(missing_ok=True)

    def _run_interpolation(self, source: Path, pending: Path,
                           target_fps: int, work_dir: Path) -> None:
        filter_spec = (
            f"minterpolate=fps={target_fps}:mi_mode=mci:mc_mode=aobmc:"
            "me_mode=bidir:vsbmc=1"
        )
        args = [str(self.ffmpeg), "-y", "-nostdin", "-hide_banner", "-loglevel", "error",
                "-threads", "2", "-filter_threads", "2", "-hwaccel", "none",
                "-i", str(source), "-map", "0:v:0", "-vf", filter_spec,
                "-fps_mode", "cfr", "-an", "-c:v", "ffv1", "-level", "3",
                "-threads", "2", "-f", "matroska", str(pending)]
        self._run_ffmpeg(args, pending, work_dir)

    def _run_tail_alignment(self, source: Path, pending: Path,
                            pad_frames: int, work_dir: Path) -> None:
        """Preserve the source timeline end with an explicit last-frame hold."""
        if pad_frames <= 0:
            raise DeliveryError("DELIVERY_TIMELINE_ALIGNMENT_INVALID")
        args = [str(self.ffmpeg), "-y", "-nostdin", "-hide_banner", "-loglevel", "error",
                "-threads", "2", "-filter_threads", "2", "-hwaccel", "none",
                "-i", str(source), "-map", "0:v:0", "-vf",
                f"tpad=stop_mode=clone:stop={pad_frames}", "-fps_mode", "cfr",
                "-an", "-c:v", "ffv1", "-level", "3", "-threads", "2",
                "-f", "matroska", str(pending)]
        self._run_ffmpeg(args, pending, work_dir)

    @staticmethod
    def _expected_delivery_frames(source_probe: Mapping[str, Any],
                                  native_fps: int, delivery_fps: int) -> int:
        source_frames = int(source_probe.get("frame_count") or 0)
        if source_frames <= 0 or native_fps <= 0 or delivery_fps <= 0:
            raise DeliveryError("DELIVERY_SOURCE_FRAME_COUNT_UNAVAILABLE")
        # Explicit ceiling covers the complete source duration on the target lattice.
        return int(math.ceil(source_frames * delivery_fps / native_fps - 1e-9))

    def _run_encode(self, video_input: Path, source_audio: Path | None,
                    pending: Path, target: tuple[int, int] | None,
                    work_dir: Path) -> None:
        args = [str(self.ffmpeg), "-y", "-nostdin", "-hide_banner", "-loglevel", "error",
                "-threads", "2", "-filter_threads", "2", "-hwaccel", "none",
                "-i", str(video_input)]
        if source_audio is not None:
            args.extend(["-i", str(source_audio)])
            audio_input = "1"
        else:
            audio_input = "0"
        args.extend(["-map", "0:v:0", "-map", f"{audio_input}:a?"])
        if target is not None:
            width, height = target
            args.extend(["-vf", (
                f"scale={width}:{height}:force_original_aspect_ratio=decrease:flags=lanczos,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1")])
        args.extend(["-fps_mode", "cfr", "-c:v", "libx264", "-preset", "fast",
                     "-crf", "18", "-pix_fmt", "yuv420p", "-threads", "2",
                     "-c:a", "aac", "-b:a", "192k", "-map_metadata", audio_input,
                     "-movflags", "+faststart", str(pending)])
        self._run_ffmpeg(args, pending, work_dir)

    def list_for_job(self, *, job_id: str, package_root: Path) -> list[dict[str, Any]]:
        if not _ID_RE.fullmatch(str(job_id or "")):
            raise DeliveryError("DELIVERY_JOB_ID_INVALID")
        root = self._confined(package_root / "delivery" / "manifests", package_root)
        if not root.is_dir():
            return []
        items = []
        for path in sorted(root.glob("delivery-*.json")):
            try:
                safe_path = self._confined(path, package_root)
                manifest = json.loads(safe_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, DeliveryError):
                continue
            if manifest.get("job_id") == job_id:
                items.append(self.public_manifest(manifest))
        return items

    def manifest_for_job(self, *, job_id: str, package_root: Path,
                         delivery_id: str) -> dict[str, Any]:
        if not _ID_RE.fullmatch(str(job_id or "")):
            raise DeliveryError("DELIVERY_JOB_ID_INVALID")
        if not re.fullmatch(r"delivery-[a-f0-9]{24}", str(delivery_id or "")):
            raise DeliveryError("DELIVERY_ID_INVALID")
        root = self._confined(Path(package_root) / "delivery" / "manifests",
                              Path(package_root))
        path = self._confined(root / f"{delivery_id}.json", Path(package_root))
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise DeliveryError("DELIVERY_NOT_FOUND") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise DeliveryError("DELIVERY_MANIFEST_INVALID") from exc
        if manifest.get("job_id") != job_id or manifest.get("delivery_id") != delivery_id:
            raise DeliveryError("DELIVERY_IDENTITY_MISMATCH")
        return manifest

    @staticmethod
    def public_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
        """Whitelist owner-visible provenance; no private filesystem paths."""
        keys = (
            "delivery_id", "job_id", "status", "created_at", "updated_at",
            "native_generation_resolution", "native_generation_fps",
            "delivery_resolution", "target_resolution", "delivery_fps",
            "expected_delivery_frame_count", "terminal_padding_frames",
            "timeline_alignment_method", "upscale_method", "restoration_method",
            "frame_interpolation_method", "postprocess_applied",
            "source_sha256", "output_sha256", "size_bytes", "duration_seconds",
            "frame_count", "video_codec", "container_format", "audio_stream",
            "probe_tool", "elapsed_seconds", "stage_status", "error_code",
            "runtime_identity", "prompt_id", "workflow_sha256",
            "processing_backend", "gpu_acceleration_used",
        )
        return {key: manifest[key] for key in keys if key in manifest}

    def create(self, *, job: Mapping[str, Any], source: Path, package_root: Path,
               target_resolution: str, delivery_fps: int) -> dict[str, Any]:
        job_id = str(job.get("id") or "")
        if not _ID_RE.fullmatch(job_id):
            raise DeliveryError("DELIVERY_JOB_ID_INVALID")
        if str(job.get("state") or "").upper() != "COMPLETED":
            raise DeliveryError("DELIVERY_SOURCE_JOB_NOT_COMPLETED")
        if str(job.get("runtime") or "") != "native":
            raise DeliveryError("DELIVERY_NATIVE_RESULT_REQUIRED")
        if target_resolution not in TARGETS:
            raise DeliveryError("DELIVERY_RESOLUTION_UNSUPPORTED")
        if isinstance(delivery_fps, bool) or delivery_fps not in DELIVERY_FPS:
            raise DeliveryError("DELIVERY_FPS_UNSUPPORTED")
        if not self.available:
            raise DeliveryError("DELIVERY_FFMPEG_UNAVAILABLE")
        ffmpeg_version = self._version()
        source = Path(source).resolve()
        if not source.is_file() or source.stat().st_size <= 0:
            raise DeliveryError("DELIVERY_SOURCE_MEDIA_MISSING")
        if source.stat().st_size > MAX_SOURCE_BYTES:
            raise DeliveryError("DELIVERY_SOURCE_SIZE_LIMIT")

        source_probe = self._probe(source, self.runtime_paths, self.probe)
        if (int(source_probe.get("width") or 0) <= 0
                or int(source_probe.get("height") or 0) <= 0
                or float(source_probe.get("fps") or 0) <= 0
                or float(source_probe.get("duration_seconds") or 0) <= 0):
            raise DeliveryError("DELIVERY_SOURCE_PROBE_INVALID")
        execution = self._identity(job)
        source_sha = sha256_file(source)
        identity = self._source_identity(job, source, source_sha, source_probe, execution)
        native_fps = int(round(float(source_probe["fps"])))
        if native_fps != 24:
            raise DeliveryError("DELIVERY_NATIVE_FPS_UNSUPPORTED")
        target = TARGETS[target_resolution]
        output_resolution = target or (
            int(source_probe["width"]), int(source_probe["height"]))
        expected_delivery_frames = self._expected_delivery_frames(
            source_probe, native_fps, delivery_fps)
        if (delivery_fps == native_fps and target is None):
            raise DeliveryError("DELIVERY_NO_POSTPROCESS_REQUESTED")

        delivery_id = self._delivery_id(identity, target_resolution, delivery_fps,
                                        ffmpeg_version)
        package_root = Path(package_root).resolve()
        delivery_root = self._confined(package_root / "delivery", package_root)
        manifest_root = self._confined(delivery_root / "manifests", package_root)
        work_root = self._confined(delivery_root / "work" / delivery_id, package_root)
        output_root = self._confined(delivery_root / "outputs", package_root)
        manifest_path = self._confined(
            manifest_root / f"{delivery_id}.json", package_root)
        work_root.mkdir(parents=True, exist_ok=True)
        output_root.mkdir(parents=True, exist_ok=True)
        self._check_resources(work_root)
        final_path = self._confined(output_root / f"{delivery_id}.mp4", package_root)
        pending_interpolation = self._confined(
            work_root / "interpolated.pending.mkv", package_root)
        raw_interpolation = self._confined(
            work_root / "interpolated.raw.pending.mkv", package_root)
        interpolation_path = self._confined(work_root / "interpolated.mkv", package_root)
        pending_final = self._confined(work_root / "delivery.pending.mp4", package_root)

        with self._lock_for(delivery_id):
            existing = None
            if manifest_path.is_file():
                try:
                    existing = json.loads(manifest_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    raise DeliveryError("DELIVERY_MANIFEST_INVALID") from exc
                if (existing.get("job_id") != job_id
                        or existing.get("source_sha256") != source_sha
                        or existing.get("prompt_id") != execution["prompt_id"]
                        or existing.get("workflow_sha256") != execution["workflow_sha256"]
                        or existing.get("runtime_identity") != execution["runtime_identity"]):
                    raise DeliveryError("DELIVERY_IDENTITY_MISMATCH")
                if (existing.get("status") == "READY" and final_path.is_file()
                        and sha256_file(final_path) == existing.get("output_sha256")):
                    return self.public_manifest(existing)

            now = _now()
            if existing is None:
                existing = {
                    "schema_version": 1,
                    "pipeline_version": PIPELINE_VERSION,
                    "delivery_id": delivery_id,
                    "job_id": job_id,
                    "prompt_id": execution["prompt_id"],
                    "workflow_sha256": execution["workflow_sha256"],
                    "runtime_identity": execution["runtime_identity"],
                    "source_filename": source.name[:180],
                    "source_sha256": source_sha,
                    "native_generation_resolution": identity["native_generation_resolution"],
                    "native_generation_fps": native_fps,
                    "native_duration_seconds": source_probe.get("duration_seconds"),
                    "native_frame_count": source_probe.get("frame_count"),
                    "delivery_resolution": {"width": output_resolution[0],
                                            "height": output_resolution[1]},
                    "target_resolution": target_resolution,
                    "delivery_fps": delivery_fps,
                    "expected_delivery_frame_count": expected_delivery_frames,
                    "upscale_method": "ffmpeg_scale_lanczos_pad" if target else None,
                    "restoration_method": "NONE",
                    "frame_interpolation_method": (
                        "ffmpeg_minterpolate_mci" if delivery_fps != native_fps else None),
                    "timeline_alignment_method": None,
                    "terminal_padding_frames": 0,
                    "postprocess_applied": True,
                    "processing_backend": "CPU_FFMPEG",
                    "gpu_acceleration_used": False,
                    "ffmpeg_version": ffmpeg_version,
                    "created_at": now,
                    "stages": {},
                    "status": "PROCESSING",
                }
            existing["status"] = "PROCESSING"
            existing["error_code"] = None
            existing["stage_status"] = dict(existing.get("stage_status") or {})
            existing.setdefault("stages", {})
            if (existing.get("expected_delivery_frame_count") not in
                    (None, expected_delivery_frames)):
                raise DeliveryError("DELIVERY_TIMELINE_IDENTITY_MISMATCH")
            existing["expected_delivery_frame_count"] = expected_delivery_frames
            self._save(manifest_path, existing)

            started = time.monotonic()
            interpolation_needed = delivery_fps != native_fps
            interpolated = None
            if interpolation_needed:
                stage = existing["stages"].setdefault(
                    "frame_interpolation", {"status": "PENDING"})
                if stage.get("status") == "COMPLETED" and interpolation_path.is_file():
                    if sha256_file(interpolation_path) != stage.get("output_sha256"):
                        raise DeliveryError("DELIVERY_CHECKPOINT_IDENTITY_MISMATCH")
                    interpolated = interpolation_path
                elif (stage.get("status") == "VERIFIED_PENDING_PUBLISH"
                      and pending_interpolation.is_file()
                      and sha256_file(pending_interpolation) == stage.get("output_sha256")):
                    os.replace(pending_interpolation, interpolation_path)
                    stage["status"] = "COMPLETED"
                    stage["artifact_retained"] = True
                    alignment = stage.get("timeline_alignment") or {}
                    existing["timeline_alignment_method"] = alignment.get("method")
                    existing["terminal_padding_frames"] = int(
                        alignment.get("frames_added") or 0)
                    self._save(manifest_path, existing)
                    interpolated = interpolation_path
                else:
                    try:
                        raw_valid = (
                            stage.get("raw_status") == "COMPLETED"
                            and raw_interpolation.is_file()
                            and sha256_file(raw_interpolation)
                            == stage.get("raw_output_sha256")
                        )
                        if not raw_valid:
                            pending_interpolation.unlink(missing_ok=True)
                            raw_interpolation.unlink(missing_ok=True)
                            stage.update({"status": "RUNNING", "raw_status": "RUNNING",
                                          "method": "ffmpeg_minterpolate_mci"})
                            existing["stage_status"]["frame_interpolation"] = "RUNNING"
                            self._save(manifest_path, existing)
                            self._run_interpolation(source, raw_interpolation,
                                                    delivery_fps, work_root)
                            raw_probe = self._probe(raw_interpolation,
                                                    self.runtime_paths, self.probe)
                            raw_failures = []
                            if (int(raw_probe.get("width") or 0)
                                    != int(source_probe["width"])
                                    or int(raw_probe.get("height") or 0)
                                    != int(source_probe["height"])):
                                raw_failures.append("resolution_mismatch")
                            if abs(float(raw_probe.get("fps") or 0)
                                   - delivery_fps) > 0.5:
                                raw_failures.append("fps_mismatch")
                            if int(raw_probe.get("frame_count") or 0) <= 0:
                                raw_failures.append("frame_count_unavailable")
                            stage["raw_probe"] = raw_probe
                            if raw_failures:
                                stage["validation_failures"] = raw_failures
                                stage["raw_status"] = "FAILED"
                                self._save(manifest_path, existing)
                                raise DeliveryError(
                                    "DELIVERY_INTERPOLATION_VALIDATION_FAILED")
                            stage.update({
                                "raw_status": "COMPLETED",
                                "raw_output_sha256": sha256_file(raw_interpolation),
                                "raw_size_bytes": raw_interpolation.stat().st_size,
                            })
                            self._save(manifest_path, existing)
                        else:
                            raw_probe = stage["raw_probe"]

                        raw_count = int(raw_probe["frame_count"])
                        if raw_count > expected_delivery_frames:
                            stage["observed_probe"] = raw_probe
                            stage["validation_failures"] = [
                                "frame_count_exceeds_timeline"]
                            self._save(manifest_path, existing)
                            raise DeliveryError(
                                "DELIVERY_INTERPOLATION_FRAME_COUNT_MISMATCH")
                        terminal_padding_frames = expected_delivery_frames - raw_count
                        final_interp_probe = raw_probe
                        if terminal_padding_frames:
                            pending_interpolation.unlink(missing_ok=True)
                            stage["timeline_alignment"] = {
                                "status": "RUNNING",
                                "method": "ffmpeg_tpad_clone_last",
                                "frames_added": terminal_padding_frames,
                            }
                            self._save(manifest_path, existing)
                            self._run_tail_alignment(
                                raw_interpolation, pending_interpolation,
                                terminal_padding_frames, work_root)
                            final_interp_probe = self._probe(
                                pending_interpolation, self.runtime_paths, self.probe)
                        else:
                            pending_interpolation.unlink(missing_ok=True)
                            os.replace(raw_interpolation, pending_interpolation)

                        expected_duration = expected_delivery_frames / delivery_fps
                        validation_failures = []
                        if (int(final_interp_probe.get("width") or 0)
                                != int(source_probe["width"])
                                or int(final_interp_probe.get("height") or 0)
                                != int(source_probe["height"])):
                            validation_failures.append("resolution_mismatch")
                        if abs(float(final_interp_probe.get("fps") or 0)
                               - delivery_fps) > 0.5:
                            validation_failures.append("fps_mismatch")
                        if (int(final_interp_probe.get("frame_count") or 0)
                                != expected_delivery_frames):
                            validation_failures.append("frame_count_mismatch")
                        if abs(float(final_interp_probe.get("duration_seconds") or 0)
                               - expected_duration) > max(0.02, 1.0 / delivery_fps):
                            validation_failures.append("duration_mismatch")
                        stage["observed_probe"] = final_interp_probe
                        stage["validation_failures"] = validation_failures
                        self._save(manifest_path, existing)
                        if validation_failures:
                            raise DeliveryError("DELIVERY_INTERPOLATION_VALIDATION_FAILED")
                        stage.update({
                            "status": "VERIFIED_PENDING_PUBLISH",
                            "output_sha256": sha256_file(pending_interpolation),
                            "size_bytes": pending_interpolation.stat().st_size,
                            "probe": final_interp_probe,
                            "timeline_alignment": {
                                "status": "COMPLETED"
                                if terminal_padding_frames else "NOT_NEEDED",
                                "method": "ffmpeg_tpad_clone_last"
                                if terminal_padding_frames else None,
                                "frames_added": terminal_padding_frames,
                            },
                        })
                        self._save(manifest_path, existing)
                        os.replace(pending_interpolation, interpolation_path)
                        stage["status"] = "COMPLETED"
                        stage["artifact_retained"] = True
                        existing["stage_status"]["frame_interpolation"] = "COMPLETED"
                        existing["timeline_alignment_method"] = (
                            "ffmpeg_tpad_clone_last"
                            if terminal_padding_frames else None)
                        existing["terminal_padding_frames"] = terminal_padding_frames
                        self._save(manifest_path, existing)
                        interpolated = interpolation_path
                    except DeliveryError as exc:
                        pending_interpolation.unlink(missing_ok=True)
                        raw_interpolation.unlink(missing_ok=True)
                        stage.update({"status": "FAILED", "error_code": exc.code})
                        existing["stage_status"]["frame_interpolation"] = "FAILED"
                        existing["status"] = "FAILED"
                        existing["error_code"] = exc.code
                        self._save(manifest_path, existing)
                        raise
            else:
                existing["stage_status"]["frame_interpolation"] = "SKIPPED"

            if target is None:
                existing["stage_status"]["upscale"] = "SKIPPED"
            else:
                existing["stage_status"]["upscale"] = "PENDING"
            existing["stage_status"]["encode"] = "PENDING"
            self._save(manifest_path, existing)

            # Recover a fully encoded pending artifact by SHA instead of
            # re-encoding when a process stopped after writing its checkpoint.
            encode_stage = existing["stages"].setdefault("encode", {"status": "PENDING"})
            pending_valid = (encode_stage.get("status") == "ENCODED"
                             and pending_final.is_file()
                             and sha256_file(pending_final) == encode_stage.get("output_sha256"))
            if not pending_valid:
                if final_path.exists():
                    if (existing.get("output_sha256")
                            and sha256_file(final_path) == existing.get("output_sha256")):
                        pending_valid = True
                    else:
                        raise DeliveryError("DELIVERY_EXISTING_OUTPUT_CONFLICT")
                else:
                    pending_final.unlink(missing_ok=True)
                    encode_stage.update({"status": "RUNNING", "method": "ffmpeg_libx264"})
                    existing["stage_status"]["encode"] = "RUNNING"
                    self._save(manifest_path, existing)
                    try:
                        self._run_encode(interpolated or source,
                                         source if interpolated else None,
                                         pending_final, target, work_root)
                        encode_stage.update({
                            "status": "ENCODED",
                            "output_sha256": sha256_file(pending_final),
                            "size_bytes": pending_final.stat().st_size,
                        })
                        existing["stage_status"]["encode"] = "COMPLETED"
                        self._save(manifest_path, existing)
                        pending_valid = True
                    except DeliveryError as exc:
                        pending_final.unlink(missing_ok=True)
                        encode_stage.update({"status": "FAILED", "error_code": exc.code})
                        existing["stage_status"]["encode"] = "FAILED"
                        existing["status"] = "FAILED"
                        existing["error_code"] = exc.code
                        self._save(manifest_path, existing)
                        raise

            probe_source = final_path if final_path.is_file() else pending_final
            existing["stage_status"]["probe"] = "RUNNING"
            self._save(manifest_path, existing)
            try:
                output_probe = self._probe(probe_source, self.runtime_paths, self.probe)
                if (int(output_probe.get("width") or 0) != output_resolution[0]
                        or int(output_probe.get("height") or 0) != output_resolution[1]
                        or abs(float(output_probe.get("fps") or 0) - delivery_fps) > 0.5
                        or int(output_probe.get("frame_count") or 0)
                           != expected_delivery_frames
                        or abs(float(output_probe.get("duration_seconds") or 0)
                               - float(source_probe["duration_seconds"]))
                           > max(0.08, 2.0 / delivery_fps)
                        or (bool(source_probe.get("audio_stream"))
                            and not bool(output_probe.get("audio_stream")))
                        or str(output_probe.get("video_codec") or "").lower() != "h264"):
                    raise DeliveryError("DELIVERY_OUTPUT_VALIDATION_FAILED")
                existing["stages"]["probe"] = {
                    "status": "COMPLETED", "probe": output_probe,
                }
                existing["stage_status"]["probe"] = "COMPLETED"
                self._save(manifest_path, existing)
                if probe_source == pending_final:
                    os.replace(pending_final, final_path)
                output_sha = sha256_file(final_path)
                output_size = final_path.stat().st_size
                existing.update({
                    "status": "READY",
                    "error_code": None,
                    "output_sha256": output_sha,
                    "size_bytes": output_size,
                    "duration_seconds": output_probe.get("duration_seconds"),
                    "frame_count": output_probe.get("frame_count"),
                    "video_codec": output_probe.get("video_codec"),
                    "container_format": output_probe.get("container_format"),
                    "audio_stream": output_probe.get("audio_stream"),
                    "probe_tool": output_probe.get("probe_tool"),
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                    "stage_status": {
                        **existing["stage_status"],
                        "upscale": "COMPLETED" if target else "SKIPPED",
                        "encode": "COMPLETED",
                        "publish": "COMPLETED",
                    },
                })
                if interpolated and interpolation_path.is_file():
                    interpolation_path.unlink()
                    existing["stages"]["frame_interpolation"]["artifact_retained"] = False
                pending_interpolation.unlink(missing_ok=True)
                pending_final.unlink(missing_ok=True)
                existing["stages"]["encode"]["status"] = "COMPLETED"
                self._save(manifest_path, existing)
            except DeliveryError as exc:
                existing["stage_status"]["probe"] = "FAILED"
                existing["stages"].setdefault("probe", {}).update(
                    {"status": "FAILED", "error_code": exc.code})
                existing["status"] = "FAILED"
                existing["error_code"] = exc.code
                self._save(manifest_path, existing)
                raise
            return self.public_manifest(existing)


__all__ = [
    "DELIVERY_FPS", "PIPELINE_VERSION", "TARGETS", "DeliveryError",
    "DeliveryPipeline", "resolve_ffmpeg", "sha256_file",
]
