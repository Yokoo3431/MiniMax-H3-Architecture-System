"""Universal, offline-first MiniMax H3 prompt engine.

The MiniMax H3 prompt-writing Skill is a public specification (Markdown plus
references), not a model endpoint.  This module keeps that specification
separate from execution providers:

* :class:`OfflineH3Compiler` always works without an LLM or network.
* :class:`CLIReasoningProvider` and :class:`OpenAICompatibleProvider` are
  optional adapters with explicit configuration and image-consent gates.
* :class:`H3PromptValidator` is shared by every provider and only checks the
  contract; it never pretends to understand an image.

No provider is invoked implicitly by discovery or by AUTO mode.  AUTO falls
back to the offline compiler unless the caller explicitly selects a configured
provider.
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from runtime.prompt_provenance import stable_hash
from runtime.prompt_bridge.skill_version import check_skill_version


MODES = ("T2VA", "I2VA", "FL2VA", "L2VA", "Ref2VA")
MODE_ALIASES = {"T2V": "T2VA", "I2V": "I2VA", "R2V": "Ref2VA", "R2VA": "Ref2VA", "REF2VA": "Ref2VA"}
BASE_FIELDS = ("integrated_multimodal_description", "overall_soundscape", "non_diegetic_music")
REF_FIELDS = (
    "subject_definitions", "summary", "retention_analysis",
    "detailed_description", "overall_soundscape", "non_diegetic_music",
)
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SKILL_ROOT = _REPO_ROOT / "references" / "known_good_h3" / "comfy_official" / "skill_check"


def normalize_mode(mode: str | None) -> str:
    value = str(mode or "I2VA").strip().upper()
    return MODE_ALIASES.get(value, value)


def _sha256_bytes(value: bytes) -> str:
    import hashlib
    return hashlib.sha256(value).hexdigest().upper()


def official_skill_bundle(root: Path | None = None) -> dict[str, Any]:
    """Load the pinned public Skill specification without exposing local paths."""
    skill_root = Path(root or _SKILL_ROOT)
    files = {
        "SKILL.md": skill_root / "SKILL.md",
        "references/base-en.txt": skill_root / "base-en.txt",
        "references/ref-en.txt": skill_root / "ref-en.txt",
    }
    # Older packages only carried base-en; Ref2VA remains valid when the
    # reference guide is absent because the pinned local SKILL contract is
    # still available.  The missing file is recorded, never silently fetched.
    contents: dict[str, str] = {}
    hashes: dict[str, str] = {}
    for name, path in files.items():
        if path.is_file():
            raw = path.read_bytes()
            contents[name] = raw.decode("utf-8")
            hashes[name] = _sha256_bytes(raw)
    gate = check_skill_version()
    return {
        "source": "MiniMax-AI/MiniMax-H3/skills/h3-prompt-writing",
        "version": gate.get("pinned_revision", "unknown"),
        "files": contents,
        "hashes": hashes,
        "skill_hash": stable_hash(hashes),
        "missing_files": [name for name in files if name not in contents],
    }


@dataclass(frozen=True)
class PromptReasoningRequest:
    mode: str
    duration: float
    user_intent: str
    reference_role: str = "first_frame"
    reference_count: int = 0
    workflow_id: str | None = None
    camera_motion: str | None = None
    environment: str | None = None
    lighting: str | None = None
    audio_preference: str | None = None
    reference_description: str | None = None
    reference_image_path: str | None = None
    current_prompt: str | None = None
    image_consent: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)


class H3PromptValidationError(ValueError):
    """Raised when a provider response is not a valid H3 prompt."""


class H3PromptValidator:
    """Deterministic structural validator shared by all prompt providers."""

    _TIMESTAMP = re.compile(r"(?<!\d)(\d{1,3}(?:\.\d{1,3})?)\s*seconds?")
    _UNRESOLVED = re.compile(r"\[(?:TODO|TBD|REPLACE|INSERT)[^\]]*\]", re.I)

    def validate(self, prompt: str, *, mode: str, duration: float,
                 reference_count: int = 0) -> dict[str, Any]:
        mode = normalize_mode(mode)
        errors: list[str] = []
        if mode not in MODES:
            errors.append(f"unsupported mode: {mode}")
        if not 4 <= float(duration) <= 15:
            errors.append("duration must be between 4 and 15 seconds")
        if len(prompt or "") > 7000:
            errors.append("prompt exceeds 7000 Unicode characters")
        if "User intent focus:" in prompt or "user intent focus:" in prompt:
            errors.append("non-official custom User intent focus field")
        if self._UNRESOLVED.search(prompt or ""):
            errors.append("unresolved placeholder label")

        if mode == "Ref2VA":
            positions = [prompt.find(f"{name}:") for name in REF_FIELDS]
            if any(pos < 0 for pos in positions):
                errors.append("Ref2VA requires six named sections")
            elif positions != sorted(positions):
                errors.append("Ref2VA section order is invalid")
            if reference_count < 1:
                errors.append("Ref2VA requires at least one reference")
        else:
            positions = [prompt.find(f"{name}:") for name in BASE_FIELDS]
            if any(pos < 0 for pos in positions):
                errors.append("base mode requires three named sections")
            elif positions != sorted(positions):
                errors.append("base section order is invalid")
            if mode == "I2VA" and not prompt.startswith(
                "For the target video, at 0.00 seconds into the target video, <Picture 1>"
            ):
                errors.append("I2VA alignment instruction is missing")
            if mode == "FL2VA" and not prompt.startswith(
                "How the reference pictures align with the target video"
            ):
                errors.append("FL2VA alignment instruction is missing")
            if mode == "L2VA" and not prompt.startswith(
                "How the reference pictures align with the target video"
            ):
                errors.append("L2VA alignment instruction is missing")
            required_refs = {"I2VA": 1, "FL2VA": 2, "L2VA": 1, "T2VA": 0}.get(mode, 0)
            if reference_count < required_refs:
                errors.append(f"{mode} requires at least {required_refs} reference(s)")

        for match in self._TIMESTAMP.findall(prompt or ""):
            if float(match) > float(duration) + 0.25:
                errors.append(f"timestamp {match} exceeds duration")
                break
        return {"pass": not errors, "mode": mode, "errors": errors,
                "character_count": len(prompt or ""), "checked_duration": float(duration)}

    def require(self, prompt: str, **kwargs: Any) -> dict[str, Any]:
        result = self.validate(prompt, **kwargs)
        if not result["pass"]:
            raise H3PromptValidationError("; ".join(result["errors"]))
        return result


def _semantic_directives(text: str) -> list[str]:
    """Map explicit, known user concepts to English prompt language.

    This is intentionally narrow.  It never claims to inspect pixels or
    translate arbitrary Chinese prose; unknown content is represented by a
    neutral instruction rather than hallucinated scene details.
    """
    low = (text or "").lower()
    rules = (
        (("pool", "水池", "水边"), "move toward the pool edge and settle there"),
        (("courtyard", "庭院"), "preserve the courtyard circulation path"),
        (("terrace", "露台", "平台"), "continue toward the exterior terrace"),
        (("interior", "室内", "室内空间"), "emphasize the interior spatial sequence"),
        (("roof", "屋顶", "屋面"), "reveal the roof plane and its architectural silhouette"),
        (("site", "场地", "总图"), "show the building in relation to the site boundary"),
        (("blue hour", "蓝调时刻", "暮色"), "transition through blue hour"),
        (("night", "夜景", "入夜"), "develop the scene toward nighttime"),
        (("warm light", "暖光", "室内灯"), "introduce warm interior illumination"),
        (("slow", "缓慢", "慢速"), "keep the movement slow and controlled"),
        (("stop", "停留", "停"), "finish with a stable hold at the requested endpoint"),
        (("reveal", "展示", "展现"), "use a gradual reveal to disclose the architectural subject"),
    )
    found: list[str] = []
    for aliases, phrase in rules:
        if any(alias in low for alias in aliases):
            found.append(phrase)
    return list(dict.fromkeys(found))


class OfflineH3Compiler:
    """Compile an H3-valid prompt without image understanding or an LLM."""

    provider = "OFFLINE_COMPILER"
    multimodal_capable = False

    def __init__(self, validator: H3PromptValidator | None = None) -> None:
        self.validator = validator or H3PromptValidator()

    @staticmethod
    def _camera(request: PromptReasoningRequest) -> str:
        value = (request.camera_motion or "").lower()
        mapping = {
            "slow_push": "The camera pushes in with small amplitude at slow speed",
            "slow_pull": "The camera pulls out with small amplitude at slow speed",
            "slow_pan": "The camera pans gently with small amplitude at slow speed",
            "slow_arc": "The camera moves in a small arc at slow speed",
            "walkthrough": "The camera tracks forward at slow speed",
            "aerial_reveal": "The camera rises and reveals the wider site at slow speed",
            "static": "The camera holds a static shot",
        }
        return mapping.get(value, "The camera moves with small amplitude at slow speed")

    def _description(self, request: PromptReasoningRequest, mode: str) -> str:
        directives = _semantic_directives(request.user_intent)
        if not directives:
            directives = ["apply the user's requested architectural action without inventing image-specific details"]
        direction = "; ".join(directives)
        image_anchor = {
            "I2VA": "The approved Picture 1 is the opening frame; preserve its visible architecture, materials, composition, and spatial relationships.",
            "FL2VA": "Use the approved opening and ending pictures as fixed endpoints and describe one continuous path between them.",
            "L2VA": "Use the approved Picture 1 as the final frame and converge toward its visible composition.",
            "Ref2VA": "Use the declared references only for their assigned roles; preserve identity and spatial relationships without inventing unseen details.",
            "T2VA": "Construct the architectural scene from the user's text without implying that an image was inspected.",
        }[mode]
        lighting = request.lighting or request.environment or "natural architectural lighting"
        sound = request.audio_preference or "quiet architectural ambience with subtle environmental sound"
        return (
            f"[Shot 1] Cinematic architectural video. {image_anchor} "
            f"{self._camera(request)}. The requested direction is applied as follows: {direction}. "
            f"Lighting and environment: {lighting}. Maintain geometry, material identity, and temporal consistency. "
            "No text, subtitles, logos, or watermarks."
        ), sound

    def compile(self, request: PromptReasoningRequest) -> dict[str, Any]:
        mode = normalize_mode(request.mode)
        if mode not in MODES:
            raise H3PromptValidationError(f"unsupported mode: {mode}")
        duration = float(request.duration)
        if not 4 <= duration <= 15:
            raise H3PromptValidationError("duration must be between 4 and 15 seconds")
        ref_count = int(request.reference_count or 0)
        description, sound = self._description(request, mode)
        music = "N/A"
        if request.audio_preference and "music" in request.audio_preference.lower():
            music = request.audio_preference

        if mode == "T2VA":
            prompt = f"integrated_multimodal_description: {description}\n\noverall_soundscape: {sound}\n\nnon_diegetic_music: {music}"
        elif mode == "I2VA":
            alignment = "For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced."
            prompt = f"{alignment}\n\n{self._base_fields(description, sound, music)}"
        elif mode == "FL2VA":
            end = duration
            alignment = (
                "How the reference pictures align with the target video — Picture 1 (from Shot 1) "
                f"aligns with the 0.00-second mark of the target video; Picture 2 (from Shot 1) aligns with the {end:.2f}-second mark of the target video."
            )
            prompt = f"{alignment}\n\n{self._base_fields(description, sound, music)}"
        elif mode == "L2VA":
            alignment = (
                "How the reference pictures align with the target video — <Picture 1> (from [Shot 1]) "
                f"aligns with the {duration:.2f}-second mark of the target video."
            )
            prompt = f"{alignment}\n\n{self._base_fields(description, sound, music)}"
        else:
            prompt = (
                "subject_definitions: <Picture 1> is the approved architectural reference image.\n\n"
                "summary: Create one continuous architectural video using the declared reference role and the selected mode.\n\n"
                "retention_analysis: Preserve visible architecture, material identity, composition, and spatial relationships from the reference without inventing unseen details.\n\n"
                f"detailed_description: {description}\n\n"
                f"overall_soundscape: {sound}\n\nnon_diegetic_music: {music}"
            )
        validation = self.validator.require(prompt, mode=mode, duration=duration, reference_count=ref_count)
        alignment = "" if mode == "T2VA" else prompt.split("\n\n", 1)[0]
        return {
            "prompt": prompt,
            "optimized_prompt": prompt,
            "mode": mode,
            "workflow": request.workflow_id,
            "duration_seconds": duration,
            "reference_count": ref_count,
            "alignment_instruction": alignment,
            "alignment": alignment,
            "integrated_multimodal_description": description,
            "overall_soundscape": sound,
            "non_diegetic_music": music,
            "verified": validation,
            "validator_result": validation,
            "skill_source": "MiniMax-AI/MiniMax-H3/skills/h3-prompt-writing",
            "skill_execution": False,
            "engine_mode": "OFFLINE_COMPILER",
            "provider": self.provider,
            "model": None,
            "multimodal_capable": False,
            "evidence": "deterministic compiler; no reasoning model or image understanding used",
        }

    @staticmethod
    def _base_fields(description: str, sound: str, music: str) -> str:
        return f"integrated_multimodal_description: {description}\n\noverall_soundscape: {sound}\n\nnon_diegetic_music: {music}"


class PromptReasoningProvider:
    provider = "UNKNOWN"
    multimodal_capable = False

    def generate(self, request: PromptReasoningRequest, bundle: Mapping[str, Any]) -> dict[str, Any]:
        raise NotImplementedError


class OfflineCompilerProvider(PromptReasoningProvider):
    provider = "OFFLINE_COMPILER"

    def __init__(self, compiler: OfflineH3Compiler | None = None) -> None:
        self.compiler = compiler or OfflineH3Compiler()

    def generate(self, request: PromptReasoningRequest, bundle: Mapping[str, Any]) -> dict[str, Any]:
        return self.compiler.compile(request)


class CLIReasoningProvider(PromptReasoningProvider):
    provider = "CLI_BRIDGE"

    def __init__(self, executable: str | None = None, args: Sequence[str] | None = None,
                 timeout: int = 120, multimodal_capable: bool = False) -> None:
        self.executable = executable
        self.args = list(args or [])
        self.timeout = int(timeout)
        self.multimodal_capable = bool(multimodal_capable)

    @property
    def available(self) -> bool:
        return bool(self.executable and (Path(self.executable).is_file() or shutil.which(self.executable)))

    def generate(self, request: PromptReasoningRequest, bundle: Mapping[str, Any]) -> dict[str, Any]:
        if not self.available:
            raise RuntimeError("configured CLI provider is unavailable")
        if request.reference_image_path and self.multimodal_capable is False:
            request_payload = {"reference_image": None}
        else:
            request_payload = {"reference_image": request.reference_image_path}
        payload = {"request": request.__dict__, "official_skill_bundle": bundle, **request_payload}
        completed = subprocess.run(
            [self.executable, *self.args], input=json.dumps(payload, ensure_ascii=False),
            text=True, capture_output=True, timeout=self.timeout, check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"CLI provider exited with code {completed.returncode}")
        raw = completed.stdout.strip()
        result = json.loads(raw) if raw.startswith("{") else {"optimized_prompt": raw}
        result.update({"provider": self.provider, "model": result.get("model"),
                       "multimodal_capable": self.multimodal_capable,
                       "engine_mode": "MULTIMODAL_H3" if self.multimodal_capable else "TEXT_REASONING_H3"})
        return result


class OpenAICompatibleProvider(PromptReasoningProvider):
    provider = "OPENAI_COMPATIBLE_HTTP"

    def __init__(self, base_url: str, model: str, api_key_env: str | None = None,
                 multimodal_capable: bool = False, timeout: int = 120,
                 transport: Callable[[str, dict[str, Any], dict[str, str], int], dict[str, Any]] | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key_env = api_key_env
        self.multimodal_capable = bool(multimodal_capable)
        self.timeout = int(timeout)
        self.transport = transport

    def generate(self, request: PromptReasoningRequest, bundle: Mapping[str, Any]) -> dict[str, Any]:
        if request.reference_image_path and not request.image_consent:
            raise PermissionError("explicit image consent is required before remote analysis")
        system = "Return only a complete MiniMax H3 prompt payload following the supplied official Skill specification."
        user = {"workflow_mode": normalize_mode(request.mode), "duration": request.duration,
                "user_intent": request.user_intent, "reference_role": request.reference_role,
                "reference_description": request.reference_description, "official_skill_bundle": bundle}
        content: list[dict[str, Any]] = [{"type": "text", "text": json.dumps(user, ensure_ascii=False)}]
        if self.multimodal_capable and request.reference_image_path:
            raw = Path(request.reference_image_path).read_bytes()
            content.append({"type": "image_url", "image_url": {"url": "data:application/octet-stream;base64," + base64.b64encode(raw).decode("ascii")}})
        payload = {"model": self.model, "temperature": 0, "messages": [
            {"role": "system", "content": system}, {"role": "user", "content": content if len(content) > 1 else content[0]["text"]}
        ]}
        headers = {"Content-Type": "application/json"}
        if self.api_key_env:
            key = os.environ.get(self.api_key_env)
            if key:
                headers["Authorization"] = f"Bearer {key}"
        if self.transport:
            result = self.transport(self.base_url, payload, headers, self.timeout)
        else:
            request_obj = urllib.request.Request(self.base_url + "/chat/completions", data=json.dumps(payload).encode(), headers=headers, method="POST")
            try:
                with urllib.request.urlopen(request_obj, timeout=self.timeout) as response:
                    result = json.loads(response.read().decode("utf-8"))
            except (OSError, urllib.error.URLError) as exc:
                raise RuntimeError(f"OpenAI-compatible provider unavailable: {exc}") from exc
        choices = result.get("choices") or []
        content_value = choices[0].get("message", {}).get("content") if choices else None
        if not content_value:
            raise ValueError("provider returned no prompt content")
        return {"optimized_prompt": content_value, "provider": self.provider, "model": self.model,
                "multimodal_capable": self.multimodal_capable,
                "engine_mode": "MULTIMODAL_H3" if self.multimodal_capable else "TEXT_REASONING_H3",
                "evidence": "explicitly configured OpenAI-compatible endpoint"}


def discover_providers() -> list[dict[str, Any]]:
    """Detect configuration only; never invoke a provider."""
    discovered = [{"provider": "OFFLINE_COMPILER", "available": True, "selected_by_default": True}]
    cli = os.environ.get("AVS_PROMPT_CLI_EXECUTABLE")
    if cli:
        discovered.append({"provider": "CLI_BRIDGE", "available": bool(Path(cli).is_file() or shutil.which(cli)), "configured": True})
    base = os.environ.get("AVS_PROMPT_LOCAL_BASE_URL")
    if base:
        discovered.append({"provider": "LOCAL_OPENAI_COMPATIBLE", "available": True, "configured": True, "base_url": base})
    return discovered


class UniversalPromptEngine:
    """Provider-neutral prompt compiler with deterministic fallback."""

    def __init__(self, providers: Mapping[str, PromptReasoningProvider] | None = None,
                 bundle: Mapping[str, Any] | None = None) -> None:
        self.bundle = dict(bundle or official_skill_bundle())
        self.providers = {"OFFLINE_COMPILER": OfflineCompilerProvider(), **dict(providers or {})}
        # Environment variables only register providers.  They never cause a
        # network request or CLI invocation during discovery.
        cli = os.environ.get("AVS_PROMPT_CLI_EXECUTABLE")
        if cli and "CLI_BRIDGE" not in self.providers:
            self.providers["CLI_BRIDGE"] = CLIReasoningProvider(
                cli, os.environ.get("AVS_PROMPT_CLI_ARGS", "").split(),
                timeout=int(os.environ.get("AVS_PROMPT_CLI_TIMEOUT", "120")),
                multimodal_capable=os.environ.get("AVS_PROMPT_CLI_MULTIMODAL", "0") == "1",
            )
        local_base = os.environ.get("AVS_PROMPT_LOCAL_BASE_URL")
        if local_base and "LOCAL_OPENAI_COMPATIBLE" not in self.providers:
            self.providers["LOCAL_OPENAI_COMPATIBLE"] = OpenAICompatibleProvider(
                local_base,
                os.environ.get("AVS_PROMPT_LOCAL_MODEL", "local-h3-prompt-model"),
                api_key_env=None,
                multimodal_capable=os.environ.get("AVS_PROMPT_LOCAL_MULTIMODAL", "0") == "1",
            )

    def generate(self, request: PromptReasoningRequest, provider: str = "AUTO") -> dict[str, Any]:
        selected = str(provider or "AUTO").upper()
        if selected == "AUTO":
            selected = "OFFLINE_COMPILER"
        selected_provider = self.providers.get(selected)
        fallback_reason = None
        if selected_provider is None:
            fallback_reason = f"provider {selected} is not configured"
            selected_provider = self.providers["OFFLINE_COMPILER"]
        try:
            result = selected_provider.generate(request, self.bundle)
            prompt = str(result.get("optimized_prompt") or result.get("prompt") or "")
            mode = normalize_mode(request.mode)
            validation = H3PromptValidator().require(prompt, mode=mode, duration=request.duration, reference_count=request.reference_count)
            result = dict(result)
            result.update({"prompt": prompt, "optimized_prompt": prompt, "validator_result": validation,
                           "verified": validation, "skill_hash": self.bundle["skill_hash"],
                           "skill_version": self.bundle["version"], "skill_source": self.bundle["source"],
                           "skill_execution": selected != "OFFLINE_COMPILER",
                           "fallback": False, "fallback_reason": fallback_reason})
            return result
        except Exception as exc:  # optional providers must never block generation
            offline = self.providers["OFFLINE_COMPILER"].generate(request, self.bundle)
            offline.update({"fallback": True, "fallback_reason": f"{type(exc).__name__}: {exc}",
                            "skill_execution": False,
                            "engine_mode": "OFFLINE_COMPILER"})
            return offline
