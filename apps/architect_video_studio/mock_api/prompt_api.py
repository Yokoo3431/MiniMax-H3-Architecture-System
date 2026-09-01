"""Prompt API (mock, contract-first).

The default path is the universal offline-first H3 Prompt Engine.  A caller
may inject the legacy adapter in tests or controlled compatibility checks, but
the normal product path never labels deterministic compilation as AI Skill
execution.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from ..state_machine.machine import ProjectStateMachine
from .store import StudioStore
from .study_state import build_study_state
from runtime.h3_generation_parameters import normalize_generation_parameters
from runtime.prompt_provenance import (
    generation_parameters_hash,
    prompt_input_hash,
    reference_asset_hash,
    stable_hash,
)
from runtime.workflow_motion import normalize_camera_motion
from runtime.h3_prompt_engine import (
    CLIReasoningProvider, OpenAICompatibleProvider, PromptReasoningRequest,
    CLI_PROVIDER_IDS, UniversalPromptEngine, discover_providers, provider_summary,
    test_provider_configuration,
)

FROZEN_WORKFLOWS = (
    "01_Exterior_Hero",
    "02_Day_Night_Transition",
    "03_Material_Detail",
    "04_Drone_Aerial",
    "05_Slow_Walkthrough",
)

CAMERA_BY_WORKFLOW = {
    "01_Exterior_Hero": "slow_push",
    "02_Day_Night_Transition": "static",
    "03_Material_Detail": "static",
    "04_Drone_Aerial": "aerial_reveal",
    "05_Slow_Walkthrough": "walkthrough",
}

PRIORITY_BY_WORKFLOW = {
    "01_Exterior_Hero": "geometry",
    "02_Day_Night_Transition": "lighting",
    "03_Material_Detail": "material",
    "04_Drone_Aerial": "geometry",
    "05_Slow_Walkthrough": "geometry",
}


class PromptAPI:
    def __init__(self, store: StudioStore, adapter=None) -> None:
        self.store = store
        from runtime.prompt_bridge.official_skill_adapter import (
            ArchitectIntent,
            OfficialSkillAdapter,
            ReferenceMetadata,
        )
        self._intent_cls = ArchitectIntent
        self._ref_cls = ReferenceMetadata
        self._custom_adapter = adapter is not None
        if adapter is None:
            adapter = OfficialSkillAdapter()
        self.adapter = adapter
        self.engine = UniversalPromptEngine()
        self.providers_path = Path(self.store.data_root) / "prompt_providers.json"

    def _provider_configs(self) -> Dict[str, Dict[str, Any]]:
        try:
            value = self.store.load_json(self.providers_path, {}) or {}
        except (OSError, ValueError, TypeError):
            value = {}
        return value if isinstance(value, dict) else {}

    def _effective_provider_config(self, provider: str, body: Dict[str, Any] | None = None) -> Dict[str, Any]:
        """Merge saved settings with live discovery; blank legacy values must not hide a valid executable."""
        provider = str(provider or "").upper()
        discovered = next((item for item in discover_providers()
                           if str(item.get("provider", "")).upper() == provider), {})
        config = dict(discovered)
        saved = self._provider_configs().get(provider, {})
        for source in (saved, body or {}):
            for key, value in dict(source).items():
                if key == "provider" or value is None or value == "":
                    continue
                config[key] = value
        config["provider"] = provider
        return config

    def provider_catalog(self) -> List[Dict[str, Any]]:
        """Expose provider identity/configuration without secrets or prompt data."""
        configured = self._provider_configs()
        result = []
        for item in discover_providers():
            provider = str(item.get("provider") or "").upper()
            result.append({**item, **provider_summary(self._effective_provider_config(provider))})
        for name in configured:
            if not any(str(item.get("provider") or "").upper() == str(name).upper()
                       for item in result):
                result.append(provider_summary(self._effective_provider_config(name)))
        return result

    def configure_provider(self, body: Dict[str, Any]) -> Dict[str, Any]:
        provider = str(body.get("provider") or "").upper()
        if provider not in set(CLI_PROVIDER_IDS) | {"OFFLINE_COMPILER", "OPENAI_COMPATIBLE_HTTP", "LOCAL_OPENAI_COMPATIBLE"}:
            raise ValueError("不支持的 Prompt Provider")
        config = {"provider": provider}
        for key in ("executable", "base_url", "model", "api_key_env", "timeout"):
            if body.get(key) not in (None, ""):
                config[key] = body[key]
        if body.get("arguments") is not None:
            config["arguments"] = list(body.get("arguments") or [])
        config["multimodal_capable"] = bool(body.get("multimodal_capable", False))
        configs = self._provider_configs()
        configs[provider] = config
        self.providers_path.parent.mkdir(parents=True, exist_ok=True)
        self.providers_path.write_text(json.dumps(configs, ensure_ascii=False, indent=2), encoding="utf-8")
        return provider_summary(config)

    def test_provider(self, body: Dict[str, Any]) -> Dict[str, Any]:
        provider = str(body.get("provider") or "").upper()
        config = self._effective_provider_config(provider, body)
        return test_provider_configuration(config)

    def _configured_engine(self) -> UniversalPromptEngine:
        providers = {}
        names = set(self._provider_configs()) | {
            str(item.get("provider") or "").upper()
            for item in discover_providers()
        }
        for name in names:
            config = self._effective_provider_config(name)
            if name in CLI_PROVIDER_IDS:
                providers[name] = CLIReasoningProvider(config.get("executable"), config.get("arguments") or [],
                    timeout=int(config.get("timeout", 120)), multimodal_capable=bool(config.get("multimodal_capable")),
                    provider_name=name)
            elif name in ("OPENAI_COMPATIBLE_HTTP", "LOCAL_OPENAI_COMPATIBLE"):
                providers[name] = OpenAICompatibleProvider(str(config.get("base_url") or ""),
                    str(config.get("model") or ""), api_key_env=config.get("api_key_env"),
                    multimodal_capable=bool(config.get("multimodal_capable")), timeout=int(config.get("timeout", 120)))
        return UniversalPromptEngine(providers)

    def generate_prompt(self, project_id: str,
                        workflow: str | None = None,
                        generation_parameters: Dict[str, Any] | None = None,
                        prompt_engine: str = "AUTO",
                        image_consent: bool = False) -> Dict[str, Any]:
        project = self.store.load_project(project_id)
        # Gate on canonical Job activity, not a stale project.state value.
        if build_study_state(self.store, project_id).get("active_job_id"):
            raise ValueError(
                "当前任务正在生成，完成后才能更新 Prompt"
            )
        intent = self.store.load_intent(project_id)
        if intent is None:
            raise ValueError("analyze_intent first")
        if intent.get("requires_user_confirmation"):
            raise ValueError("intent requires user workflow confirmation first")

        workflow = workflow or intent.get("selected_workflow")
        if workflow not in FROZEN_WORKFLOWS:
            raise ValueError(f"workflow {workflow!r} not in frozen set {FROZEN_WORKFLOWS}")

        refs = self.store.load_references(project_id)
        current_id = project.get("current_reference_asset_id")
        current = refs.get(current_id)
        approved = [current] if current and current.get("state") == "APPROVED" else []
        if not approved:
            raise ValueError(
                "Reference Approval Gate: current reference is not approved "
                "(no approved reference selected)"
            )

        reference_paths = [r["stored_path"] or r["filename"] for r in approved]
        reference_hash = reference_asset_hash(approved)
        camera_motion = normalize_camera_motion(workflow)
        intent_obj = self._intent_cls(
            project_type=project["project_type"],
            video_task=intent.get("selected_video_task"),
            scene=intent.get("natural_language", ""),
            camera_motion=camera_motion,
            amplitude="small",
            speed="slow",
            priority=PRIORITY_BY_WORKFLOW[workflow],
            constraints=["geometry", "material"],
            confidence=float(intent.get("confidence") or 0.0),
            reason=intent.get("reason", ""),
            requires_user_confirmation=False,
        )
        ref_meta = self._ref_cls(
            input_images=reference_paths,
            user_approved=True,
        )
        frame_count = 107 if workflow == "02_Day_Night_Transition" else None
        params = normalize_generation_parameters(generation_parameters)
        started_at = self.store.timestamp()
        try:
            if self._custom_adapter:
                prompt = self.adapter.build_prompt(
                    intent_obj,
                    workflow=workflow,
                    reference=ref_meta,
                    duration_seconds=params["duration"],
                    frame_count=frame_count,
                    fps=float(params["fps"]),
                )
                prompt = dict(prompt)
                prompt.update({
                    "engine_mode": "LEGACY_OFFICIAL_ADAPTER",
                    "provider": "OFFICIAL_SKILL_ADAPTER",
                    "skill_execution": True,
                    "fallback": False,
                })
            else:
                mode = "FL2VA" if workflow == "02_Day_Night_Transition" else "I2VA"
                prompt = self._configured_engine().generate(
                    PromptReasoningRequest(
                        mode=mode,
                        duration=float(params["duration"]),
                        user_intent=intent.get("natural_language", ""),
                        reference_role="first_and_last_frame" if mode == "FL2VA" else "first_frame",
                        reference_count=len(approved),
                        workflow_id=workflow,
                        camera_motion=camera_motion,
                        reference_image_path=reference_paths[0] if reference_paths else None,
                        image_consent=bool(image_consent),
                        metadata={"generation_parameters": params},
                    ),
                    provider=prompt_engine,
                )
        except Exception as exc:  # noqa: BLE001 - product fallback boundary
            # A fallback is allowed for inspection, but it must never wear the
            # official-success badge or pass the generation gate.
            completed_at = self.store.timestamp()
            reference_id = current.get("id") if current else None
            reference_hash = reference_asset_hash(approved)
            fallback = self._fallback_prompt(workflow, intent.get("natural_language", ""))
            record = {
                "project_id": project_id, "workflow": workflow, "mode": "FALLBACK",
                "prompt": fallback, "alignment": "", "integrated_multimodal_description": fallback,
                "overall_soundscape": "N/A", "non_diegetic_music": "N/A",
                "verified": {"pass": False, "reason": "official skill invocation failed"},
                "prompt_hash": stable_hash(fallback), "generation_parameters": params,
                "original_intent": intent.get("natural_language", ""),
                "optimized_prompt": fallback, "workflow_id": workflow,
                "reference_asset_hash": reference_hash,
                "generation_parameters_hash": generation_parameters_hash(params),
                "input_hash": prompt_input_hash(intent.get("natural_language", ""), workflow,
                                                 reference_hash, params),
                "generated_at": completed_at, "created_at": completed_at,
                "status": "FALLBACK", "prompt_source": "template_fallback",
                "prompt_current": False,
                "skill_invoked": False,
                "skill_source": "MiniMax-AI/MiniMax-H3/skills/h3-prompt-writing",
                "skill_version": "unknown",
                "input_intent_hash": stable_hash(intent.get("natural_language", "")),
                "reference_asset_id": reference_id,
                "reference_hash": reference_hash,
                "optimized_prompt_hash": stable_hash(fallback),
                "started_at": started_at, "completed_at": completed_at,
                "invocation_result": f"FAILED: {type(exc).__name__}: {exc}",
                "official_skill_status": "官方 Prompt Skill 未运行，当前为基础模板",
            }
            self.store.save_prompt(project_id, record)
            return record
        created_at = self.store.timestamp()
        params_hash = generation_parameters_hash(params)
        provenance = dict(prompt.get("provenance") or {})
        completed_at = self.store.timestamp()
        provider_name = str(prompt.get("provider") or prompt_engine or "OFFLINE_COMPILER").upper()
        engine_mode = str(prompt.get("engine_mode") or "OFFLINE_COMPILER")
        skill_executed = bool(prompt.get("skill_execution"))
        prompt_hash = stable_hash(prompt["prompt"])
        validation = prompt.get("validator_result") or prompt.get("verified") or {"pass": False}
        skill_version = prompt.get("skill_version") or provenance.get("official_skill_revision", "unknown")
        skill_source = prompt.get("skill_source", "MiniMax-AI/MiniMax-H3/skills/h3-prompt-writing")
        reference_hashes = {
            str(item.get("filename") or item.get("id") or "reference"): str(
                item.get("sha256") or item.get("id") or "MISSING_FILE"
            )
            for item in approved
        }
        raw_architect_intent = {
            "project_type": intent_obj.project_type,
            "video_task": intent_obj.video_task,
            "scene": intent_obj.scene,
            "camera_motion": intent_obj.camera_motion,
            "amplitude": intent_obj.amplitude,
            "speed": intent_obj.speed,
            "priority": intent_obj.priority,
            "constraints": list(intent_obj.constraints),
            "confidence": intent_obj.confidence,
            "reason": intent_obj.reason,
        }
        if engine_mode == "OFFLINE_COMPILER":
            status_text = "H3 官方格式编译 ✓ · 未启用 AI 图像理解"
            prompt_source = "offline_h3_compiler" if not prompt.get("fallback") else "offline_fallback"
        elif engine_mode == "TEXT_REASONING_H3":
            status_text = "H3 Skill · AI文本优化 ✓"
            prompt_source = "reasoning_provider"
        elif engine_mode == "MULTIMODAL_H3":
            status_text = "H3 Skill · 图像理解优化 ✓"
            prompt_source = "reasoning_provider"
        else:
            status_text = "官方 H3 Prompt Skill 已执行 ✓" if skill_executed else "H3 官方格式编译 ✓"
            prompt_source = "official_skill_adapter" if skill_executed else "offline_h3_compiler"
        if prompt.get("fallback"):
            status_text = "AI优化失败，已使用 H3 官方格式编译"
        provenance.update({
            "official_skill_revision": skill_version,
            "official_skill_hash": prompt.get("skill_hash"),
            "engine_mode": engine_mode,
            "provider": provider_name,
            "model": prompt.get("model"),
            "skill_hash": prompt.get("skill_hash"),
            "skill_version": skill_version,
            "multimodal": bool(prompt.get("multimodal_capable")),
            "input_fingerprint": prompt_input_hash(
                intent.get("natural_language", ""), workflow, reference_hash, params, provider_name),
            "output_hash": prompt_hash,
            "validator_result": validation,
            "skill_invoked": skill_executed,
            "invocation_result": "PASS" if skill_executed else "OFFLINE_COMPILED",
            "workflow_id": workflow,
            "generation_mode": prompt.get("mode"),
            "raw_architect_intent": raw_architect_intent,
            "user_reference_hashes": reference_hashes,
            "user_reference_approved": True,
            "generated_prompt_hash": prompt_hash,
            "provider_evidence": prompt.get("evidence"),
            "started_at": started_at,
            "completed_at": completed_at,
        })
        record = {
            "project_id": project_id,
            "workflow": workflow,
            "mode": prompt["mode"],
            "prompt": prompt["prompt"],
            "alignment": prompt.get("alignment", prompt.get("alignment_instruction", "")),
            "integrated_multimodal_description": prompt["integrated_multimodal_description"],
            "overall_soundscape": prompt["overall_soundscape"],
            "non_diegetic_music": prompt["non_diegetic_music"],
            "verified": validation,
            "prompt_hash": prompt_hash,
            "provenance": {
                **provenance,
                "skill_source": skill_source,
                "input_intent_hash": stable_hash(intent.get("natural_language", "")),
                "reference_asset_id": current_id,
                "reference_hash": reference_hash,
                "optimized_prompt_hash": prompt_hash,
            },
            "generation_parameters": params,
            "original_intent": intent.get("natural_language", ""),
            "optimized_prompt": prompt["prompt"],
            "workflow_id": workflow,
            "reference_asset_hash": reference_hash,
            "generation_parameters_hash": params_hash,
            "input_hash": prompt_input_hash(
                intent.get("natural_language", ""), workflow,
                reference_hash, params, provider_name),
            "generated_at": created_at,
            "adapter_version": provenance.get("adapter_revision", ""),
            "bridge_version": provenance.get("bridge_revision", ""),
            "status": "CURRENT" if validation.get("pass") else "INVALID",
            "prompt_source": prompt_source,
            "prompt_current": bool(validation.get("pass")),
            "skill_invoked": skill_executed,
            "skill_source": skill_source,
            "skill_version": skill_version,
            "input_intent_hash": stable_hash(intent.get("natural_language", "")),
            "reference_asset_id": current_id,
            "reference_hash": reference_hash,
            "optimized_prompt_hash": prompt_hash,
            "started_at": started_at,
            "completed_at": completed_at,
            "invocation_result": "PASS" if skill_executed else "OFFLINE_COMPILED",
            "official_skill_status": status_text,
            "engine_mode": engine_mode,
            "provider": provider_name,
            "model": prompt.get("model"),
            "multimodal_capable": bool(prompt.get("multimodal_capable")),
            "prompt_engine_provider": provider_name,
            "input_fingerprint": provenance.get("input_fingerprint"),
            "validator_result": validation,
            "fallback": bool(prompt.get("fallback")),
            "fallback_reason": prompt.get("fallback_reason"),
            "provider_evidence": prompt.get("evidence"),
            "created_at": created_at,
        }
        self.store.save_prompt(project_id, record)

        # A terminal Job is history, not an edit lock on the Study.  Restore
        # the editable Study state before applying the normal prompt transition.
        if project["state"] in ("GPU_FAILED", "QUALITY_FAILED", "COMPLETED"):
            project["state"] = "PROMPT_REVIEW"
            self.store.save_project(project)
        machine = ProjectStateMachine(project["state"])
        if machine.state == "PROMPT_REVIEW":
            machine.transition("show_generation_panel", actor="architect",
                               reason="prompt generated")
        # from USER_CONFIRM (regenerate) stay in USER_CONFIRM
        project["state"] = machine.state
        self.store.save_project(project)
        self.store.append_audit(project_id, {
            "actor": "architect",
            "event": "generate_prompt",
            "from": "PROMPT_REVIEW",
            "to": "USER_CONFIRM",
            "detail": {"workflow": workflow, "prompt_hash": record["prompt_hash"]},
        })
        return record

    @staticmethod
    def _fallback_prompt(workflow: str, intent: str) -> str:
        """Inspectable fallback; never presented as official optimization."""
        return (
            f"基础模板（{workflow}）：保持建筑结构稳定，按照用户意图执行镜头运动。"
            f" 用户意图：{intent.strip() or '未提供'}"
        )

    def get_prompt(self, project_id: str) -> Dict[str, Any]:
        prompt = self.store.load_prompt(project_id)
        if prompt is None:
            raise KeyError("no prompt record yet")
        return prompt
