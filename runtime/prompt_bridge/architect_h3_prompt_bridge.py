"""Architect Production Layer — official MiniMax H3 skill-based FL2VA prompt bridge.

Independent of the RC3-era OfficialH3PromptAdapter. Composes official-structure
FL2VA prompts (first-frame alignment + integrated_multimodal_description +
overall_soundscape + non_diegetic_music) from the skill registry and user
design intent. Not a hosted Context-IR call; does not claim resolution gains.
"""

from __future__ import annotations

import datetime as _dt
import json
import shutil
from pathlib import Path
from typing import Any, Sequence

from runtime.h3_prompt_engine import _semantic_directives

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_RULES = Path(__file__).resolve().parent / "skill_registry" / "minimax_h3_skill_rules.json"
_CATALOG = _REPO_ROOT / "configs" / "workflow_catalog.json"
_PROJECTS = _REPO_ROOT / "userdata" / "projects"


def _load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _has(text: str, aliases: Sequence[str]) -> bool:
    low = text.lower()
    return any(a.lower() in low for a in aliases)


def fl2va_end_time_seconds(frame_count: int, fps: float = 24.0) -> float:
    """Derive the FL2VA Picture-2 alignment end time from the actual output
    contract (H3 frame-grid result + fps), never a hard-coded duration.

    PATCH2.5-A: production must not hard-code 4.46s / 4.458s.
    """
    if frame_count is None or int(frame_count) <= 0:
        raise ValueError(f"frame_count must be a positive integer; got {frame_count!r}")
    if fps is None or float(fps) <= 0:
        raise ValueError(f"fps must be positive; got {fps!r}")
    return int(frame_count) / float(fps)


