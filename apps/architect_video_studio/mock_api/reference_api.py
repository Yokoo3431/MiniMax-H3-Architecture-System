"""Reference API (mock, contract-first).

Quality cards are advisory (ReferenceQualityAssistant when cv2 is available,
otherwise a deterministic mock card). Approval/rejection is ALWAYS a human
action and is enforced by the state machine.
"""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional

from .store import StudioStore
from ..state_machine.machine import IllegalTransitionError, ProjectStateMachine

_REFERENCE_ROLES = ("first_frame", "last_frame")


class ReferenceAPI:
    def __init__(self, store: StudioStore) -> None:
        self.store = store

    # ------------------------------------------------------------------ #
    def upload_reference(self, project_id: str, filename: str,
                         role: str = "first_frame",
                         data_base64: Optional[str] = None) -> Dict[str, Any]:
        project = self.store.load_project(project_id)
        if project["state"] not in (
                "CREATED", "REFERENCE_PENDING", "REFERENCE_REJECTED",
                "REFERENCE_APPROVED", "PROMPT_REVIEW", "PROMPT_NEEDS_CONFIRMATION",
                "USER_CONFIRM", "GPU_FAILED", "QUALITY_FAILED", "COMPLETED"):
            raise ValueError(
                f"cannot upload reference from state {project['state']}; "
                "reject/restart required"
            )
        if role not in _REFERENCE_ROLES:
            raise ValueError(f"role {role!r} not in {_REFERENCE_ROLES}")
        filename = Path(filename).name  # strip any path component

        stored_path: Optional[Path] = None
        sha256 = None
        if data_base64:
            raw = base64.b64decode(data_base64)
            stored_path = self.store.input_dir(project_id) / filename
            stored_path.write_bytes(raw)
            sha256 = hashlib.sha256(raw).hexdigest().upper()

        quality_card = self._assess_quality(stored_path if stored_path else None,
                                            filename=filename)
        ref_id = self.store.new_id("ref")
        ref = {
            "id": ref_id,
            "project_id": project_id,
            "filename": filename,
            "stored_path": str(stored_path) if stored_path else None,
            "role": role,
            "state": "PENDING",
            "quality_card": quality_card,
            "sha256": sha256,
            "version": 1,
            "created_at": self.store.timestamp(),
            "approved_at": None,
            "rejected_at": None,
            "reject_reason": "",
        }
        refs = self.store.load_references(project_id)
        refs[ref_id] = ref
        self.store.save_references(project_id, refs)
        # A new reference materially changes Prompt provenance.  The old
        # optimized Prompt is stale immediately.
        self.store.clear_prompt(project_id)

        machine = ProjectStateMachine(project["state"])
        try:
            if project["state"] == "CREATED":
                machine.transition("upload_reference", actor="architect",
                                   reason=f"upload {filename}")
            elif project["state"] == "REFERENCE_REJECTED":
                machine.transition("upload_new", actor="architect",
                                   reason=f"upload {filename}")
            elif project["state"] not in ("REFERENCE_PENDING",):
                # Editing the reference reopens only the reference gate; Job
                # history remains untouched.
                machine.state = "REFERENCE_PENDING"
        except IllegalTransitionError:
            pass  # already REFERENCE_PENDING: adding another reference is fine
        project["state"] = machine.state
        self.store.save_project(project)
        self._audit(project_id, "upload_reference", machine.state,
                    {"filename": filename, "role": role, "reference_id": ref_id})
        return self._public_ref(ref)

    def approve_reference(self, project_id: str, reference_id: str) -> Dict[str, Any]:
        project = self.store.load_project(project_id)
        refs = self.store.load_references(project_id)
        ref = refs.get(reference_id)
        if ref is None:
            raise KeyError(f"reference not found: {reference_id}")
        if ref["state"] != "PENDING":
            raise ValueError(f"reference {reference_id} is {ref['state']}, not PENDING")
        ref["state"] = "APPROVED"
        ref["approved_at"] = self.store.timestamp()
        self.store.save_references(project_id, refs)

        if project["state"] in ("REFERENCE_PENDING", "REFERENCE_REJECTED"):
            machine = ProjectStateMachine(project["state"])
            if project["state"] == "REFERENCE_REJECTED":
                machine.transition("upload_new", actor="architect", reason="approve replacement")
            machine.transition("approve", actor="architect",
                               reason=f"approve reference {reference_id}")
            project["state"] = machine.state
            self.store.save_project(project)
        elif project["state"] in ("GPU_FAILED", "QUALITY_FAILED", "COMPLETED",
                                   "PROMPT_REVIEW", "USER_CONFIRM"):
            project["state"] = "REFERENCE_APPROVED"
            self.store.save_project(project)
        self.store.clear_prompt(project_id)
        self._audit(project_id, "approve_reference", project["state"],
                    {"reference_id": reference_id, "filename": ref["filename"]})
        return self._public_ref(ref)

    def reject_reference(self, project_id: str, reference_id: str,
                         reason: str = "") -> Dict[str, Any]:
        project = self.store.load_project(project_id)
        refs = self.store.load_references(project_id)
        ref = refs.get(reference_id)
        if ref is None:
            raise KeyError(f"reference not found: {reference_id}")
        if ref["state"] != "PENDING":
            raise ValueError(f"reference {reference_id} is {ref['state']}, not PENDING")
        ref["state"] = "REJECTED"
        ref["rejected_at"] = self.store.timestamp()
        ref["reject_reason"] = reason
        self.store.save_references(project_id, refs)

        remaining_pending = [r for r in refs.values() if r["state"] == "PENDING"]
        if project["state"] == "REFERENCE_PENDING" and not remaining_pending:
            machine = ProjectStateMachine("REFERENCE_PENDING")
            machine.transition("reject", actor="architect", reason=reason or "rejected by architect")
            project["state"] = machine.state
            self.store.save_project(project)
        self._audit(project_id, "reject_reference", project["state"],
                    {"reference_id": reference_id, "reason": reason})
        return self._public_ref(ref)

    def list_references(self, project_id: str) -> List[Dict[str, Any]]:
        return [self._public_ref(ref)
                for ref in self.store.load_references(project_id).values()]

    def get_approved_references(self, project_id: str) -> List[Dict[str, Any]]:
        return [r for r in self.list_references(project_id) if r["state"] == "APPROVED"]

    def _public_ref(self, ref: Dict[str, Any]) -> Dict[str, Any]:
        """Return browser-safe metadata; never expose the stored filesystem path."""
        public = dict(ref)
        stored = public.pop("stored_path", None)
        public["preview_ready"] = bool(stored and Path(stored).is_file())
        public["preview_url"] = (
            f"/api/assets/{public['id']}/content?v={public.get('sha256') or public.get('version', 1)}"
            if public["preview_ready"] else None
        )
        return public

    # ------------------------------------------------------------------ #
    def _assess_quality(self, path: Optional[Path], filename: str) -> Dict[str, Any]:
        if path is not None and path.is_file():
            try:
                from runtime.input_validator.reference_quality_assistant import (
                    ReferenceQualityAssistant,
                )
                return ReferenceQualityAssistant().assess(str(path))
            except Exception:
                pass
        return {
            "source": filename,
            "reference_quality": {
                "resolution": "PASS (mock)",
                "geometry": "MEDIUM (mock)",
                "motion_risk": "LOW (mock)",
                "note": "mock reference record; upload a real image for a live quality card",
            },
            "recommended_workflow": None,
            "prompt_recommendation": None,
            "guidance": "Mock quality card (no image bytes provided).",
        }

    def _audit(self, project_id: str, event: str, to_state: str,
               detail: Dict[str, Any]) -> None:
        self.store.append_audit(project_id, {
            "actor": "architect",
            "event": event,
            "from": "reference",
            "to": to_state,
            "detail": detail,
        })
