"""Persistent A9 shot-queue API; it never submits a Comfy prompt."""

from __future__ import annotations

import copy
import hashlib
import threading
from pathlib import Path
from typing import Any, Mapping

from runtime.a8_delivery import sha256_file
from runtime.long_form import (
    LongFormError, build_assembly_manifest, canonical_json,
    compile_continuity_binding, create_shot_queue, reconcile_shot_queue,
    resume_plan, stable_sha256,
)
from runtime.long_form_assembly import LongFormAssemblyError, LongFormAssembler
from runtime.a8_delivery import resolve_ffmpeg


class LongFormAPI:
    """Study-owned queue snapshots layered over immutable Director shots."""

    def __init__(self, store, *, output_api) -> None:
        self.store = store
        self.output_api = output_api
        self.assembler = LongFormAssembler(
            ffmpeg_executable=resolve_ffmpeg(getattr(output_api, "runtime_paths", None)),
            runtime_paths=getattr(output_api, "runtime_paths", None))
        self._lock = threading.RLock()

    def _queue_path(self, project_id: str, queue_id: str) -> Path:
        if not queue_id or any(char not in
                               "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
                               for char in queue_id):
            raise LongFormError("LONG_FORM_QUEUE_ID_INVALID")
        root = (self.store.project_dir(project_id) / "long_form" / "queues").resolve()
        path = (root / f"{queue_id}.json").resolve()
        if not path.is_relative_to(root):
            raise LongFormError("LONG_FORM_QUEUE_ID_INVALID")
        return path

    def create(self, project_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock:
            self.store.load_project(project_id)
            sequence = self.store.load_json(
                self.store.project_dir(project_id) / "director.json")
            if not isinstance(sequence, Mapping):
                raise LongFormError("DIRECTOR_SEQUENCE_NOT_FOUND")
            shot_ids = payload.get("shot_ids")
            modes = payload.get("continuity_modes") or {}
            identity = payload.get("project_identity_bindings") or []
            stable_request = {
                "project_id": project_id,
                "sequence_id": sequence.get("sequence_id"),
                "sequence_revision": sequence.get("revision"),
                "shot_ids": list(shot_ids) if shot_ids is not None else [
                    item.get("shot_id") for item in sequence.get("shots", [])],
                "continuity_modes": modes,
                "project_identity_bindings": identity,
                "target_resolution": payload.get("target_resolution"),
                "target_fps": payload.get("target_fps", 24),
                "audio_policy": payload.get("audio_policy", "KEEP_PER_SHOT_CUT"),
                "transition_policy": payload.get("transition_policy", "CUT"),
            }
            request_sha = hashlib.sha256(canonical_json(stable_request).encode("utf-8")).hexdigest()
            queue_id = str(payload.get("queue_id") or f"longform-{request_sha[:16]}")
            path = self._queue_path(project_id, queue_id)
            existing = self.store.load_json(path)
            if existing is not None:
                if existing.get("request_sha256") != request_sha:
                    raise LongFormError("LONG_FORM_QUEUE_ID_CONFLICT")
                return self.get(project_id, queue_id)
            queue = create_shot_queue(
                project_id=project_id, director_sequence=sequence,
                shot_ids=shot_ids,
                continuity_modes=modes,
                project_identity_bindings=identity,
                target_resolution=payload.get("target_resolution"),
                target_fps=payload.get("target_fps", 24),
                audio_policy=str(payload.get("audio_policy", "KEEP_PER_SHOT_CUT")),
                transition_policy=str(payload.get("transition_policy", "CUT")),
                queue_id=queue_id)
            queue["request_sha256"] = request_sha
            queue = self._reconcile(queue, project_id)
            self.store.save_json(path, queue)
            return copy.deepcopy(queue)

    def list(self, project_id: str) -> dict[str, Any]:
        self.store.load_project(project_id)
        root = self.store.project_dir(project_id) / "long_form" / "queues"
        queues = []
        if root.is_dir():
            for path in sorted(root.glob("*.json")):
                value = self.store.load_json(path)
                if isinstance(value, dict) and value.get("project_id") == project_id:
                    queues.append(self.get(project_id, str(value.get("queue_id") or "")))
        return {"project_id": project_id, "queues": queues}

    def get(self, project_id: str, queue_id: str) -> dict[str, Any]:
        with self._lock:
            self.store.load_project(project_id)
            path = self._queue_path(project_id, queue_id)
            queue = self.store.load_json(path)
            if not isinstance(queue, dict):
                raise KeyError("long-form queue not found")
            if str(queue.get("project_id") or "") != project_id:
                raise LongFormError("LONG_FORM_CROSS_PROJECT_QUEUE")
            reconciled = self._reconcile(queue, project_id)
            if reconciled != queue:
                self.store.save_json(path, reconciled)
            return copy.deepcopy(reconciled)

    def resume(self, project_id: str, queue_id: str) -> dict[str, Any]:
        """Return a no-side-effect resume decision; callers explicitly submit Jobs."""
        queue = self.get(project_id, queue_id)
        return {"queue": queue, "resume": resume_plan(queue),
                "submission_performed": False}

    def prepare_for_job(self, project_id: str, queue_id: str,
                        shot_id: str) -> dict[str, Any]:
        """Resolve the selected queue shot's explicit continuity inputs.

        This method may derive one bounded PNG from a completed predecessor,
        but never creates a Job or submits generation. The returned reference
        is internal to JobAPI; public queue responses contain only hashes and
        product identities.
        """
        with self._lock:
            queue = self.get(project_id, queue_id)
            sequence = self.store.load_json(
                self.store.project_dir(project_id) / "director.json")
            if (not isinstance(sequence, Mapping)
                    or str(sequence.get("project_id") or "") != project_id
                    or str(sequence.get("sequence_id") or "")
                    != str(queue.get("director_sequence_id") or "")):
                raise LongFormError("LONG_FORM_DIRECTOR_SEQUENCE_STALE")
            shots = list(queue.get("shots") or [])
            ordinal = next((index for index, item in enumerate(shots)
                            if str(item.get("shot_id") or "") == shot_id), -1)
            if ordinal < 0:
                raise LongFormError("LONG_FORM_SHOT_NOT_FOUND")
            shot = shots[ordinal]
            if shot.get("state") != "PENDING" or shot.get("job_id"):
                raise LongFormError("LONG_FORM_SHOT_NOT_SUBMITTABLE")
            next_step = resume_plan(queue)
            if (next_step.get("action") != "GENERATE_NEXT_SHOT"
                    or str(next_step.get("shot_id") or "") != shot_id):
                raise LongFormError("LONG_FORM_SHOT_NOT_NEXT_IN_SEQUENCE")
            current_shot = next((item for item in sequence.get("shots") or []
                                 if str(item.get("shot_id") or "") == shot_id), None)
            current_shot_sha = stable_sha256({
                key: value for key, value in (current_shot or {}).items()
                if key not in {"last_job_id", "compiled_fragment"}
            })
            if (current_shot is None
                    or current_shot_sha != shot.get("director_shot_sha256")):
                raise LongFormError("LONG_FORM_DIRECTOR_SHOT_STALE")
            modes = list(shot.get("continuity_modes") or [])
            if "CONTINUE_VISUALLY" in modes and "LOCK_PROJECT_IDENTITY" in modes:
                raise LongFormError("LONG_FORM_CONTINUITY_COMBINATION_UNSUPPORTED")

            refs = self.store.load_references(project_id)
            for binding in (queue.get("continuity_identity_bindings") or []):
                asset_id = str(binding.get("asset_id") or "")
                ref = refs.get(asset_id) or {}
                if (ref.get("state") != "APPROVED"
                        or ref.get("role") != binding.get("role")
                        or str(ref.get("sha256") or "").lower()
                        != str(binding.get("content_sha256") or "").lower()):
                    raise LongFormError("LONG_FORM_PROJECT_IDENTITY_BINDING_STALE")

            predecessor_identity = None
            derived_reference = None
            if "CONTINUE_VISUALLY" in modes:
                if ordinal == 0:
                    raise LongFormError("LONG_FORM_FIRST_SHOT_CANNOT_CONTINUE")
                previous = shots[ordinal - 1]
                if str(previous.get("state") or "") not in {"RESULT_READY", "READY"}:
                    raise LongFormError("LONG_FORM_PREVIOUS_SHOT_NOT_READY")
                predecessor_job_id = str(previous.get("job_id") or "")
                jobs = self.store.load_jobs(project_id)
                predecessor_job = jobs.get(predecessor_job_id) or {}
                expected_job = previous.get("job_identity") or {}
                runtime = ((predecessor_job.get("execution_trace") or {}).get(
                    "runtime_identity") or predecessor_job.get("runtime_identity") or {})
                actual_job_identity = {
                    "job_id": predecessor_job_id,
                    "prompt_id": str(predecessor_job.get("prompt_id") or ""),
                    "workflow_sha256": str(
                        predecessor_job.get("execution_workflow_sha256")
                        or (predecessor_job.get("execution_trace") or {}).get(
                            "workflow_sha256") or "").lower(),
                    "runtime_id": str(runtime.get("runtime_id")
                                      or predecessor_job.get("runtime_id") or ""),
                }
                if (predecessor_job.get("state") != "COMPLETED"
                        or actual_job_identity != expected_job):
                    raise LongFormError("LONG_FORM_PREVIOUS_JOB_IDENTITY_CHANGED")
                result = self.output_api.get_result(predecessor_job_id)
                probe = result.get("ffprobe") or {}
                result_identity = previous.get("result_identity") or {}
                if ((result.get("output") or {}).get("available") is not True
                        or probe.get("available") is not True):
                    raise LongFormError("LONG_FORM_PREVIOUS_RESULT_NOT_PROBED")
                try:
                    frame_count = int(probe.get("frame_count"))
                except (TypeError, ValueError, OverflowError) as exc:
                    raise LongFormError(
                        "LONG_FORM_PREVIOUS_FRAME_COUNT_UNAVAILABLE") from exc
                if frame_count <= 0:
                    raise LongFormError("LONG_FORM_PREVIOUS_FRAME_COUNT_UNAVAILABLE")
                media = self.output_api.media_path(predecessor_job_id).resolve()
                media_sha = sha256_file(media)
                if media_sha != str(result_identity.get("media_sha256") or "").lower():
                    raise LongFormError("LONG_FORM_PREVIOUS_MEDIA_IDENTITY_CHANGED")
                result_id = str(result_identity.get("result_id") or "")
                if not result_id:
                    raise LongFormError("LONG_FORM_PREVIOUS_RESULT_IDENTITY_INCOMPLETE")
                extraction_version = "ffmpeg-select-last-decoded-v1"
                frame_key = hashlib.sha256(canonical_json({
                    "project_id": project_id,
                    "source_job_id": predecessor_job_id,
                    "source_result_id": result_id,
                    "source_media_sha256": media_sha,
                    "source_frame_idx": frame_count - 1,
                    "extractor": extraction_version,
                }).encode("utf-8")).hexdigest()[:32]
                frame_path = self.store.input_dir(project_id) / (
                    f"continuity_{frame_key}.png")
                if frame_path.is_file():
                    frame_sha = sha256_file(frame_path)
                    frame_info = {
                        "asset_id": f"frame-{frame_sha[:32]}",
                        "content_sha256": frame_sha,
                        "source_frame_idx": frame_count - 1,
                    }
                else:
                    frame_info = self.assembler.extract_last_frame(
                        media, frame_count=frame_count, output_path=frame_path)
                if (not frame_path.is_file()
                        or sha256_file(frame_path)
                        != str(frame_info.get("content_sha256") or "").lower()):
                    raise LongFormError("LONG_FORM_DERIVED_FRAME_IDENTITY_INVALID")
                asset_id = str(frame_info.get("asset_id") or "")
                existing_ref = refs.get(asset_id)
                if existing_ref and (
                        str(existing_ref.get("sha256") or "").lower()
                        != str(frame_info["content_sha256"]).lower()
                        or Path(str(existing_ref.get("stored_path") or "")).resolve()
                        != frame_path.resolve()):
                    raise LongFormError("LONG_FORM_DERIVED_FRAME_ID_CONFLICT")
                if not existing_ref:
                    refs[asset_id] = {
                        "id": asset_id,
                        "project_id": project_id,
                        "filename": frame_path.name,
                        "stored_path": str(frame_path),
                        "role": "first_frame",
                        "media_type": "image",
                        "source_identity": f"sha256:{frame_info['content_sha256']}",
                        "state": "APPROVED",
                        "sha256": str(frame_info["content_sha256"]).upper(),
                        "version": 1,
                        "created_at": self.store.timestamp(),
                        "approved_at": self.store.timestamp(),
                        "approval_basis": "USER_SELECTED_CONTINUE_VISUALLY",
                        "derived_from": {
                            "job_id": predecessor_job_id,
                            "result_id": result_id,
                            "media_sha256": media_sha,
                            "frame_selector": "LAST_DECODED_FRAME",
                            "frame_idx": frame_count - 1,
                            "extractor": extraction_version,
                        },
                    }
                    self.store.save_references(project_id, refs)
                derived_reference = refs[asset_id]
                predecessor_identity = {
                    "job_id": predecessor_job_id,
                    "result_id": result_id,
                    "media_sha256": media_sha,
                    "last_frame_asset_id": asset_id,
                    "last_frame_sha256": str(frame_info["content_sha256"]).lower(),
                    "last_frame_idx": frame_count - 1,
                }

            binding = compile_continuity_binding(queue, ordinal, predecessor_identity)
            binding["queue_id"] = queue_id
            binding["binding_sha256"] = hashlib.sha256(
                canonical_json(binding).encode("utf-8")).hexdigest()
            prior = shot.get("continuity_binding")
            if prior and prior.get("binding_sha256") != binding["binding_sha256"]:
                raise LongFormError("LONG_FORM_CONTINUITY_BINDING_CHANGED")
            if not prior:
                shot["continuity_binding"] = copy.deepcopy(binding)
                queue["revision"] = int(queue.get("revision", 0)) + 1
                self.store.save_json(self._queue_path(project_id, queue_id), queue)
            return {
                "queue_id": queue_id,
                "shot_id": shot_id,
                "ordinal": ordinal,
                "binding": binding,
                "reference": copy.deepcopy(derived_reference),
                "submission_performed": False,
            }

    def assemble(self, project_id: str, queue_id: str) -> dict[str, Any]:
        """Create/reconcile the cut-only sequence output without new Jobs."""
        with self._lock:
            queue = self.get(project_id, queue_id)
            manifest = build_assembly_manifest(queue)
            output_path = self._assembly_path(project_id, manifest["assembly_id"])
            existing = queue.get("assembly") or {}
            if (existing.get("status") == "READY"
                    and existing.get("assembly_id") == manifest["assembly_id"]):
                try:
                    if (output_path.is_file()
                            and sha256_file(output_path) == existing.get("output_sha256")):
                        return {"queue": queue, "assembly": copy.deepcopy(existing),
                                "reused": True, "generation_submitted": False}
                except OSError:
                    pass
            queue["assembly"] = {**manifest, "status": "PROCESSING",
                                  "started_at": self.store.timestamp()}
            self.store.save_json(self._queue_path(project_id, queue_id), queue)
            sources: list[Path] = []
            probes: list[dict[str, Any]] = []
            try:
                jobs = self.store.load_jobs(project_id)
                for shot in queue["shots"]:
                    job_id = str(shot.get("job_id") or "")
                    job = jobs.get(job_id)
                    if not job or job.get("state") != "COMPLETED":
                        raise LongFormAssemblyError("LONG_FORM_ASSEMBLY_SHOT_NOT_COMPLETED")
                    current_runtime = ((job.get("execution_trace") or {}).get(
                        "runtime_identity") or job.get("runtime_identity") or {})
                    current_job_identity = {
                        "job_id": job_id,
                        "prompt_id": str(job.get("prompt_id") or ""),
                        "workflow_sha256": str(
                            job.get("execution_workflow_sha256")
                            or (job.get("execution_trace") or {}).get(
                                "workflow_sha256") or "").lower(),
                        "runtime_id": str(current_runtime.get("runtime_id")
                                          or job.get("runtime_id") or ""),
                    }
                    if current_job_identity != shot.get("job_identity"):
                        raise LongFormAssemblyError("LONG_FORM_JOB_IDENTITY_CHANGED")
                    media = self.output_api.media_path(job_id)
                    if sha256_file(media) != (shot.get("result_identity") or {}).get(
                            "media_sha256"):
                        raise LongFormAssemblyError("LONG_FORM_SOURCE_MEDIA_CHANGED")
                    result = self.output_api.get_result(job_id)
                    probe = result.get("ffprobe") or {}
                    if probe.get("available") is not True:
                        raise LongFormAssemblyError("LONG_FORM_MEDIA_PROBE_FAILED")
                    sources.append(media)
                    probes.append(probe)
                target = queue.get("target") or {}
                output = self.assembler.assemble(
                    sources, probes,
                    width=int(target["width"]), height=int(target["height"]),
                    fps=int(target["fps"]),
                    audio_policy=str(queue.get("audio_policy") or ""),
                    output_path=output_path)
                assembly = {
                    **manifest,
                    **output,
                    "media_url": f"/api/projects/{project_id}/long-form/{queue_id}/media",
                    "completed_at": self.store.timestamp(),
                    "error_code": None,
                }
            except LongFormAssemblyError as exc:
                assembly = {**manifest, "status": "FAILED", "error_code": exc.code,
                            "failed_at": self.store.timestamp()}
            except Exception:
                assembly = {**manifest, "status": "FAILED",
                            "error_code": "LONG_FORM_ASSEMBLY_RECONCILIATION_FAILED",
                            "failed_at": self.store.timestamp()}
            queue["assembly"] = assembly
            queue = self._reconcile(queue, project_id)
            self.store.save_json(self._queue_path(project_id, queue_id), queue)
            if assembly.get("status") != "READY":
                raise LongFormError(str(assembly.get("error_code") or
                                        "LONG_FORM_ASSEMBLY_FAILED"))
            return {"queue": queue, "assembly": copy.deepcopy(assembly),
                    "reused": False, "generation_submitted": False}

    def media_path(self, project_id: str, queue_id: str) -> Path:
        queue = self.get(project_id, queue_id)
        assembly = queue.get("assembly") or {}
        if assembly.get("status") != "READY":
            raise KeyError("long-form assembly is not ready")
        path = self._assembly_path(project_id, str(assembly.get("assembly_id") or ""))
        if (not path.is_file() or path.stat().st_size <= 0
                or sha256_file(path) != assembly.get("output_sha256")):
            raise LongFormError("LONG_FORM_ASSEMBLY_OUTPUT_INTEGRITY_FAILED")
        return path

    def _assembly_path(self, project_id: str, assembly_id: str) -> Path:
        if not assembly_id or any(char not in
                                  "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
                                  for char in assembly_id):
            raise LongFormError("LONG_FORM_ASSEMBLY_ID_INVALID")
        root = (self.store.project_dir(project_id) / "long_form" / "assemblies").resolve()
        path = (root / f"{assembly_id}.mp4").resolve()
        if not path.is_relative_to(root):
            raise LongFormError("LONG_FORM_ASSEMBLY_ID_INVALID")
        return path

    def bind_job(self, project_id: str, queue_id: str,
                 shot_id: str, job_id: str) -> dict[str, Any]:
        """Bind a Job created by the normal Studio path to its Director shot."""
        with self._lock:
            queue = self.get(project_id, queue_id)
            _, job = self.store.find_job(job_id)
            if str(job.get("project_id") or "") != project_id:
                raise LongFormError("LONG_FORM_JOB_CROSS_PROJECT")
            director = job.get("director_execution") or {}
            if (str(director.get("sequence_id") or "")
                    != str(queue.get("director_sequence_id") or "")
                    or str(director.get("shot_id") or "") != shot_id):
                raise LongFormError("LONG_FORM_JOB_SHOT_IDENTITY_MISMATCH")
            provenance_binding = director.get("long_form_execution") or {}
            if (str(provenance_binding.get("queue_id") or "") != queue_id
                    or str(provenance_binding.get("shot_id") or "") != shot_id):
                raise LongFormError("LONG_FORM_JOB_QUEUE_IDENTITY_MISMATCH")
            shots = list(queue.get("shots") or [])
            target = next((item for item in shots
                           if str(item.get("shot_id") or "") == shot_id), None)
            if target is None:
                raise LongFormError("LONG_FORM_SHOT_NOT_FOUND")
            current = str(target.get("job_id") or "")
            if current and current != job_id:
                raise LongFormError("LONG_FORM_SHOT_ALREADY_BOUND")
            if current == job_id:
                return copy.deepcopy(queue)
            if target.get("state") != "PENDING":
                raise LongFormError("LONG_FORM_SHOT_NOT_SUBMITTABLE")
            target["job_id"] = job_id
            queue["revision"] = int(queue.get("revision", 0)) + (0 if current else 1)
            queue = self._reconcile(queue, project_id)
            self.store.save_json(self._queue_path(project_id, queue_id), queue)
            return copy.deepcopy(queue)

    def reserve_job(self, project_id: str, queue_id: str,
                    shot_id: str, job: Mapping[str, Any]) -> dict[str, Any]:
        """Atomically reserve the next queue shot before Job persistence.

        The reservation is a pre-submission fence: a concurrent request for
        the same shot cannot create a second Job or reach the runtime.
        """
        with self._lock:
            queue = self.get(project_id, queue_id)
            job_id = str(job.get("id") or "")
            director = job.get("director_execution") or {}
            binding = director.get("long_form_execution") or {}
            if (not job_id or str(job.get("project_id") or "") != project_id
                    or str(binding.get("queue_id") or "") != queue_id
                    or str(binding.get("shot_id") or "") != shot_id
                    or str(director.get("sequence_id") or "")
                    != str(queue.get("director_sequence_id") or "")):
                raise LongFormError("LONG_FORM_JOB_QUEUE_IDENTITY_MISMATCH")
            target = next((item for item in queue.get("shots") or []
                           if str(item.get("shot_id") or "") == shot_id), None)
            if target is None:
                raise LongFormError("LONG_FORM_SHOT_NOT_FOUND")
            if target.get("state") != "PENDING" or target.get("job_id"):
                raise LongFormError("LONG_FORM_SHOT_NOT_SUBMITTABLE")
            next_step = resume_plan(queue)
            if (next_step.get("action") != "GENERATE_NEXT_SHOT"
                    or str(next_step.get("shot_id") or "") != shot_id):
                raise LongFormError("LONG_FORM_SHOT_NOT_NEXT_IN_SEQUENCE")
            prior_binding = target.get("continuity_binding") or {}
            if (prior_binding and str(binding.get("binding_sha256") or "")
                    != str(prior_binding.get("binding_sha256") or "")):
                raise LongFormError("LONG_FORM_CONTINUITY_BINDING_CHANGED")
            target["job_id"] = job_id
            target["state"] = "PREFLIGHT"
            queue["revision"] = int(queue.get("revision", 0)) + 1
            self.store.save_json(self._queue_path(project_id, queue_id), queue)
            return copy.deepcopy(queue)

    def _reconcile(self, queue: dict[str, Any], project_id: str) -> dict[str, Any]:
        jobs = self.store.load_jobs(project_id)
        # Job and queue snapshots are separate atomic files. Recover a lost
        # response from immutable Job provenance; never choose by recency.
        queue_id = str(queue.get("queue_id") or "")
        sequence_id = str(queue.get("director_sequence_id") or "")
        provenance_jobs: dict[str, list[str]] = {}
        for candidate_id, candidate in jobs.items():
            if not isinstance(candidate, Mapping):
                continue
            provenance = candidate.get("director_execution") or {}
            binding = provenance.get("long_form_execution") or {}
            if (str(candidate.get("id") or "") != str(candidate_id)
                    or str(candidate.get("project_id") or "") != project_id
                    or str(provenance.get("sequence_id") or "") != sequence_id
                    or str(binding.get("queue_id") or "") != queue_id):
                continue
            shot_key = str(binding.get("shot_id") or "")
            if shot_key:
                provenance_jobs.setdefault(shot_key, []).append(str(candidate_id))
        for shot in queue.get("shots") or []:
            if shot.get("job_id"):
                continue
            matches = provenance_jobs.get(str(shot.get("shot_id") or ""), [])
            if len(matches) == 1:
                shot["job_id"] = matches[0]
            elif len(matches) > 1:
                shot.update(state="FAILED", error_code=
                            "LONG_FORM_MULTIPLE_JOBS_FOR_SHOT")
        identities = {}
        for shot in queue.get("shots") or []:
            job_id = str(shot.get("job_id") or "")
            job = jobs.get(job_id)
            if not job or job.get("state") != "COMPLETED":
                continue
            try:
                manifest = self.output_api.get_result(job_id)
                media = self.output_api.media_path(job_id)
            except Exception:
                continue
            output = manifest.get("output") or {}
            probe = manifest.get("ffprobe") or {}
            runtime = ((job.get("execution_trace") or {}).get("runtime_identity")
                       or job.get("runtime_identity") or {})
            runtime_id = str(runtime.get("runtime_id") or job.get("runtime_id") or "")
            identities[job_id] = {
                "available": bool(output.get("available")) and probe.get("available") is True,
                "job_id": job_id,
                "prompt_id": str(job.get("prompt_id") or ""),
                "workflow_sha256": str(
                    job.get("execution_workflow_sha256")
                    or (job.get("execution_trace") or {}).get("workflow_sha256") or ""),
                "runtime_id": runtime_id,
                "result_id": f"result:{job_id}",
                "media_sha256": sha256_file(media),
                "duration_seconds": probe.get("duration_seconds"),
                "width": probe.get("width"), "height": probe.get("height"),
                "fps": probe.get("fps"),
                "video_codec": probe.get("video_codec"),
                "container_format": probe.get("container_format"),
                "audio_stream": bool(probe.get("audio_stream")),
            }
        return reconcile_shot_queue(queue, jobs, identities)