class H3PromptBridge:
    """Builds official-structure FL2VA prompts and writes output packages."""

    def __init__(self, rules_path=None, catalog_path=None, projects_root=None) -> None:
        self.rules = _load_json(Path(rules_path or _RULES))
        self.catalog = _load_json(Path(catalog_path or _CATALOG))
        self.projects_root = Path(projects_root or _PROJECTS)

    def get_workflow(self, workflow_name: str) -> dict:
        wf = self.catalog["workflows"].get(workflow_name)
        if wf is None:
            raise ValueError(f"Unknown workflow {workflow_name!r}; catalog: {list(self.catalog['workflows'])}")
        return wf

    def extract_intent_fields(self, intent: str, workflow: dict) -> dict:
        text = intent or ""
        cat = self.rules["categories"]
        camera = next((k["phrase"] for k in cat["camera"]["keywords"] if _has(text, k["match"])), None) or workflow.get("camera_style") or cat["camera"]["default"]
        motion = cat["motion"]
        motion_type = next((k["motion"] for k in motion["keywords"] if _has(text, k["match"])), "orbit")
        amplitude = next((k["value"] for k in motion["keywords_amplitude"] if _has(text, k["match"])), "small")
        speed = next((k["value"] for k in motion["keywords_speed"] if _has(text, k["match"])), "slow")
        verb = motion["movement_types"].get(motion_type, motion["movement_types"]["orbit"])
        movement = f"the camera {verb} with {motion['amplitude'][amplitude]} at {motion['speed'][speed]}"
        lighting = next((k["phrase"] for k in cat["lighting"]["keywords"] if _has(text, k["match"])), None) or cat["lighting"]["default"]
        geometry = next((k["phrase"] for k in cat["geometry"]["keywords"] if _has(text, k["match"])), None) or cat["geometry"]["preservation"]
        materials = [k["phrase"] for k in cat["material"]["keywords"] if _has(text, k["match"])]
        material = "; ".join(materials) if materials else cat["material"]["default"]
        atmosphere = next((k["phrase"] for k in cat["atmosphere"]["keywords"] if _has(text, k["match"])), None) or cat["atmosphere"]["mood_default"]
        return {
            "camera": {"phrase": camera, "motion_type": motion_type, "amplitude": amplitude, "speed": speed, "movement": movement},
            "motion": {"temporal_consistency": motion["temporal_consistency"]},
            "lighting": {"phrase": lighting},
            "geometry": {"phrase": geometry},
            "material": {"phrase": material},
            "atmosphere": {"phrase": atmosphere, "environment": cat["atmosphere"]["environment_default"], "weather": cat["atmosphere"]["weather_default"]},
            # The official structure remains unchanged.  Deterministic known
            # concepts are converted into English scene directives; arbitrary
            # user text is not pasted into a pseudo-schema field.
            "semantic_directives": _semantic_directives(text),
        }

    def build_fl2va_prompt(self, intent: str, workflow_name: str, duration_seconds: float = 5.0,
                           input_images: Sequence[str] | None = None,
                           frame_count: int | None = None,
                           fps: float = 24.0) -> dict[str, Any]:
        """Official FL2VA prompt: Picture 1 (first frame) at 0.00s; Picture 2 (last frame) at end."""
        workflow = self.get_workflow(workflow_name)
        fields = self.extract_intent_fields(intent, workflow)
        if frame_count is not None:
            # PATCH2.5-A: end time derives from the actual frame-grid contract.
            dur = fl2va_end_time_seconds(frame_count, fps)
        else:
            # Legacy fallback (validated 107-frame baseline) for callers that do
            # not yet supply the frame grid; production passes frame_count.
            dur = 107.0 / 24.0 if abs(float(duration_seconds) - 4.0) < 0.01 else float(duration_seconds)
        alignment = (
            "How the reference pictures align with the target video — Picture 1 (from Shot 1) "
            "aligns with the 0.00-second mark of the target video; "
            f"Picture 2 (from Shot 1) aligns with the {dur:.2f}-second mark of the target video."
        )
        description = (
            f"[Shot 1] {fields['camera']['phrase']}. {fields['camera']['movement']}. "
            f"The requested architectural direction is applied through {'; '.join(fields['semantic_directives']) or 'the selected workflow controls'}. "
            f"{fields['lighting']['phrase']}. {fields['geometry']['phrase']}. "
            f"{fields['material']['phrase']}. {fields['motion']['temporal_consistency']} "
            "The scene transitions continuously from the DAY reference (Picture 1) to the NIGHT reference (Picture 2), "
            "changing only sky, ambient brightness, interior illumination, landscape lighting, shadow softness, and color temperature. "
            "Architecture, camera, facade, materials, and landscape geometry remain unchanged. "
            f"Environment: {fields['atmosphere']['environment']}; weather: {fields['atmosphere']['weather']}; "
            f"{fields['atmosphere']['phrase']}. No text, subtitles, logos, or watermarks."
        )
        prompt = (
            f"{alignment}\n\nintegrated_multimodal_description: {description}\n\n"
            f"overall_soundscape: {self.rules['soundscape_default']}\n\n"
            f"non_diegetic_music: {self.rules['music_default']}"
        )
        return {
            "prompt": prompt,
            "alignment_instruction": alignment,
            "integrated_multimodal_description": description,
            "overall_soundscape": self.rules["soundscape_default"],
            "non_diegetic_music": self.rules["music_default"],
            "intent_fields": fields,
            "workflow": workflow_name,
            "mode": "FL2VA",
            "duration_seconds": float(duration_seconds),
            "frame_count": int(frame_count) if frame_count is not None else None,
            "fps": float(fps),
            "end_time_seconds": float(dur),
            "input_images": list(input_images or []),
            "skill_source": self.rules["meta"]["source"],
        }


    def build_i2va_prompt(self, intent: str, workflow_name: str, duration_seconds: float = 5.0,
                          input_images: Sequence[str] | None = None) -> dict[str, Any]:
        """Official I2VA prompt: single first frame is fully referenced at 0.00s.

        Alignment instruction per MiniMax H3 official prompt-writing skill
        (references/base-en.txt I2VA form), then the three core fields in order.
        """
        workflow = self.get_workflow(workflow_name)
        fields = self.extract_intent_fields(intent, workflow)
        alignment = "For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced."
        description = (
            f"[Shot 1] {fields['camera']['phrase']}. {fields['camera']['movement']}. "
            f"The requested architectural direction is applied through {'; '.join(fields['semantic_directives']) or 'the selected workflow controls'}. "
            f"{fields['lighting']['phrase']}. {fields['geometry']['phrase']}. "
            f"{fields['material']['phrase']}. {fields['motion']['temporal_consistency']} "
            f"Environment: {fields['atmosphere']['environment']}; weather: {fields['atmosphere']['weather']}; "
            f"{fields['atmosphere']['phrase']}. No text, subtitles, logos, or watermarks."
        )
        prompt = (
            f"{alignment}\n\nintegrated_multimodal_description: {description}\n\n"
            f"overall_soundscape: {self.rules['soundscape_default']}\n\n"
            f"non_diegetic_music: {self.rules['music_default']}"
        )
        return {
            "prompt": prompt,
            "alignment_instruction": alignment,
            "integrated_multimodal_description": description,
            "overall_soundscape": self.rules["soundscape_default"],
            "non_diegetic_music": self.rules["music_default"],
            "intent_fields": fields,
            "workflow": workflow_name,
            "mode": "I2VA",
            "duration_seconds": float(duration_seconds),
            "input_images": list(input_images or []),
            "skill_source": self.rules["meta"]["source"],
        }

    @staticmethod
    def verify_official_structure(result: dict) -> dict:
        prompt = result.get("prompt", "")
        alignment_ok = prompt.startswith("For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.")
        i_desc = prompt.find("integrated_multimodal_description:")
        i_snd = prompt.find("overall_soundscape:")
        i_mus = prompt.find("non_diegetic_music:")
        order_ok = -1 < i_desc < i_snd < i_mus
        blank_after_alignment = "fully referenced.\n\nintegrated_multimodal_description:" in prompt
        shot_ok = "[Shot 1]" in result.get("integrated_multimodal_description", "")
        english_ok = all(ord(c) < 128 for c in (result.get("integrated_multimodal_description", "") or "") if c not in "\n")
        return {
            "pass": bool(alignment_ok and order_ok and blank_after_alignment and shot_ok),
            "checks": {
                "alignment_instruction_exact": alignment_ok,
                "field_order": order_ok,
                "blank_line_after_alignment": blank_after_alignment,
                "single_shot_marker": shot_ok,
                "description_english_only": english_ok,
            },
        }


    @staticmethod
    def verify_fl2va_structure(result: dict) -> dict:
        p = result.get("prompt", "")
        ok = p.startswith("How the reference pictures align with the target video")
        order = -1 < p.find("integrated_multimodal_description:") < p.find("overall_soundscape:") < p.find("non_diegetic_music:")
        pair = ("Picture 1" in result.get("alignment_instruction", "")) and ("Picture 2" in result.get("alignment_instruction", ""))
        return {"pass": bool(ok and order and pair), "checks": {"alignment_prefix": ok, "field_order": order, "two_pictures": pair}}

    def write_output_package(self, project_name: str, prompt_result: dict, input_images: Sequence[str] | None = None,
                             workflow_path: str | Path | None = None, report_extra: dict | None = None) -> Path:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in project_name)
        root = self.projects_root / safe
        for sub in ("input_images", "selected_workflow", "prompts", "outputs", "reports"):
            (root / sub).mkdir(parents=True, exist_ok=True)
        for img in list(input_images or prompt_result.get("input_images") or []):
            src = Path(img)
            if src.is_file():
                shutil.copy2(src, root / "input_images" / src.name)
        if workflow_path and Path(workflow_path).is_file():
            shutil.copy2(workflow_path, root / "selected_workflow" / Path(workflow_path).name)
        (root / "prompts" / "prompt.txt").write_text(prompt_result["prompt"], encoding="utf-8")
        with open(root / "prompts" / "prompt.json", "w", encoding="utf-8") as fh:
            json.dump(prompt_result, fh, indent=2, ensure_ascii=False)
        report = {
            "created_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
            "project": safe,
            "workflow": prompt_result.get("workflow"),
            "duration_seconds": prompt_result.get("duration_seconds"),
            "prompt_fields": ["alignment_instruction", "integrated_multimodal_description", "overall_soundscape", "non_diegetic_music"],
            "output_mp4_expected": str(root / "outputs" / "output.mp4"),
            "ffprobe": None,
            "gates": None,
        }
        if prompt_result.get("provenance"):
            # PATCH2.5-A: provenance (skill/bridge/profile hashes, intent,
            # reference hashes, approval, generated prompt hash) must be stored
            # in report.json. No machine-local secrets are included.
            report["provenance"] = prompt_result["provenance"]
        if report_extra:
            report.update(report_extra)
        with open(root / "reports" / "report.json", "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, ensure_ascii=False)
        return root
