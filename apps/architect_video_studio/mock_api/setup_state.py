"""First-run setup state (PATCH2.8-I1).

Stores the minimal user configuration at userdata/system/setup_state.json.
NEVER stores tokens, API keys, credentials, prompts, projects, or session data.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict

SCHEMA_VERSION = 1

FORBIDDEN_KEYS = (
    "token", "api_key", "apikey", "credential", "secret", "password",
    "prompt", "session", "project", "content",
)


def _validate_no_secrets(data: Dict[str, Any]) -> None:
    for key in data:
        low = str(key).lower()
        if any(f in low for f in FORBIDDEN_KEYS):
            raise ValueError(f"forbidden key in setup state: {key}")


class SetupState:
    def __init__(self, store) -> None:
        self.store = store
        # userdata/system/setup_state.json (data_root = userdata/studio in dist)
        self.path = self.store.data_root.parent / "system" / "setup_state.json"

    def load(self) -> Dict[str, Any]:
        if not self.path.is_file():
            return {
                "schema_version": SCHEMA_VERSION,
                "setup_completed": False,
                "native_root": "",
                "models_root": "",
                "last_validation": "",
                "environment_status": "SETUP_REQUIRED",
                "skill_status": "UNKNOWN",
            }
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {"schema_version": SCHEMA_VERSION, "setup_completed": False}
        _validate_no_secrets(data)
        return data

    def save(self, data: Dict[str, Any]) -> Dict[str, Any]:
        _validate_no_secrets(data)
        state = self.load()
        state.update(data)
        state["schema_version"] = SCHEMA_VERSION
        state.setdefault("setup_completed", False)
        state["last_validation"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
        return state
