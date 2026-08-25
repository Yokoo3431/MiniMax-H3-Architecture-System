"""Official H3 Skill Production Adapter (RC3.3 PATCH2.5 / PATCH2.5-A).

Production chain:

    Architect Intent -> Workflow Intent Classification -> Official H3 Skill Rule
    Selection -> H3PromptBridge -> Official Prompt Schema -> Native MiniMax H3 Node

This adapter does NOT author prompts. The Official MiniMax H3 Skill
(h3-prompt-writing) is the ONLY prompt-authoring authority; the adapter:

  1. enforces the pinned Official Skill version gate (no silent upstream drift)
  2. validates the architect intent against configs/architect_video_intent_schema.yaml
  3. selects the workflow from `video_task` (never from `project_type` alone)
  4. classifies ambiguous natural-language intent with confidence/confirmation
  5. loads the workflow profile from configs/native_workflow_prompt_profiles.yaml
  6. converts the structured intent into bridge-compatible intent language
  7. calls H3PromptBridge (the local implementation of the official skill rules)
  8. verifies the official prompt structure
  9. attaches prompt provenance metadata (skill/bridge/profile hashes, intent,
     reference hashes, approval) for auditability
  10. returns the OfficialH3Prompt schema

The legacy runtime/prompt_bridge/official_h3_prompt_adapter.py (RC3-era
manual-concatenation adapter) is DEPRECATED and must not be used in the
production chain.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from runtime.yaml_compat import safe_load

from runtime.prompt_bridge.architect_h3_prompt_bridge import H3PromptBridge
from runtime.prompt_bridge.skill_version import check_skill_version, require_generation_allowed

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_INTENT_SCHEMA = _REPO_ROOT / "configs" / "architect_video_intent_schema.yaml"
_PROFILES = _REPO_ROOT / "configs" / "native_workflow_prompt_profiles.yaml"
_CATALOG = _REPO_ROOT / "configs" / "workflow_catalog.json"

# video_task -> workflow. video_task is the PRIMARY workflow selector.
WORKFLOW_BY_VIDEO_TASK = {
    "exterior_hero": "01_Exterior_Hero",
    "day_night_transition": "02_Day_Night_Transition",
    "material_detail": "03_Material_Detail",
    "drone_aerial": "04_Drone_Aerial",
    "slow_walkthrough": "05_Slow_Walkthrough",
}
VIDEO_TASK_BY_WORKFLOW = {v: k for k, v in WORKFLOW_BY_VIDEO_TASK.items()}

# Deterministic natural-language classification signals (advisory; the
# classifier assists, it never traps the user - explicit workflow override wins).
_VIDEO_TASK_SIGNALS = {
    "exterior_hero": (
        ["exterior", "hero", "外观", "主视角", "立面展示", "建筑展示", "showcase", "reveal", "正面"],
        "building exterior facade showcase",
    ),
    "day_night_transition": (
        ["day to night", "day-night", "night", "日景", "夜景", "transition", "转换", "光照变化", "灯光", "lighting", "暮色", "dusk"],
        "environmental day-to-night lighting transition",
    ),
    "material_detail": (
        ["material", "detail", "texture", "材质", "细节", "特写", "close-up", "肌理", "拼缝", "节点"],
        "architectural material and construction detail close-up",
    ),
    "drone_aerial": (
        ["drone", "aerial", "鸟瞰", "航拍", "masterplan", "总图", "场地", "site", "top-down", "环绕"],
        "controlled aerial masterplan reveal",
    ),
    "slow_walkthrough": (
        ["walkthrough", "漫游", "推近", "push in", "slow forward", "入口", "entry", "走廊", "corridor", "庭院", "courtyard", "纵深"],
        "very slow forward architectural walkthrough",
    ),
}


@dataclass
class ArchitectIntent:
    """Normalized architect input (schema: configs/architect_video_intent_schema.yaml)."""

    project_type: str = "exterior"
    video_task: Optional[str] = None  # PRIMARY workflow selector
    scene: str = ""
    camera_motion: str = "static"
    amplitude: str = "small"
    speed: str = "slow"
    priority: str = "geometry"
    constraints: List[str] = field(default_factory=list)
    confidence: float = 1.0
    reason: str = ""
    requires_user_confirmation: bool = False


@dataclass
class ReferenceMetadata:
    """User-approved reference inputs for the selected mode."""

    input_images: List[str] = field(default_factory=list)
    user_approved: bool = False


class OfficialSkillAdapter:
    """Orchestrates the official-skill prompt production chain."""

    def __init__(self, bridge: Optional[H3PromptBridge] = None,
                 intent_schema: Optional[Path] = None,
                 profiles: Optional[Path] = None) -> None:
        self.bridge = bridge or H3PromptBridge()
        self.intent_schema = self._load_yaml(Path(intent_schema or _INTENT_SCHEMA))
        self.profiles = self._load_yaml(Path(profiles or _PROFILES))
        self.catalog = json.loads(Path(_CATALOG).read_text(encoding="utf-8"))

    # ------------------------------------------------------------------ #
    # Skill version policy (PIN, DO NOT FLOAT)
    # ------------------------------------------------------------------ #
    @staticmethod
    def skill_gate() -> Dict[str, Any]:
        """Return the skill version gate; raises if installed != pinned."""
        return require_generation_allowed()

    def skill_policy(self) -> Dict[str, Any]:
        """Three skill identities for provenance/reporting (never auto-updates)."""
        gate = check_skill_version()
        return {
            "pinned_skill_revision": gate["pinned_skill_revision"],
            "installed_skill_revision": gate["installed_skill_revision"],
            "latest_upstream_skill_revision": gate["latest_upstream_skill_revision"],
            "pinned_label": gate["pinned_revision"],
            "status": gate["status"],
            "flags": gate["flags"],
        }

    @staticmethod
    def _load_yaml(path: Path) -> dict:
        if not path.is_file():
            raise FileNotFoundError(f"Missing config: {path}")
        return safe_load(path.read_text(encoding="utf-8"))

    def _validate_intent(self, intent: ArchitectIntent) -> None:
        allowed_project = set(self.intent_schema["intent"]["project_type"])
        allowed_motion = set(self.intent_schema["intent"]["camera"]["motion"])
        allowed_priority = set(self.intent_schema["intent"]["priority"])
        allowed_task = set(self.intent_schema["intent"]["video_task"])
        if intent.project_type not in allowed_project:
            raise ValueError(f"project_type {intent.project_type!r} not in {sorted(allowed_project)}")
        if intent.video_task is not None and intent.video_task not in allowed_task:
            raise ValueError(f"video_task {intent.video_task!r} not in {sorted(allowed_task)}")
        if intent.camera_motion not in allowed_motion:
            raise ValueError(f"camera_motion {intent.camera_motion!r} not in {sorted(allowed_motion)}")
        if intent.priority not in allowed_priority:
            raise ValueError(f"priority {intent.priority!r} not in {sorted(allowed_priority)}")

    def select_workflow(self, intent: ArchitectIntent) -> str:
        """Workflow selection driven by video_task (PATCH2.5-A).

        project_type NEVER selects the workflow. When video_task is missing,
        a conservative advisory mapping is used ONLY for backward compatibility;
        ambiguous project types require an explicit video_task.
        """
        if intent.video_task:
            workflow = WORKFLOW_BY_VIDEO_TASK.get(intent.video_task)
            if workflow is None:
                raise ValueError(f"Unknown video_task {intent.video_task!r}")
            return workflow

        # Backward-compatible advisory mapping for callers without video_task.
        # This is NOT a replacement for classification; see classify_intent().
        legacy_map = {
            "exterior": "01_Exterior_Hero",
            "lighting": "02_Day_Night_Transition",
            "material": "03_Material_Detail",
            "aerial": "04_Drone_Aerial",
            "interior": "05_Slow_Walkthrough",  # advisory only
            "landscape": "04_Drone_Aerial",     # advisory only
        }
        if intent.project_type in legacy_map:
            return legacy_map[intent.project_type]
        raise ValueError(
            f"project_type {intent.project_type!r} is ambiguous without video_task; "
            "set ArchitectIntent.video_task explicitly."
        )

    def classify_intent(self, natural_language: str) -> Dict[str, Any]:
        """Deterministic natural-language workflow classification.

        Returns selected_workflow / selected_video_task / confidence / reason /
        requires_user_confirmation / candidate_workflows. Ambiguous input does
        NOT silently pick a workflow.
        """
        text = (natural_language or "").lower()
        scores: Dict[str, int] = {}
        for task, (signals, _) in _VIDEO_TASK_SIGNALS.items():
            scores[task] = sum(1 for s in signals if s in text)

        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        top_task, top_score = ranked[0]
        second_score = ranked[1][1] if len(ranked) > 1 else 0

        # Explicit workflow mention (01..05 or workflow names) -> override.
        explicit = self._explicit_workflow_from_text(text)
        if explicit is not None:
            return {
                "selected_workflow": explicit,
                "selected_video_task": VIDEO_TASK_BY_WORKFLOW[explicit],
                "confidence": 1.0,
                "reason": f"explicit workflow reference in user text ({explicit})",
                "requires_user_confirmation": False,
                "candidate_workflows": [explicit],
            }

        total = sum(scores.values())
        if total == 0:
            return {
                "selected_workflow": None,
                "selected_video_task": None,
                "confidence": 0.0,
                "reason": "no workflow signal found in user text",
                "requires_user_confirmation": True,
                "candidate_workflows": sorted(WORKFLOW_BY_VIDEO_TASK.values()),
            }

        confidence = min(1.0, top_score / 2.0 + 0.3)
        ambiguous = (top_score == second_score) or (top_score == 1 and total >= 3)
        if ambiguous or confidence < 0.6:
            candidates = [WORKFLOW_BY_VIDEO_TASK[t] for t, s in ranked if s == top_score or s == second_score]
            return {
                "selected_workflow": None,
                "selected_video_task": None,
                "confidence": round(confidence, 2),
                "reason": f"ambiguous intent; top scores {dict(ranked[:2])}",
                "requires_user_confirmation": True,
                "candidate_workflows": sorted(set(candidates)),
            }

        workflow = WORKFLOW_BY_VIDEO_TASK[top_task]
        return {
            "selected_workflow": workflow,
            "selected_video_task": top_task,
            "confidence": round(confidence, 2),
            "reason": f"matched signals {top_score} for {_VIDEO_TASK_SIGNALS[top_task][1]}",
            "requires_user_confirmation": False,
            "candidate_workflows": [workflow],
        }

    @staticmethod
    def _explicit_workflow_from_text(text: str) -> Optional[str]:
        aliases = {
            "01": "01_Exterior_Hero", "exterior hero": "01_Exterior_Hero",
            "02": "02_Day_Night_Transition", "day night": "02_Day_Night_Transition",
            "03": "03_Material_Detail", "material detail": "03_Material_Detail",
            "04": "04_Drone_Aerial", "drone aerial": "04_Drone_Aerial",
            "05": "05_Slow_Walkthrough", "slow walkthrough": "05_Slow_Walkthrough",
        }
        for token, workflow in aliases.items():
            if token in text:
                return workflow
        return None

    def _intent_language(self, intent: ArchitectIntent, profile: dict) -> str:
        """Translate structured intent into bridge-compatible intent language.

        This is a normalized conversion of the architect's structured intent, not a
        prompt: the final prompt is still authored by the official skill (bridge).
        """
        pt = intent.project_type
        vt = intent.video_task
        amp = "large amplitude" if intent.amplitude == "large" else "small amplitude, slow speed"
        base_geo = "preserve geometry, 保持几何"
        base_mat = "keep materials"

        if vt == "material_detail" or pt == "material":
            # Avoid scene words like "facade" that would mis-select the hero camera
            # phrase in the skill keyword layer; material phrases map to the
            # close-up / static camera profile verified in W03.
            return (
                f"material close-up, 特写, 细节, static shot, 固定, {amp}, "
                f"material fidelity over motion, {base_geo}, {base_mat}, calm"
            )
        if vt == "day_night_transition" or pt == "lighting":
            return (
                "static shot, 固定, continuous environmental lighting transition, "
                "keep camera and building geometry fixed, "
                f"{base_geo}, {base_mat}, calm"
            )
        if vt == "drone_aerial" or pt in ("aerial", "landscape"):
            return (
                f"aerial, 鸟瞰, subtle reveal, {amp}, "
                f"{base_geo}, {base_mat}, calm"
            )
        if vt == "slow_walkthrough" or pt == "interior":
            return (
                f"walkthrough, 漫游, 推近, {amp}, spatial stability, "
                f"{base_geo}, {base_mat}, calm"
            )
        # exterior (default)
        motion = intent.camera_motion
        motion_text = {
            "slow_push": "slow push in, 推近",
            "slow_pull": "slow pull out",
            "slow_pan": "slow pan",
            "slow_arc": "small slow arc, small amplitude",
            "walkthrough": "walkthrough, 漫游",
            "aerial_reveal": "aerial, 鸟瞰, subtle reveal",
        }.get(motion, motion)
        parts = [profile.get("intent", ""), intent.scene or "", motion_text, amp,
                 base_geo, base_mat, "calm"]
        return ", ".join(p for p in parts if p)

    def _apply_audio_policy(self, result: dict) -> dict:
        """Architecture-validation default: non_diegetic_music = N/A."""
        result = dict(result)
        result["non_diegetic_music"] = "N/A"
        result["prompt"] = (
            f"{result['alignment_instruction']}\n\n"
            f"integrated_multimodal_description: {result['integrated_multimodal_description']}\n\n"
            f"overall_soundscape: {result['overall_soundscape']}\n\n"
            f"non_diegetic_music: N/A"
        )
        return result

    def _provenance(self, intent: ArchitectIntent, workflow: str, profile: dict,
                    reference: Optional[ReferenceMetadata], prompt_hash: str,
                    frame_count: Optional[int], fps: float) -> Dict[str, Any]:
        """Prompt provenance record for report.json (no machine secrets)."""
        skill = self.skill_policy()
        reference_hashes: Dict[str, str] = {}
        for img in (reference.input_images if reference else []):
            p = Path(img)
            reference_hashes[p.name] = self._sha256_file(p) if p.is_file() else "MISSING_FILE"
        return {
            "official_skill_revision": skill["pinned_label"],
            "official_skill_hash": skill["pinned_skill_revision"],
            "installed_skill_hash": skill["installed_skill_revision"],
            "latest_upstream_skill_revision": skill["latest_upstream_skill_revision"],
            "skill_gate_status": skill["status"],
            "skill_gate_flags": skill["flags"],
            "bridge_revision": self._sha256_file(
                _REPO_ROOT / "runtime" / "prompt_bridge" / "architect_h3_prompt_bridge.py"),
            "adapter_revision": self._sha256_file(
                _REPO_ROOT / "runtime" / "prompt_bridge" / "official_skill_adapter.py"),
            "workflow_profile_revision": self._sha256_file(_PROFILES),
            "workflow_id": workflow,
            "video_task": VIDEO_TASK_BY_WORKFLOW.get(workflow),
            "generation_mode": profile.get("official_skill_mode"),
            "raw_architect_intent": {
                "project_type": intent.project_type,
                "video_task": intent.video_task,
                "scene": intent.scene,
                "camera_motion": intent.camera_motion,
                "amplitude": intent.amplitude,
                "speed": intent.speed,
                "priority": intent.priority,
                "constraints": list(intent.constraints),
                "confidence": intent.confidence,
                "reason": intent.reason,
            },
            "user_reference_hashes": reference_hashes,
            "user_reference_approved": bool(reference and reference.user_approved),
            "frame_count": frame_count,
            "fps": fps,
            "generated_prompt_hash": prompt_hash,
        }

    @staticmethod
    def _sha256_file(path: Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest().upper()

    def build_prompt(self, intent: ArchitectIntent, workflow: Optional[str] = None,
                     reference: Optional[ReferenceMetadata] = None,
                     duration_seconds: float = 4.0, frame_count: Optional[int] = None,
                     fps: float = 24.0) -> Dict[str, Any]:
        """Returns OfficialH3Prompt schema with provenance.

        workflow: explicit user override (01..05). When provided it bypasses
        automatic classification - but reference gates still apply.
        frame_count/fps: actual H3 frame-grid output contract; FL2VA end-time is
        derived dynamically (never hard-coded).
        """
        # Hard gate 1: pinned Official Skill version (installed == pinned).
        self.skill_gate()

        self._validate_intent(intent)
        if workflow is not None and workflow not in self.profiles["workflow_profiles"]:
            raise ValueError(f"Explicit workflow override {workflow!r} is not a known workflow profile")
        if workflow is None:
            if intent.requires_user_confirmation:
                raise ValueError(
                    "Intent is ambiguous (requires_user_confirmation=True). "
                    "Do NOT guess; classify_intent() returned candidate_workflows - "
                    "ask the user to confirm before generation."
                )
            workflow = self.select_workflow(intent)
        profile = self.profiles["workflow_profiles"].get(workflow)
        if profile is None:
            raise ValueError(f"Unknown workflow profile: {workflow}")

        mode = profile["official_skill_mode"]
        if mode not in ("I2VA", "FL2VA"):
            raise ValueError(f"Adapter supports I2VA/FL2VA only; profile requests {mode}")

        if reference is None or not reference.user_approved:
            raise ValueError(
                "ReferenceMetadata.user_approved must be True before GPU/prompt generation "
                "for a reference-gated workflow"
            )
        expected = profile.get("required_reference_count") or (1 if mode == "I2VA" else 2)
        if len(reference.input_images) < expected:
            raise ValueError(f"{mode} requires at least {expected} reference image(s); got {len(reference.input_images)}")

        intent_language = self._intent_language(intent, profile)
        if mode == "FL2VA":
            result = self.bridge.build_fl2va_prompt(
                intent_language, workflow, duration_seconds=duration_seconds,
                input_images=reference.input_images,
                frame_count=frame_count, fps=fps,
            )
            verify = self.bridge.verify_fl2va_structure(result)
        else:
            result = self.bridge.build_i2va_prompt(
                intent_language, workflow, duration_seconds=duration_seconds,
                input_images=reference.input_images,
            )
            verify = self.bridge.verify_official_structure(result)

        result = self._apply_audio_policy(result)
        if not verify.get("pass"):
            raise ValueError(f"Official skill structure verification failed: {verify}")

        prompt_hash = hashlib.sha256(result["prompt"].encode("utf-8")).hexdigest().upper()
        provenance = self._provenance(
            intent, workflow, profile, reference, prompt_hash, frame_count, fps)

        return {
            "alignment": result["alignment_instruction"],
            "integrated_multimodal_description": result["integrated_multimodal_description"],
            "overall_soundscape": result["overall_soundscape"],
            "non_diegetic_music": result["non_diegetic_music"],
            "prompt": result["prompt"],
            "mode": mode,
            "workflow": workflow,
            "verified": verify,
            "skill_source": "MiniMax-AI/MiniMax-H3/skills/h3-prompt-writing",
            "provenance": provenance,
        }


def demo() -> None:
    adapter = OfficialSkillAdapter()
    intent = ArchitectIntent(
        project_type="material",
        scene="fair-faced concrete facade detail",
        camera_motion="static",
        priority="material",
        constraints=["geometry", "material"],
    )
    ref = ReferenceMetadata(
        input_images=["samples/03_Material_Detail.jpg"],
        user_approved=True,
    )
    out = adapter.build_prompt(intent, reference=ref)
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    demo()
