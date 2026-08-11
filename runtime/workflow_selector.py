"""Workflow Selector Module
Selects appropriate workflow JSON from configs/workflow_registry.json based on TaskPlanner intent.
"""

import json
from pathlib import Path

class WorkflowSelector:
    """Matches task intent against categorized workflow registry."""

    def __init__(self, registry_path: Path):
        self.registry_path = registry_path
        self.categories = self._load_registry()

    def _load_registry(self) -> dict:
        if self.registry_path.is_file():
            try:
                with open(self.registry_path, "r", encoding="utf-8") as f:
                    return json.load(f).get("categories", {})
            except Exception:
                pass
        return {}

    def select_workflow(self, plan: dict) -> tuple[dict, str]:
        desc = plan["raw_task"].lower()
        matched_spec = None

        for cat_key, cat_data in self.categories.items():
            wfs = cat_data.get("workflows", {})
            for wf_id, wf_meta in wfs.items():
                for kw in wf_meta.get("supported_tasks", []):
                    if kw in desc:
                        matched_spec = wf_meta
                        break
                if matched_spec:
                    break
            if matched_spec:
                break

        if not matched_spec:
            vis_wfs = self.categories.get("architecture_visualization", {}).get("workflows", {})
            matched_spec = vis_wfs.get("1_image_to_video", {
                "filename": "1_建筑效果图_ImageToVideo.json",
                "prompt_template_key": "1_image_to_video"
            })

        filename = matched_spec.get("filename", "1_建筑效果图_ImageToVideo.json")
        return matched_spec, filename
