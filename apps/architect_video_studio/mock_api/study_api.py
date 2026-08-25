"""HTTP-facing Study state and trusted asset access."""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any, Dict, Tuple

from .reference_api import ReferenceAPI
from .store import StudioStore
from .study_state import build_study_state


class StudyAPI:
    def __init__(self, store: StudioStore) -> None:
        self.store = store
        self.references = ReferenceAPI(store)

    def get_state(self, project_id: str) -> Dict[str, Any]:
        return build_study_state(self.store, project_id)

    def asset_content(self, asset_id: str) -> Tuple[Path, str]:
        project_id, ref = self.store.find_reference(asset_id)
        if ref.get("id") != asset_id:
            raise KeyError(f"asset not found: {asset_id}")
        stored = ref.get("stored_path")
        if not stored:
            raise KeyError(f"asset has no content: {asset_id}")
        project_root = self.store.input_dir(project_id).resolve()
        path = Path(stored).resolve()
        if project_root not in path.parents or not path.is_file():
            raise KeyError(f"asset content not found: {asset_id}")
        content_type = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
        }.get(path.suffix.lower())
        if content_type is None:
            raise ValueError("unsupported reference image type")
        return path, content_type
