"""Candidate-based, rollback-safe managed Runtime updates.

This module deliberately does not download, patch, or start ComfyUI.  An
installer/update coordinator may stage a separately validated candidate and
then call :class:`RuntimeUpdateManager.promote`.  The active Runtime and the
independent Models root remain separate; no update operation ever copies or
deletes model data.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Callable


class RuntimeUpdateError(RuntimeError):
    """A candidate failed a safety gate or an atomic transition."""


class RuntimeUpdateManager:
    """Manage one active Runtime plus one retained rollback directory."""

    def __init__(self, active_root: Path, state_path: Path | None = None) -> None:
        self.active_root = Path(active_root).resolve()
        self.state_path = Path(state_path or self.active_root.parent / "runtime_update_state.json")

    @property
    def rollback_root(self) -> Path:
        return self.active_root.with_name(self.active_root.name + ".rollback")

    def status(self, candidate_root: Path | None = None) -> dict[str, Any]:
        candidate = Path(candidate_root).resolve() if candidate_root else None
        state = self._read_state()
        return {
            "active_root_exists": self.active_root.is_dir(),
            "active_root": str(self.active_root),
            "candidate_root": str(candidate) if candidate else "",
            "candidate_ready": bool(candidate and self._runtime_shape_ok(candidate)),
            "rollback_available": self.rollback_root.is_dir(),
            "last_transition": state.get("last_transition"),
            "active_version": state.get("active_version"),
            "candidate_version": state.get("candidate_version"),
            "models_root_untouched": True,
        }

    def validate_candidate(self, candidate_root: Path,
                           validator: Callable[[Path], Any] | None = None) -> dict[str, Any]:
        candidate = Path(candidate_root).resolve()
        if not self._runtime_shape_ok(candidate):
            raise RuntimeUpdateError("candidate Runtime is missing python_embeded/python.exe or ComfyUI/main.py")
        details: Any = True
        if validator is not None:
            details = validator(candidate)
            if details is False:
                raise RuntimeUpdateError("candidate Runtime validation failed")
        return {"candidate_root": str(candidate), "validated": True, "details": details,
                "models_root_untouched": True}

    def promote(self, candidate_root: Path, *, version: str,
                validator: Callable[[Path], Any] | None = None) -> dict[str, Any]:
        """Atomically promote a validated candidate and retain rollback state.

        The candidate must already be fully staged on the same volume.  The
        method retains one rollback tree and restores the active tree if the
        rename sequence fails.  It never touches a Models root.
        """
        candidate = Path(candidate_root).resolve()
        self.validate_candidate(candidate, validator)
        if candidate == self.active_root:
            raise RuntimeUpdateError("candidate Runtime must differ from active Runtime")
        if self.rollback_root.exists():
            raise RuntimeUpdateError("rollback slot is occupied; review or clear it explicitly")
        self.active_root.parent.mkdir(parents=True, exist_ok=True)
        moved_active = False
        try:
            if self.active_root.exists():
                os.replace(self.active_root, self.rollback_root)
                moved_active = True
            os.replace(candidate, self.active_root)
        except Exception as exc:
            if moved_active and self.rollback_root.exists() and not self.active_root.exists():
                os.replace(self.rollback_root, self.active_root)
            raise RuntimeUpdateError("Runtime promotion failed; active Runtime was restored") from exc
        self._write_state({
            "schema_version": 1,
            "last_transition": "promoted",
            "active_version": str(version),
            "candidate_version": str(version),
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        })
        return self.status()

    def rollback(self, *, validator: Callable[[Path], Any] | None = None) -> dict[str, Any]:
        """Restore the retained Runtime after the caller has stopped services."""
        if not self.rollback_root.is_dir():
            raise RuntimeUpdateError("no validated Runtime rollback is available")
        if validator is not None:
            self.validate_candidate(self.rollback_root, validator)
        failed = self.active_root.with_name(self.active_root.name + ".failed." + str(int(time.time())))
        try:
            if self.active_root.exists():
                os.replace(self.active_root, failed)
            os.replace(self.rollback_root, self.active_root)
        except Exception as exc:
            if failed.exists() and not self.active_root.exists():
                os.replace(failed, self.active_root)
            raise RuntimeUpdateError("Runtime rollback failed; active Runtime was restored") from exc
        self._write_state({
            "schema_version": 1,
            "last_transition": "rolled_back",
            "active_version": None,
            "candidate_version": None,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        })
        return self.status()

    @staticmethod
    def _runtime_shape_ok(root: Path) -> bool:
        return (root / "python_embeded" / "python.exe").is_file() and \
            (root / "ComfyUI" / "main.py").is_file()

    def _read_state(self) -> dict[str, Any]:
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}

    def _write_state(self, value: dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self.state_path)
