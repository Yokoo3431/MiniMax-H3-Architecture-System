"""Output API (contract-first).

Builds the Project/input|workflow|prompt|output|report package with provenance,
runtime info, reference hashes, and a frozen workflow copy. Native completed
Jobs expose their verified packaged media through a job-bound URL.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List

from ._paths import REPO_ROOT
from .store import StudioStore
from runtime.a8_delivery import DeliveryError, DeliveryPipeline, sha256_file

WORKFLOW_FILE_MAP = {
    "01_Exterior_Hero": "workflows/01_Exterior_Hero_NATIVE.json",
    "02_Day_Night_Transition": "workflows/02_Day_Night_Transition_NATIVE.json",
    "03_Material_Detail": "workflows/03_Material_Detail_NATIVE.json",
    "04_Drone_Aerial": "workflows/04_Drone_Aerial_NATIVE_GOLDEN.json",
    "05_Slow_Walkthrough": "workflows/05_Slow_Walkthrough_NATIVE.json",
}


class OutputAPI:
    def __init__(self, store: StudioStore,
                 allow_mock_outputs: bool = True,
                 runtime_paths=None,
                 experimental_video_probe_python: str | None = None) -> None:
        self.store = store
        self.allow_mock_outputs = bool(allow_mock_outputs)
        self.runtime_paths = runtime_paths
        # Private deployment-only path; it is never copied into Job/API records.
        self.experimental_video_probe_python = experimental_video_probe_python
        self.delivery_pipeline = DeliveryPipeline(
            store=store, runtime_paths=runtime_paths)

    def list_deliveries(self, job_id: str) -> Dict[str, Any]:
        """List only Job-bound A8 delivery derivatives; native Result is unchanged."""
        project_id, job = self.store.find_job(job_id)
        if job.get("state") != "COMPLETED":
            raise DeliveryError("DELIVERY_SOURCE_JOB_NOT_COMPLETED")
        self.media_path(job_id)
        package = self.store.job_package_dir(project_id, job_id)
        items = self.delivery_pipeline.list_for_job(
            job_id=job_id, package_root=package)
        expected = self.delivery_pipeline._identity(job)
        source_sha = sha256_file(self.media_path(job_id))
        for item in items:
            if (item.get("prompt_id") != expected["prompt_id"]
                    or item.get("workflow_sha256") != expected["workflow_sha256"]
                    or item.get("runtime_identity") != expected["runtime_identity"]
                    or item.get("source_sha256") != source_sha):
                item["status"] = "IDENTITY_MISMATCH"
                item["error_code"] = "DELIVERY_IDENTITY_MISMATCH"
            elif item.get("status") == "READY":
                manifest = self.delivery_pipeline.manifest_for_job(
                    job_id=job_id, package_root=package,
                    delivery_id=str(item.get("delivery_id") or ""))
                media = (package / "delivery" / "outputs"
                         / f"{item['delivery_id']}.mp4").resolve()
                try:
                    media.relative_to((package / "delivery" / "outputs").resolve())
                    valid_output = (media.is_file()
                                    and sha256_file(media) == manifest.get("output_sha256"))
                except (OSError, ValueError):
                    valid_output = False
                if not valid_output:
                    item["status"] = "OUTPUT_INTEGRITY_FAILED"
                    item["error_code"] = "DELIVERY_OUTPUT_INTEGRITY_FAILED"
                    continue
                item["media_url"] = (
                    f"/api/jobs/{job_id}/deliveries/{item['delivery_id']}/media")
        return {
            "job_id": job_id,
            "available": bool(self.delivery_pipeline.available
                               and job.get("runtime") == "native"),
            "items": items,
        }

    def create_delivery(self, job_id: str, *, target_resolution: str,
                        delivery_fps: int) -> Dict[str, Any]:
        """Create/reconcile one CPU derivative without invoking ComfyUI."""
        project_id, job = self.store.find_job(job_id)
        source = self.media_path(job_id)
        recorded = [str(job.get(key) or "").strip()
                    for key in ("final_output_path", "output_path")]
        recorded = [Path(value).resolve() for value in recorded if value]
        package_video = self._package_video_path(project_id, job)
        strongly_bound = (
            source.resolve() in recorded
            or (package_video is not None and source.resolve() == package_video.resolve())
            or job_id in source.name
        )
        if not strongly_bound:
            raise DeliveryError("DELIVERY_SOURCE_IDENTITY_UNPROVEN")
        package = self.store.job_package_dir(project_id, job_id)
        return self.delivery_pipeline.create(
            job=job, source=source, package_root=package,
            target_resolution=target_resolution, delivery_fps=delivery_fps)

    def delivery_media_path(self, job_id: str, delivery_id: str) -> Path:
        """Resolve a ready derivative through the exact canonical Job identity."""
        project_id, job = self.store.find_job(job_id)
        source = self.media_path(job_id)
        package = self.store.job_package_dir(project_id, job_id)
        manifest = self.delivery_pipeline.manifest_for_job(
            job_id=job_id, package_root=package, delivery_id=delivery_id)
        identity = self.delivery_pipeline._identity(job)
        if (manifest.get("status") != "READY"
                or manifest.get("source_sha256") != sha256_file(source)
                or manifest.get("prompt_id") != identity["prompt_id"]
                or manifest.get("workflow_sha256") != identity["workflow_sha256"]
                or manifest.get("runtime_identity") != identity["runtime_identity"]):
            raise DeliveryError("DELIVERY_IDENTITY_MISMATCH")
        root = (package / "delivery" / "outputs").resolve()
        candidate = (root / f"{delivery_id}.mp4").resolve()
        if not candidate.is_relative_to(root):
            raise DeliveryError("DELIVERY_PATH_OUTSIDE_JOB_PACKAGE")
        if (not candidate.is_file() or candidate.stat().st_size <= 0
                or sha256_file(candidate) != manifest.get("output_sha256")):
            raise DeliveryError("DELIVERY_OUTPUT_INTEGRITY_FAILED")
        return candidate

    def _job_references(self, project_id: str, job: Dict[str, Any]) -> list[dict[str, Any]]:
        by_id = self.store.load_references(project_id)
        snapshots = list(job.get("reference_assets_snapshot") or [])
        ids = [str(item.get("asset_id") or "") for item in snapshots]
        if not ids:
            ids = [str(item.get("asset_id") or "")
                   for item in job.get("reference_bindings") or []]
        if ids:
            return [by_id[asset_id] for asset_id in ids if asset_id in by_id]
        current = self.store.load_project(project_id).get("current_reference_asset_id")
        return [by_id[current]] if current in by_id else []

    @staticmethod
    def _reference_manifest(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{
            "asset_id": item.get("id"),
            "role": item.get("role"),
            "filename": Path(str(item.get("filename") or "reference")).name,
            "sha256": item.get("sha256"),
            "approval_state": item.get("state"),
        } for item in refs]

    def build_output_package(self, project_id: str,
                             job: Dict[str, Any]) -> Dict[str, Any]:
        project = self.store.load_project(project_id)
        prompt = job.get("prompt_snapshot") or self.store.load_prompt(project_id)
        intent = self.store.load_intent(project_id)
        refs = self._job_references(project_id, job)
        package = self.store.package_dir(project_id)
        self.store.clear_package(project_id)

        input_dir = package / "input"
        workflow_dir = package / "workflow"
        prompt_dir = package / "prompt"
        output_dir = package / "output"
        report_dir = package / "report"
        for d in (input_dir, workflow_dir, prompt_dir, output_dir, report_dir):
            d.mkdir(parents=True, exist_ok=True)

        # input/ — copy stored reference bytes; always write reference manifest
        for ref in refs:
            stored = Path(ref["stored_path"]) if ref.get("stored_path") else None
            if stored and stored.is_file():
                dest = input_dir / stored.name
                dest.write_bytes(stored.read_bytes())
        (input_dir / "references.json").write_text(json.dumps(
            self._reference_manifest(refs), indent=2, ensure_ascii=False), encoding="utf-8")

        # workflow/ — read-only copy of the frozen workflow JSON
        workflow_name = job.get("workflow") or prompt.get("workflow")
        frozen = REPO_ROOT / WORKFLOW_FILE_MAP.get(workflow_name, "")
        if frozen.is_file():
            (workflow_dir / frozen.name).write_text(
                frozen.read_text(encoding="utf-8"), encoding="utf-8")
            workflow_copied = frozen.name
        else:
            workflow_copied = None

        # prompt/
        (prompt_dir / "prompt.json").write_text(
            json.dumps(prompt, indent=2, ensure_ascii=False), encoding="utf-8")

        # output/ — placeholder MP4 (prototype only, no GPU)
        placeholder = (
            "MOCK OUTPUT PLACEHOLDER - Architect Video Studio PATCH2.6-B prototype.\n"
            "No real MP4 is generated in this phase. PATCH2.6-C connects the "
            "Native runtime to produce the actual video.\n"
            f"workflow={workflow_name} seed={job.get('seed')}\n"
        )
        (output_dir / "output.mp4").write_text(placeholder, encoding="utf-8")

        # report/
        provenance = (prompt or {}).get("provenance", {})
        execution_trace = dict(job.get("execution_trace") or {})
        provenance = {**provenance, "execution_trace": execution_trace}
        (report_dir / "provenance.json").write_text(
            json.dumps(provenance, indent=2, ensure_ascii=False), encoding="utf-8")
        runtime_info = {
            "runtime": "MOCK_PROTOTYPE (no GPU)",
            "comfyui_invoked": False,
            "native_baseline": "ComfyUI v0.33.1 (frozen, not invoked)",
            "safe_load": "pread (frozen)",
            "model_load": False,
            "job_id": job.get("id"),
            "workflow": workflow_name,
            "seed": job.get("seed"),
        }
        (report_dir / "runtime_info.json").write_text(
            json.dumps(runtime_info, indent=2, ensure_ascii=False), encoding="utf-8")
        report = {
            "project_id": project_id,
            "project_name": project["name"],
            "job_id": job.get("id"),
            "workflow": workflow_name,
            "state": "COMPLETED",
            "reference_hashes": {
                f"{r.get('role') or 'first_frame'}:{r.get('id')}": r.get("sha256")
                for r in refs},
            "intent": intent,
            "prompt_hash": prompt.get("prompt_hash"),
            "provenance": provenance,
            "execution_trace": execution_trace,
            "audit_log": self.store.load_audit(project_id),
            "runtime_info": runtime_info,
            "workflow_file_copied": workflow_copied,
        }
        (report_dir / "report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        return self.manifest(project_id, job)

    def build_real_output_package(self, project_id: str, job: Dict[str, Any],
                                  output: Dict[str, Any],
                                  request: Any) -> Dict[str, Any]:
        """Assemble the unified package from a REAL runtime output."""
        import hashlib
        import shutil

        video_path = Path(str(output.get("video_path") or ""))
        if not video_path.is_file() or video_path.stat().st_size <= 0:
            raise ValueError("OUTPUT_FILE_MISSING: verified runtime video is unavailable")
        project = self.store.load_project(project_id)
        prompt = job.get("prompt_snapshot") or self.store.load_prompt(project_id)
        package = self.store.job_package_dir(project_id, str(job.get("id") or ""))
        for sub in ("input", "workflow", "prompt", "output", "report"):
            (package / sub).mkdir(parents=True, exist_ok=True)

        def sha256_file(path: Path) -> str:
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            return digest.hexdigest()

        media_sha256 = sha256_file(video_path)
        existing_report = package / "report" / "generation_report.json"
        existing_video = package / "output" / "video.mp4"
        if existing_report.is_file() and existing_video.is_file():
            try:
                prior = json.loads(existing_report.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                prior = {}
            if (self._report_matches_job(prior, job)
                    and prior.get("media_sha256") == media_sha256
                    and sha256_file(existing_video) == media_sha256):
                return self.manifest(project_id, job)

        # input/ — approved reference files + manifest
        refs = [r for r in self._job_references(project_id, job)
                if r.get("state") == "APPROVED"]
        for ref in refs:
            src = Path(ref["stored_path"]) if ref.get("stored_path") else None
            if src and src.is_file():
                shutil.copy2(src, package / "input" / src.name)
        (package / "input" / "references.json").write_text(json.dumps(
            self._reference_manifest(refs), indent=2, ensure_ascii=False), encoding="utf-8")

        trace = dict(job.get("execution_trace") or {})
        guide_bindings = list(trace.get("guide_bindings") or
                              job.get("guide_bindings_snapshot") or [])
        guide_manifest = []
        if guide_bindings:
            from runtime.multiframe_guides import GUIDE_ROLE, guide_comfy_filename
            guide_dir = package / "input" / "guides"
            guide_dir.mkdir(parents=True, exist_ok=True)
            reference_root = self.store.input_dir(project_id).resolve()
            records = self.store.load_references(project_id)
            for guide in guide_bindings:
                asset_id = str(guide.get("asset_id") or "")
                record = records.get(asset_id) or {}
                source = Path(str(record.get("stored_path") or "")).resolve()
                if (record.get("project_id") != project_id
                        or record.get("role") != GUIDE_ROLE
                        or str(record.get("state") or "").upper() != "APPROVED"
                        or not source.is_file()
                        or not source.is_relative_to(reference_root)):
                    raise ValueError("OUTPUT_ERROR: approved timeline guide is unavailable")
                hasher = hashlib.sha256()
                with source.open("rb") as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        hasher.update(block)
                digest = hasher.hexdigest().upper()
                expected_digest = str(guide.get("content_sha256") or "").upper()
                if digest != expected_digest or digest != str(record.get("sha256") or "").upper():
                    raise ValueError("OUTPUT_ERROR: timeline guide provenance changed")
                packaged_name = guide_comfy_filename({
                    "asset_id": asset_id, "role": GUIDE_ROLE,
                    "content_sha256": digest,
                    "filename": record.get("filename") or source.name,
                })
                shutil.copy2(source, guide_dir / packaged_name)
                guide_manifest.append({
                    "asset_id": asset_id,
                    "role": GUIDE_ROLE,
                    "requested_time_seconds": guide.get("requested_time_seconds"),
                    "resolved_frame_idx": guide.get("resolved_frame_idx"),
                    "ordinal": guide.get("ordinal"),
                    "sha256": digest,
                    "packaged_file": f"guides/{packaged_name}",
                })
        (package / "input" / "guides.json").write_text(json.dumps(
            guide_manifest, indent=2, ensure_ascii=False), encoding="utf-8")

        # Guided jobs preserve the exact compiled API graph. The immutable
        # Golden asset remains untouched and is still the non-guide base.
        from runtime.yaml_compat import safe_load
        workflow_id = job.get("workflow")
        workflow_asset = None
        snapshot = job.get("workflow_snapshot") or {}
        snapshot_workflow = snapshot.get("workflow")
        if guide_bindings:
            if not isinstance(snapshot_workflow, dict):
                raise ValueError("OUTPUT_ERROR: guided Job lacks its exact execution graph")
            workflow_asset = package / "workflow" / f"{workflow_id}_A5_EXECUTION.json"
            workflow_asset.write_text(
                json.dumps(snapshot_workflow, indent=2, ensure_ascii=False),
                encoding="utf-8")
        else:
            mapping = safe_load(
                (REPO_ROOT / "runtime" / "contracts" / "workflow_mapping.yaml")
                .read_text(encoding="utf-8"))
            if workflow_id in mapping.get("workflow_registry", {}):
                workflow_asset = REPO_ROOT / mapping["workflow_registry"][workflow_id]["native_asset"]
                if workflow_asset.is_file():
                    shutil.copy2(workflow_asset, package / "workflow" / workflow_asset.name)
            elif isinstance(snapshot_workflow, dict):
                workflow_asset = package / "workflow" / f"{workflow_id}_EXECUTION.json"
                workflow_asset.write_text(
                    json.dumps(snapshot_workflow, indent=2, ensure_ascii=False),
                    encoding="utf-8")

        # prompt/
        request_prompt = getattr(request, "prompt_payload", None)
        prompt_record = {
            "study_id": project_id,
            "workflow_id": job.get("workflow"),
            "camera_motion": job.get("camera_motion"),
            "generation_parameters": job.get("generation_parameters"),
            "prompt_hash": (request_prompt or {}).get("prompt_hash") or (prompt or {}).get("prompt_hash"),
            "prompt": (request_prompt or {}).get("prompt") or (prompt or {}).get("prompt"),
            "execution_trace": dict(job.get("execution_trace") or {}),
        }
        (package / "prompt" / "prompt.json").write_text(
            json.dumps(prompt_record, indent=2, ensure_ascii=False), encoding="utf-8")

        # output/
        packaged_video = package / "output" / "video.mp4"
        if video_path.resolve() != packaged_video.resolve():
            staged_video = package / "output" / f".video.{uuid.uuid4().hex}.partial"
            shutil.copy2(video_path, staged_video)
            if staged_video.stat().st_size != video_path.stat().st_size:
                staged_video.unlink(missing_ok=True)
                raise ValueError("PACKAGING_COPY_FAILURE: media size verification failed")
            os.replace(staged_video, packaged_video)
        if sha256_file(packaged_video) != media_sha256:
            raise ValueError("PACKAGING_COPY_FAILURE: media hash verification failed")

        # report/
        runtime_info = dict(output.get("runtime_info") or {})
        runtime_capability = trace.get("runtime_capability") or {}
        runtime_identity = trace.get("runtime_identity") or {}
        runtime_info.update({
            "job_id": str(job.get("id") or ""),
            "prompt_id": str(job.get("prompt_id") or ""),
            "execution_workflow_sha256": str(
                job.get("execution_workflow_sha256") or ""),
            "output_root_fingerprint": str(
                runtime_info.get("output_root_fingerprint") or
                runtime_identity.get("output_root_fingerprint") or ""),
            "comfyui_version": (runtime_info.get("comfyui_version")
                                or runtime_capability.get("version")
                                or "unknown"),
            "runtime_target": runtime_identity.get("target") or
                              job.get("runtime_target") or "production",
            "runtime_port": runtime_identity.get("port"),
            "workflow_asset": workflow_asset.name if workflow_asset else None,
        })
        if runtime_info["runtime_target"] == "production":
            runtime_info["safe_load"] = "H3_WINDOWS_SAFE_LOAD=pread"
        (package / "report" / "runtime_info.json").write_text(
            json.dumps(runtime_info, indent=2, ensure_ascii=False), encoding="utf-8")
        provenance = {
            "workflow": job.get("workflow"),
            "mode": (prompt or {}).get("mode"),
            "prompt_hash": (prompt or {}).get("prompt_hash"),
            "reference_sha256": [r.get("sha256") for r in refs],
            "reference_approved": True,
            "seed": job.get("seed"),
            "official_skill_revision": "2026-07-29-main-reviewed",
            "runtime": "native",
            "execution_trace": trace,
        }
        (package / "report" / "provenance.json").write_text(
            json.dumps(provenance, indent=2, ensure_ascii=False), encoding="utf-8")
        generation_report = {
            "project_id": project_id,
            "project_name": project["name"],
            "job_id": job.get("id"),
            "prompt_id": job.get("prompt_id"),
            "execution_workflow_sha256": job.get("execution_workflow_sha256"),
            "media_sha256": media_sha256,
            "workflow": job.get("workflow"),
            "seed": job.get("seed"),
            "camera_motion": job.get("camera_motion"),
            "generation_parameters": job.get("generation_parameters"),
            "prompt_hash": (prompt or {}).get("prompt_hash"),
            "runtime_info": runtime_info,
            "provenance": provenance,
            "execution_trace": dict(job.get("execution_trace") or {}),
            "status": "COMPLETED",
        }
        (package / "report" / "generation_report.json").write_text(
            json.dumps(generation_report, indent=2, ensure_ascii=False),
            encoding="utf-8")
        return self.manifest(project_id, job)

    def copy_to_study_output(self, project_id: str, job: Dict[str, Any],
                             runtime_output_path: str | Path) -> Path:
        """Copy and verify the real MP4 into the user-selected Study folder."""
        import hashlib
        import shutil
        source = Path(runtime_output_path)
        if not source.is_file() or source.stat().st_size <= 0:
            raise ValueError(f"OUTPUT_ERROR: runtime output is missing: {source}")
        project = self.store.load_project(project_id)
        destination_dir = self.store.output_directory(project)
        try:
            destination_dir.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            # Protected Documents locations are common on Windows.  Keep the
            # job successful and fall back to the app-owned data tree; persist
            # the resolved path so the user can open the actual result.
            destination_dir = self.store.data_root / "outputs" / self.store._safe_study_name(project.get("name"))
            destination_dir.mkdir(parents=True, exist_ok=True)
            project["output_directory"] = str(destination_dir)
            self.store.save_project(project)
        destination = destination_dir / f"{job.get('workflow', 'ArchitectVideo')}_{job.get('id', 'job')}.mp4"
        shutil.copy2(source, destination)
        if not destination.is_file() or destination.stat().st_size != source.stat().st_size:
            raise ValueError(f"OUTPUT_ERROR: copied output verification failed: {destination}")
        def digest(path: Path) -> str:
            h = hashlib.sha256()
            with path.open("rb") as fh:
                for block in iter(lambda: fh.read(1024 * 1024), b""):
                    h.update(block)
            return h.hexdigest()
        if digest(source) != digest(destination):
            raise ValueError(f"OUTPUT_ERROR: copied output hash mismatch: {destination}")
        return destination

    def get_result(self, job_id: str) -> Dict[str, Any]:
        project_id, job = self.store.find_job(job_id)
        if job.get("runtime") == "mock" and not self.allow_mock_outputs:
            raise ValueError(
                "REAL_RUNTIME_REQUIRED: 此任务是在设置/演示模式创建的，未生成真实视频。")
        if job["state"] != "COMPLETED":
            raise ValueError(f"job {job_id} is {job['state']}; result available only when COMPLETED")
        if job.get("runtime") == "native":
            video_path = self._job_media_path(project_id, job)
            if video_path is None:
                raise ValueError(
                    f"OUTPUT_ERROR: completed job has no real MP4 output for {job_id}")
            if not video_path.is_file() or video_path.stat().st_size <= 0:
                raise ValueError(
                    f"OUTPUT_ERROR: completed job has no real MP4 output: {video_path}")
        return self.manifest(project_id, job)

    def get_report(self, job_id: str) -> Dict[str, Any]:
        project_id, job = self.store.find_job(job_id)
        package = self._package_dir_for_job(project_id, job)
        report_path = package / "report" / "report.json"
        if report_path.is_file():
            report = json.loads(report_path.read_text(encoding="utf-8"))
            if self._report_matches_job(report, job):
                return report

        # Native output packages historically used generation_report.json.
        # Normalize that existing report shape at the API boundary instead of
        # treating optional packaging metadata as a completed-video failure.
        generation_report = package / "report" / "generation_report.json"
        if generation_report.is_file():
            report = json.loads(generation_report.read_text(encoding="utf-8"))
            if not self._report_matches_job(report, job):
                raise ValueError(f"REPORT_IDENTITY_MISMATCH: report does not belong to Job {job_id}")
            project = self.store.load_project(project_id)
            refs = self.store.load_references(project_id)
            report.setdefault("project_id", project_id)
            report.setdefault("project_name", project.get("name", ""))
            report.setdefault("job_id", job_id)
            report.setdefault("state", report.get("status", job.get("state")))
            report.setdefault("reference_hashes", {
                ref.get("filename", ref_id): ref.get("sha256")
                for ref_id, ref in refs.items()
            })
            report.setdefault("audit_log", self.store.load_audit(project_id))
            report.setdefault("provenance", {})
            return report
        raise ValueError(f"report not built for job {job_id}")

    @staticmethod
    def _report_matches_job(report: Dict[str, Any], job: Dict[str, Any]) -> bool:
        """Require persisted identity before trusting a legacy shared package."""
        if not isinstance(report, dict):
            return False
        expected_job = str(job.get("id") or "")
        expected_prompt = str(job.get("prompt_id") or "")
        expected_sha = str(job.get("execution_workflow_sha256") or "")
        runtime_info = report.get("runtime_info") or {}
        trace = report.get("execution_trace") or {}
        provenance = report.get("provenance") or {}
        observed_job = str(report.get("job_id") or runtime_info.get("job_id") or "")
        observed_prompt = str(report.get("prompt_id") or runtime_info.get("prompt_id") or "")
        observed_sha = str(
            report.get("execution_workflow_sha256")
            or trace.get("workflow_sha256")
            or provenance.get("execution_trace", {}).get("workflow_sha256")
            or "")
        if observed_job and observed_job != expected_job:
            return False
        if observed_prompt and expected_prompt and observed_prompt != expected_prompt:
            return False
        if observed_sha and expected_sha and observed_sha != expected_sha:
            return False
        return bool((observed_job and observed_job == expected_job)
                    or (observed_prompt and expected_prompt
                        and observed_prompt == expected_prompt)
                    or (observed_sha and expected_sha and observed_sha == expected_sha))

    def _package_dir_for_job(self, project_id: str,
                             job: Dict[str, Any]) -> Path:
        """Prefer the Job-scoped package; accept legacy package only by identity."""
        job_id = str(job.get("id") or "")
        if job_id:
            path = self.store.job_package_dir(project_id, job_id)
            if path.is_dir() and any(path.iterdir()):
                return path
        legacy = self.store.package_dir(project_id)
        for name in ("report.json", "generation_report.json"):
            candidate = legacy / "report" / name
            if candidate.is_file():
                try:
                    report = json.loads(candidate.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if self._report_matches_job(report, job):
                    return legacy
        return self.store.job_package_dir(project_id, job_id) if job_id else legacy

    def _package_video_path(self, project_id: str,
                            job: Dict[str, Any]) -> Path | None:
        """Return a packaged MP4 only from the matching Job package."""
        package = self._package_dir_for_job(project_id, job)
        report_path = package / "report" / "generation_report.json"
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not self._report_matches_job(report, job):
            return None
        output_root = (package / "output").resolve()
        candidate = (output_root / "video.mp4").resolve()
        try:
            candidate.relative_to(output_root)
        except ValueError:
            return None
        if candidate.is_file() and candidate.stat().st_size > 0:
            return candidate
        return None

    def _job_media_path(self, project_id: str,
                        job: Dict[str, Any]) -> Path | None:
        """Resolve a completed Job's media within AVS-owned output roots."""
        project = self.store.load_project(project_id)
        package = self._package_dir_for_job(project_id, job)
        roots = [
            (package / "output").resolve(),
            self.store.output_directory(project).resolve(),
        ]
        candidates = []
        for value in (job.get("final_output_path"), job.get("output_path")):
            if value:
                candidates.append(Path(value).resolve())
        package_video = self._package_video_path(project_id, job)
        if package_video is not None:
            candidates.append(package_video)
        for candidate in candidates:
            if candidate.suffix.lower() != ".mp4" or not candidate.is_file():
                continue
            if any(self._is_within(candidate, root) for root in roots):
                if candidate.stat().st_size > 0:
                    return candidate
        return None

    @staticmethod
    def _is_within(candidate: Path, root: Path) -> bool:
        try:
            candidate.relative_to(root)
            return True
        except ValueError:
            return False

    def media_path(self, job_id: str) -> Path:
        """Resolve browser media strictly through the selected canonical Job."""
        project_id, job = self.store.find_job(job_id)
        if job.get("runtime") == "mock" and not self.allow_mock_outputs:
            raise KeyError(f"output media not found for job {job_id}")
        if job.get("state") != "COMPLETED":
            raise KeyError(f"output media not available for job {job_id}")
        media = self._job_media_path(project_id, job)
        if media is None:
            raise KeyError(f"output media not found for job {job_id}")
        return media

    def list_outputs(self, project_id: str) -> List[Dict[str, Any]]:
        out = []
        for job in self.store.load_jobs(project_id).values():
            if (job["state"] == "COMPLETED"
                    and (self.allow_mock_outputs or job.get("runtime") != "mock")
                    and (job.get("runtime") == "mock"
                         or self._job_media_path(project_id, job) is not None)):
                out.append(self.manifest(project_id, job))
        return out

    def manifest(self, project_id: str, job: Dict[str, Any]) -> Dict[str, Any]:
        package = self._package_dir_for_job(project_id, job)
        media = self._job_media_path(project_id, job)
        ffprobe = None
        if media is not None and job.get("runtime") == "native":
            if job.get("runtime_target") == "experimental":
                delivery = dict((job.get("execution_trace") or {}).get(
                    "delivery") or {})
                if delivery.get("status") == "PROBED":
                    ffprobe = {
                        "available": True,
                        "duration_seconds": delivery.get("duration_seconds"),
                        "width": delivery.get("width"),
                        "height": delivery.get("height"),
                        "fps": delivery.get("fps"),
                        "video_codec": delivery.get("video_codec"),
                        "audio_stream": delivery.get("audio_stream", False),
                        "frame_count": delivery.get("frame_count"),
                        "container_format": delivery.get("container_format"),
                        "probe_tool": delivery.get("probe_tool"),
                    }
                else:
                    from runtime.media_probe import probe_media_file
                    ffprobe = probe_media_file(
                        media, runtime_paths=None,
                        python_executable=self.experimental_video_probe_python)
            else:
                from runtime.media_probe import probe_media_file
                ffprobe = probe_media_file(media, runtime_paths=self.runtime_paths)
        final_path = str(job.get("final_output_path") or "")
        runtime_path = str(job.get("runtime_output_path") or "")
        package_root = package.resolve().relative_to(
            self.store.project_dir(project_id).resolve()).as_posix()
        return {
            "job_id": job["id"],
            "project_id": project_id,
            "runtime": job.get("runtime", ""),
            "workflow": job.get("workflow"),
            # Public manifests contain logical package locations only. Actual
            # filesystem paths remain server-side for local delivery actions.
            "runtime_output_name": Path(runtime_path).name if runtime_path else "",
            "final_output_name": Path(final_path).name if final_path else "",
            "package_root": package_root,
            "output": {
                "available": bool(media),
                "filename": media.name if media else "",
                "media_url": f"/api/jobs/{job['id']}/media" if media else "",
                "mime_type": "video/mp4" if media else "",
                "size_bytes": media.stat().st_size if media else None,
            },
            "structure": {
                "input": [p.name for p in sorted((package / "input").iterdir())] if (package / "input").is_dir() else [],
                "workflow": [p.name for p in sorted((package / "workflow").iterdir())] if (package / "workflow").is_dir() else [],
                "prompt": [p.name for p in sorted((package / "prompt").iterdir())] if (package / "prompt").is_dir() else [],
                "output": [p.name for p in sorted((package / "output").iterdir())] if (package / "output").is_dir() else [],
                "report": [p.name for p in sorted((package / "report").iterdir())] if (package / "report").is_dir() else [],
            },
            "ffprobe": ffprobe,
            "files": {
                "prompt_json": "prompt/prompt.json",
                "provenance_json": "report/provenance.json",
                "runtime_info_json": "report/runtime_info.json",
                "report_json": "report/report.json",
                "video_mp4": "output/video.mp4",
                # Kept for backwards-compatible mock fixtures only. Production
                # jobs never expose this as a successful output.
                "output_mp4_placeholder": "output/output.mp4",
            },
        }
