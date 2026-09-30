"""Study-owned timeline guide management on top of the existing reference store."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from runtime.a4_profiles import h3_frame_count_for_duration
from runtime.adapters.multiframe_guide_capability import capability_from_object_info
from runtime.multiframe_guides import (
    GUIDE_ROLE, GuideFrameError, NATIVE_H3_FPS, ROUNDING_POLICY,
    resolve_guide_bindings,
)


class GuideFrameAPI:
    def __init__(self, store, production_client=None, experimental_client=None,
                 experimental_enabled: bool = False,
                 production_identity: dict | None = None,
                 experimental_identity: dict | None = None) -> None:
        self.store = store
        self.production_client = production_client
        self.experimental_client = experimental_client
        self.experimental_enabled = bool(experimental_enabled)
        self.production_identity = dict(production_identity or {})
        self.experimental_identity = dict(experimental_identity or {})

    def list(self, project_id: str) -> dict[str, Any]:
        project = self.store.load_project(project_id)
        references = self.store.load_references(project_id)
        rows = self._public_rows(project.get("guide_frames") or [], references)
        return {"guide_frames": rows, "capabilities": self.capabilities()}

    def capabilities(self) -> dict[str, Any]:
        production = self._inspect_client(
            self.production_client, "production", 8189)
        experimental = self._inspect_client(
            self.experimental_client, "experimental", 8190)
        production.update(self.production_identity)
        experimental.update(self.experimental_identity)
        result = {
            "production": production,
            "experimental": experimental,
            "routing": "EXPLICIT_ONLY",
            "experimental_job_route_enabled": self.experimental_enabled,
        }
        return result

    def runtime_registry(self) -> dict[str, Any]:
        """Path-free runtime inventory suitable for the Studio API/UI."""
        capabilities = self.capabilities()
        return {
            "schema_version": 1,
            "default_runtime_id": "production-h3-8189",
            "experimental_job_route_enabled": self.experimental_enabled,
            "runtimes": [capabilities["production"], capabilities["experimental"]],
            "fallback_policy": "FORBIDDEN",
        }

    @staticmethod
    def _inspect_client(client, name: str, port: int) -> dict[str, Any]:
        if client is None:
            return {"runtime": name, "version": "unknown", "port": port,
                    "node": "MiniMaxH3AddGuide", "available": False,
                    "status": "UNAVAILABLE", "reason": "runtime client not configured",
                    "routing": "EXPLICIT_ONLY"}
        try:
            health = client.health_check()
            version = str((health.get("system") or {}).get("comfyui_version")
                          or health.get("comfyui_version") or "unknown")
            result = capability_from_object_info(
                client.object_info(), runtime_name=name, version=version, port=port)
            result["health"] = "PASS"
            return result
        except Exception as exc:  # noqa: BLE001 - capability is a read-only projection
            return {"runtime": name, "version": "unknown", "port": port,
                    "node": "MiniMaxH3AddGuide", "available": False,
                    "status": "UNAVAILABLE",
                    "reason": f"runtime not reachable ({type(exc).__name__})",
                    "health": "UNAVAILABLE", "routing": "EXPLICIT_ONLY"}

    def add(self, project_id: str, asset_id: str, time_seconds: Any) -> dict[str, Any]:
        project = self.store.load_project(project_id)
        references = self.store.load_references(project_id)
        record = references.get(str(asset_id or ""))
        self._require_guide_asset(project_id, record)
        seconds = self._time_value(time_seconds)
        rows = list(project.get("guide_frames") or [])
        if any(str(row.get("asset_id")) == str(asset_id) for row in rows):
            raise GuideFrameError("GUIDE_DUPLICATE_ASSET: this asset is already on the timeline")
        if rows and seconds <= self._time_value(rows[-1].get("requested_time_seconds")):
            raise GuideFrameError("GUIDE_ORDER_INVALID: add guides in increasing time order")
        rows.append({
            "guide_id": self.store.new_id("guide"),
            "asset_id": str(asset_id),
            "role": GUIDE_ROLE,
            "requested_time_seconds": float(seconds),
            "ordinal": len(rows) + 1,
        })
        self._save(project_id, project, rows, "add_timeline_guide")
        return self.list(project_id)

    def update(self, project_id: str, guide_id: str, time_seconds: Any) -> dict[str, Any]:
        project = self.store.load_project(project_id)
        rows = list(project.get("guide_frames") or [])
        position = self._find(rows, guide_id)
        seconds = self._time_value(time_seconds)
        if position and seconds <= self._time_value(rows[position - 1]["requested_time_seconds"]):
            raise GuideFrameError("GUIDE_ORDER_INVALID: time must follow the previous guide")
        if position + 1 < len(rows) and seconds >= self._time_value(
                rows[position + 1]["requested_time_seconds"]):
            raise GuideFrameError("GUIDE_ORDER_INVALID: time must precede the next guide")
        rows[position]["requested_time_seconds"] = float(seconds)
        self._save(project_id, project, rows, "update_timeline_guide")
        return self.list(project_id)

    def remove(self, project_id: str, guide_id: str) -> dict[str, Any]:
        project = self.store.load_project(project_id)
        rows = list(project.get("guide_frames") or [])
        self._find(rows, guide_id)
        rows = [row for row in rows if str(row.get("guide_id")) != str(guide_id)]
        self._save(project_id, project, rows, "remove_timeline_guide")
        return self.list(project_id)

    def reorder(self, project_id: str, guide_ids: list[str]) -> dict[str, Any]:
        project = self.store.load_project(project_id)
        rows = list(project.get("guide_frames") or [])
        by_id = {str(row.get("guide_id")): row for row in rows}
        if len(guide_ids) != len(rows) or set(map(str, guide_ids)) != set(by_id):
            raise GuideFrameError("GUIDE_ORDER_INVALID: reorder must include every guide once")
        ordered = [by_id[str(item)] for item in guide_ids]
        time_slots = sorted(
            (self._time_value(row["requested_time_seconds"]) for row in rows))
        for ordinal, row in enumerate(ordered, start=1):
            row["requested_time_seconds"] = float(time_slots[ordinal - 1])
            row["ordinal"] = ordinal
        self._save(project_id, project, ordered, "reorder_timeline_guides")
        return self.list(project_id)

    def resolve(self, project_id: str, *, duration_seconds: Any,
                workflow_id: str | None = None) -> dict[str, Any]:
        project = self.store.load_project(project_id)
        intent = self.store.load_intent(project_id) or {}
        workflow = workflow_id or intent.get("selected_workflow")
        duration = float(self._time_value(duration_seconds))
        target_count = h3_frame_count_for_duration(duration, NATIVE_H3_FPS)
        refs = self.store.load_references(project_id)
        try:
            bindings = resolve_guide_bindings(
                project_id, project.get("guide_frames") or [], refs,
                target_frame_count=int(target_count), fps=NATIVE_H3_FPS,
                workflow_id=workflow,
                reference_root=self.store.input_dir(project_id))
        except GuideFrameError as exc:
            return {"valid": False, "reason": str(exc), "target_frame_count": target_count,
                    "native_generation_fps": NATIVE_H3_FPS,
                    "rounding_policy": ROUNDING_POLICY,
                    "guides": self._public_rows(project.get("guide_frames") or [], refs)}
        return {
            "valid": True,
            "target_frame_count": int(target_count),
            "native_generation_fps": NATIVE_H3_FPS,
            "rounding_policy": ROUNDING_POLICY,
            "timeline_boundary_policy": "frame_0_and_last_valid_frame_reserved",
            "guides": [{key: guide[key] for key in (
                "guide_id", "asset_id", "role", "requested_time_seconds",
                "resolved_frame_idx", "ordinal", "approval_state", "content_sha256",
                "source_identity", "comfy_filename")}
                for guide in bindings],
        }

    def _save(self, project_id: str, project: dict, rows: list[dict], event: str) -> None:
        for ordinal, row in enumerate(rows, start=1):
            row["ordinal"] = ordinal
        project["guide_frames"] = rows
        self.store.save_project(project)
        self.store.append_audit(project_id, {
            "actor": "architect", "event": event,
            "from": "timeline_guides", "to": "timeline_guides",
            "detail": {"guide_count": len(rows)},
        })
        from .study_state import build_study_state
        build_study_state(self.store, project_id)

    def _public_rows(self, rows, references) -> list[dict[str, Any]]:
        result = []
        for row in rows:
            ref = references.get(str(row.get("asset_id") or "")) or {}
            stored = ref.get("stored_path")
            ready = bool(stored and Path(str(stored)).is_file())
            result.append({
                "guide_id": str(row.get("guide_id") or ""),
                "asset_id": str(row.get("asset_id") or ""),
                "role": GUIDE_ROLE,
                "requested_time_seconds": row.get("requested_time_seconds"),
                "ordinal": row.get("ordinal"),
                "filename": str(ref.get("filename") or ""),
                "approval_state": str(ref.get("state") or "MISSING"),
                "content_sha256": ref.get("sha256"),
                "preview_ready": ready,
                "preview_url": (f"/api/assets/{ref['id']}/content?v={ref.get('sha256') or ref.get('version', 1)}"
                                if ready and ref.get("id") else None),
            })
        return result

    @staticmethod
    def _time_value(value: Any) -> Decimal:
        if isinstance(value, bool):
            raise GuideFrameError(
                "GUIDE_TIME_INVALID: time must be finite and between 0 and 3600 seconds")
        try:
            result = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise GuideFrameError(
                "GUIDE_TIME_INVALID: time must be finite and non-negative") from exc
        if not result.is_finite() or result < 0 or result > Decimal("3600"):
            raise GuideFrameError("GUIDE_TIME_INVALID: time must be finite and non-negative")
        return result

    @staticmethod
    def _require_guide_asset(project_id: str, record: dict | None) -> None:
        if not record:
            raise GuideFrameError("GUIDE_ASSET_NOT_FOUND")
        if str(record.get("project_id") or "") != str(project_id):
            raise GuideFrameError("GUIDE_CROSS_PROJECT")
        if record.get("role") != GUIDE_ROLE:
            raise GuideFrameError("GUIDE_ASSET_ROLE_MISMATCH")
        if str(record.get("state") or "").upper() != "APPROVED":
            raise GuideFrameError("GUIDE_NOT_APPROVED")

    @staticmethod
    def _find(rows: list[dict], guide_id: str) -> int:
        for index, row in enumerate(rows):
            if str(row.get("guide_id")) == str(guide_id):
                return index
        raise KeyError("timeline guide not found")


__all__ = ["GuideFrameAPI"]
