"""Director sequence CRUD, deterministic shot compilation, and retake lineage."""

from __future__ import annotations

import copy
import threading
import uuid
from typing import Any, Mapping

from runtime.a4_profiles import H3_NATIVE_FPS
from runtime.director_timeline import (
    CAMERA_INTENT_LABELS, DirectorTimelineError, compile_shot,
    normalize_sequence, new_shot, stable_sha256,
)
from runtime.multiframe_guides import (
    NATIVE_H3_FPS, compile_timeline_guide_prompt, resolve_guide_bindings,
)


class DirectorAPI:
    def __init__(self, store, output_api=None) -> None:
        self.store = store
        self.output_api = output_api
        self._lock = threading.RLock()

    def get(self, project_id: str) -> dict[str, Any]:
        self.store.load_project(project_id)
        sequence = self.store.load_json(
            self.store.project_dir(project_id) / "director.json")
        return {
            "sequence": sequence,
            "camera_intents": [
                {"id": key, "label": label,
                 "semantics": "PROMPT_CAMERA_INTENT"}
                for key, label in CAMERA_INTENT_LABELS.items()
            ],
            "execution_model": "ONE_H3_JOB_PER_SHOT; ASSEMBLY_DEFERRED_TO_A9",
        }

    def create(self, project_id: str, title: str = "建筑分镜") -> dict[str, Any]:
        with self._lock:
            self.store.load_project(project_id)
            current = self.store.load_json(
                self.store.project_dir(project_id) / "director.json")
            if current:
                return {"sequence": current, "created": False}
            project = self.store.load_project(project_id)
            shot = new_shot(ordinal=0)
            prompt = self.store.load_prompt(project_id) or {}
            prompt_parameters = prompt.get("generation_parameters") or {}
            prompt_quality = str(prompt_parameters.get("quality") or "")
            if prompt_quality in {"PREVIEW", "NATIVE_HIGH"}:
                shot["generation_settings"]["quality"] = prompt_quality
            try:
                prompt_duration = float(prompt_parameters.get("duration"))
            except (TypeError, ValueError, OverflowError):
                prompt_duration = None
            if prompt_duration is not None and 4.0 <= prompt_duration <= 15.0:
                shot["duration_seconds"] = prompt_duration
            shot["guide_asset_ids"] = [
                str(item.get("guide_id") or "")
                for item in (project.get("guide_frames") or [])]
            shot["reference_asset_ids"] = [
                str(item.get("asset_id") or "")
                for item in (prompt.get("reference_bindings") or [])]
            sequence = normalize_sequence({
                "sequence_id": f"sequence-{uuid.uuid4().hex[:16]}",
                "title": title,
                "revision": 0,
                "shots": [shot],
            }, project_id)
            sequence["revision"] = 1
            self._save(project_id, sequence)
            return {"sequence": sequence, "created": True}

    def save(self, project_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock:
            current = self.store.load_json(
                self.store.project_dir(project_id) / "director.json")
            if current is None:
                raise DirectorTimelineError("DIRECTOR_SEQUENCE_NOT_FOUND")
            expected = payload.get("expected_revision")
            if expected is not None and int(expected) != int(current.get("revision", 0)):
                raise DirectorTimelineError("DIRECTOR_SEQUENCE_STALE_REVISION")
            candidate = dict(payload.get("sequence") or {})
            if str(candidate.get("sequence_id") or "") != str(current.get("sequence_id") or ""):
                raise DirectorTimelineError("DIRECTOR_SEQUENCE_ID_MISMATCH")
            normalized = normalize_sequence(candidate, project_id)
            # A retake is a new immutable shot; callers may not edit its lineage
            # or remove source shots that already have Job evidence.
            current_shots = {str(s["shot_id"]): s for s in current.get("shots", [])}
            next_shots = {str(s["shot_id"]): s for s in normalized["shots"]}
            for shot_id, prior in current_shots.items():
                if prior.get("lineage"):
                    new_retake = next_shots.get(shot_id)
                    if not new_retake or new_retake.get("lineage") != prior.get("lineage"):
                        raise DirectorTimelineError("DIRECTOR_RETAKE_LINEAGE_IMMUTABLE")
                if prior.get("last_job_id"):
                    new = next_shots.get(shot_id)
                    if not new:
                        raise DirectorTimelineError("DIRECTOR_EXECUTED_SHOT_IMMUTABLE")
                    old_contract = {k: v for k, v in prior.items()
                                    if k not in {"ordinal", "last_job_id"}}
                    new_contract = {k: v for k, v in new.items()
                                    if k not in {"ordinal", "last_job_id"}}
                    if new_contract != old_contract:
                        raise DirectorTimelineError("DIRECTOR_EXECUTED_SHOT_IMMUTABLE")
            normalized["revision"] = int(current.get("revision", 0)) + 1
            self._save(project_id, normalized)
            return {"sequence": normalized}

    def compile(self, project_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        project = self.store.load_project(project_id)
        sequence = self._require_sequence(project_id, payload)
        expected_revision = payload.get("sequence_revision")
        if expected_revision is not None and int(expected_revision) != int(
                sequence.get("revision", 0)):
            raise DirectorTimelineError("DIRECTOR_SEQUENCE_STALE_REVISION")
        shot = self._find_shot(sequence, str(payload.get("shot_id") or ""))
        prompt = self.store.load_prompt(project_id)
        if not prompt or not (prompt.get("verified") or {}).get("pass"):
            raise DirectorTimelineError("DIRECTOR_PROMPT_NOT_VERIFIED")
        refs = self.store.load_references(project_id)
        params = dict(payload.get("generation_parameters") or {})
        compiled = compile_shot(
            prompt, shot, params, workflow_id=str(prompt.get("workflow") or ""),
            project_id=project_id, references=refs,
            guide_frames=list(project.get("guide_frames") or []))
        guide_bindings = resolve_guide_bindings(
            project_id, project.get("guide_frames") or [], refs,
            target_frame_count=int(compiled["generation_parameters"]["frame_count"]),
            fps=NATIVE_H3_FPS, workflow_id=str(prompt.get("workflow") or ""),
            reference_root=self.store.input_dir(project_id))
        execution_prompt = compile_timeline_guide_prompt(
            str(compiled["prompt"].get("prompt") or ""), guide_bindings,
            fps=NATIVE_H3_FPS)
        return {
            "sequence_id": sequence["sequence_id"],
            "sequence_revision": sequence["revision"],
            "shot": copy.deepcopy(shot),
            "compiled_prompt": compiled["prompt"].get("prompt"),
            "execution_prompt": execution_prompt["prompt"],
            "execution_prompt_sha256": execution_prompt[
                "execution_prompt_sha256"],
            "source_prompt_hash": prompt.get("prompt_hash"),
            "guide_prompt_compilation": {
                key: value for key, value in execution_prompt.items()
                if key != "prompt"},
            "compiled_fragment": compiled["compiled_fragment"],
            "prompt_sha256": compiled["prompt"].get("prompt_hash"),
            "director_provenance": compiled["provenance"],
            "generation_parameters": compiled["generation_parameters"],
            "submission_performed": False,
        }

    def prepare_for_job(self, project_id: str, execution: Mapping[str, Any],
                        prompt: Mapping[str, Any], generation_parameters: Mapping[str, Any],
                        *, runtime_target: str, project: Mapping[str, Any],
                        references: Mapping[str, Mapping[str, Any]],
                        continuity_binding: Mapping[str, Any] | None = None
                        ) -> dict[str, Any]:
        sequence = self._require_sequence(project_id, execution)
        shot = self._find_shot(sequence, str(execution.get("shot_id") or ""))
        expected_revision = execution.get("sequence_revision")
        if expected_revision is not None and int(expected_revision) != int(sequence["revision"]):
            raise DirectorTimelineError("DIRECTOR_SEQUENCE_STALE_REVISION")
        requirement = shot.get("runtime_requirement")
        if requirement not in {"any", runtime_target}:
            raise DirectorTimelineError("DIRECTOR_RUNTIME_REQUIREMENT_MISMATCH")
        shot = copy.deepcopy(shot)
        if continuity_binding is not None:
            if (str(continuity_binding.get("shot_id") or "") != str(shot["shot_id"])
                    or not str(continuity_binding.get("binding_sha256") or "")):
                raise DirectorTimelineError("DIRECTOR_LONG_FORM_BINDING_MISMATCH")
            modes = list(continuity_binding.get("continuity_modes") or [])
            if "CONTINUE_VISUALLY" in modes:
                bound_refs = list(prompt.get("reference_bindings") or [])
                first_frame_ids = [str(item.get("asset_id") or "")
                                   for item in bound_refs
                                   if item.get("role") == "first_frame"]
                if len(first_frame_ids) != 1:
                    raise DirectorTimelineError(
                        "DIRECTOR_CONTINUITY_FIRST_FRAME_CONTRACT_UNSUPPORTED")
                shot["reference_asset_ids"] = [
                    str(item.get("asset_id") or "") for item in bound_refs]
        guides = list(project.get("guide_frames") or [])
        compiled = compile_shot(
            prompt, shot, generation_parameters,
            workflow_id=str(prompt.get("workflow") or ""),
            project_id=project_id, references=references,
            guide_frames=guides)
        provenance = {
            **compiled["provenance"],
            "sequence_id": sequence["sequence_id"],
            "sequence_revision": int(sequence["revision"]),
            "sequence_sha256": stable_sha256({
                "sequence_id": sequence["sequence_id"],
                "revision": sequence["revision"],
                "shots": sequence["shots"],
            }),
            "workflow_id": prompt.get("workflow"),
        }
        if continuity_binding is not None:
            provenance["long_form_execution"] = {
                "queue_id": str(continuity_binding.get("queue_id") or ""),
                "shot_id": str(continuity_binding.get("shot_id") or ""),
                "ordinal": int(continuity_binding.get("ordinal", -1)),
                "continuity_modes": list(
                    continuity_binding.get("continuity_modes") or []),
                "binding_sha256": str(
                    continuity_binding.get("binding_sha256") or ""),
                "reference_bindings": copy.deepcopy(list(
                    continuity_binding.get("reference_bindings") or [])),
            }
        return {**compiled, "provenance": provenance, "shot": copy.deepcopy(shot)}

    def create_retake(self, project_id: str, shot_id: str,
                      payload: Mapping[str, Any]) -> dict[str, Any]:
        source_job_id = str(payload.get("source_job_id") or "")
        if not source_job_id:
            raise DirectorTimelineError("DIRECTOR_RETAKE_SOURCE_JOB_REQUIRED")
        try:
            source_project_id, source_job = self.store.find_job(source_job_id)
        except KeyError as exc:
            raise DirectorTimelineError("DIRECTOR_RETAKE_SOURCE_JOB_NOT_FOUND") from exc
        if source_project_id != project_id:
            raise DirectorTimelineError("DIRECTOR_RETAKE_CROSS_PROJECT")
        source_director = source_job.get("director_execution") or {}
        if str(source_director.get("shot_id") or "") != shot_id:
            raise DirectorTimelineError("DIRECTOR_RETAKE_SOURCE_SHOT_MISMATCH")
        if source_job.get("state") != "COMPLETED":
            raise DirectorTimelineError("DIRECTOR_RETAKE_SOURCE_NOT_COMPLETED")
        result = self.output_api.get_result(source_job_id) if self.output_api else None
        if not result or not (result.get("output") or {}).get("available"):
            raise DirectorTimelineError("DIRECTOR_RETAKE_SOURCE_RESULT_UNAVAILABLE")
        changes = payload.get("changes") or {}
        if not isinstance(changes, Mapping) or not changes:
            raise DirectorTimelineError("DIRECTOR_RETAKE_CHANGES_REQUIRED")
        if not set(changes) <= {"camera_intent", "composition_intent",
                                "preservation_intent", "action_intent",
                                "audio_intent", "prompt_fragment", "guide_asset_ids"}:
            raise DirectorTimelineError("DIRECTOR_RETAKE_FIELD_NOT_ALLOWED")
        reason = str(payload.get("retake_reason") or "").strip()
        if not reason:
            raise DirectorTimelineError("DIRECTOR_RETAKE_REASON_REQUIRED")
        with self._lock:
            sequence = self._require_sequence(project_id, payload)
            source = self._find_shot(sequence, shot_id)
            source_parameters = source_job.get("generation_parameters") or {}
            source_settings = dict(source.get("generation_settings") or {})
            source_settings["quality"] = str(
                source_parameters.get("quality") or source_settings.get(
                    "quality") or "NATIVE_HIGH")
            source_settings["fps"] = H3_NATIVE_FPS
            source_seed = source_job.get("seed", source_parameters.get("seed"))
            if source_seed is not None:
                source_settings["seed"] = int(source_seed)
            source["generation_settings"] = source_settings
            retake = copy.deepcopy(source)
            retake["shot_id"] = f"shot-{uuid.uuid4().hex[:16]}"
            retake["ordinal"] = len(sequence["shots"])
            retake["title"] = f"{source['title']} · 重拍"
            retake["last_job_id"] = None
            for key, value in changes.items():
                retake[key] = copy.deepcopy(value)
            # Apply the same strict data validation as ordinary edits.
            retake = normalize_sequence({"sequence_id": sequence["sequence_id"],
                                         "title": sequence["title"],
                                         "shots": [retake]}, project_id)["shots"][0]
            retake["ordinal"] = len(sequence["shots"])
            changed_fields = sorted(key for key in changes
                                    if changes[key] != source.get(key))
            if not changed_fields:
                raise DirectorTimelineError("DIRECTOR_RETAKE_NO_EFFECTIVE_CHANGE")
            tracked = ("duration_seconds", "camera_intent", "composition_intent",
                       "preservation_intent", "action_intent", "reference_asset_ids",
                       "guide_asset_ids", "audio_intent", "generation_settings",
                       "runtime_requirement", "prompt_fragment")
            unchanged = sorted(key for key in tracked if key not in changed_fields)
            retake["lineage"] = {
                "source_job_id": source_job_id,
                "source_result_id": f"result:{source_job_id}",
                "retake_reason": reason,
                "changed_fields": changed_fields,
                "unchanged_fields": unchanged,
                "source_workflow_sha256": str(source_job.get("execution_workflow_sha256") or ""),
            }
            sequence["shots"].append(retake)
            sequence["revision"] = int(sequence.get("revision", 0)) + 1
            self._save(project_id, sequence)
            return {"sequence": sequence, "shot": retake,
                    "source_job_id": source_job_id,
                    "source_result_id": f"result:{source_job_id}"}

    def mark_job(self, project_id: str, sequence_id: str, shot_id: str,
                 job_id: str, generation_settings: Mapping[str, Any] | None = None) -> None:
        with self._lock:
            sequence = self._require_sequence(project_id, {"sequence_id": sequence_id})
            shot = self._find_shot(sequence, shot_id)
            if generation_settings:
                settings = dict(shot.get("generation_settings") or {})
                settings.update(dict(generation_settings))
                shot["generation_settings"] = settings
            shot["last_job_id"] = job_id
            sequence["revision"] = int(sequence.get("revision", 0)) + 1
            self._save(project_id, sequence)

    def _require_sequence(self, project_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        sequence = self.store.load_json(
            self.store.project_dir(project_id) / "director.json")
        if not sequence:
            raise DirectorTimelineError("DIRECTOR_SEQUENCE_NOT_FOUND")
        if payload.get("sequence_id") and str(payload["sequence_id"]) != str(sequence.get("sequence_id")):
            raise DirectorTimelineError("DIRECTOR_SEQUENCE_ID_MISMATCH")
        return sequence

    @staticmethod
    def _find_shot(sequence: Mapping[str, Any], shot_id: str) -> dict[str, Any]:
        if not shot_id:
            raise DirectorTimelineError("DIRECTOR_SHOT_ID_REQUIRED")
        for shot in sequence.get("shots") or []:
            if str(shot.get("shot_id") or "") == shot_id:
                return shot
        raise DirectorTimelineError("DIRECTOR_SHOT_NOT_FOUND")

    def _save(self, project_id: str, sequence: dict[str, Any]) -> None:
        self.store.save_json(self.store.project_dir(project_id) / "director.json", sequence)
