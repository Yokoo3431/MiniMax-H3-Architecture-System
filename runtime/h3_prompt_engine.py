"""Universal, offline-first MiniMax H3 prompt engine.

The MiniMax H3 prompt-writing Skill is a public specification (Markdown plus
references), not a model endpoint.  This module keeps that specification
separate from execution providers:

* :class:`OfflineH3Compiler` always works without an LLM or network.
* :class:`CLIReasoningProvider` and :class:`OpenAICompatibleProvider` are
  optional adapters with explicit configuration and image-consent gates.
* :class:`H3PromptValidator` is shared by every provider and only checks the
  contract; it never pretends to understand an image.

Discovery never invokes a provider.  AUTO may use an explicitly configured
local provider when one is available; otherwise it deterministically falls
back to the offline compiler.  Cloud providers remain explicit and consent
gated.
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
CLI_PROVIDER_IDS = ("CODEX", "ANTIGRAVITY", "DEEPSEEK_HARNESS", "CUSTOM_CLI", "CLI_BRIDGE")
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
    source = "MiniMax-AI/MiniMax-H3/skills/h3-prompt-writing"
    version = gate.get("pinned_revision", "unknown")
    missing_files = [name for name in files if name not in contents]
    bundle_manifest = {
        "source": source, "version": version, "hashes": hashes,
        "missing_files": missing_files,
    }
    payload_manifest = {
        "source": source, "version": version,
        "hashes": {name: hashes[name] for name in (
            "SKILL.md", "references/base-en.txt") if name in hashes},
    }
    return {
        "source": source,
        "version": version,
        "files": contents,
        "hashes": hashes,
        "skill_hash": stable_hash(hashes),
        "bundle_manifest_sha256": stable_hash(bundle_manifest),
        "payload_manifest_sha256": stable_hash(payload_manifest),
        "missing_files": missing_files,
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
        (("slow", "缓慢", "慢速", "很慢", "稍慢", "慢一点"), "keep the movement slow and controlled"),
        (("fast", "faster", "quick", "quickly", "加快", "快点", "快一点", "稍微快", "快速", "迅速", "加速", "很快"), "use a slightly faster controlled camera movement"),
        (("day", "白天", "日景", "daylight"), "retain the current daylight character at the start"),
        (("outdoor", "室外", "户外", "外部", "露台"), "transition toward the exterior space without changing the building identity"),
        (("drone", "航拍", "无人机", "空中"), "emphasize a high aerial viewpoint and the building's relationship to the site"),
        (("day-night", "昼夜"), "transition the illumination from daylight toward evening and night"),
        (("stop", "停留", "停"), "finish with a stable hold at the requested endpoint"),
        (("reveal", "展示", "展现"), "use a gradual reveal to disclose the architectural subject"),
    )
    found: list[str] = []
    for aliases, phrase in rules:
        if any(alias in low for alias in aliases):
            found.append(phrase)
    return list(dict.fromkeys(found))


def parse_control_intent(text: str) -> dict[str, str | None]:
    """Extract only explicit, deterministic controls from natural language.

    This parser is intentionally conservative.  It supplies camera wording
    and contradiction checks; it does not infer scene content or invent H3
    workflow enum values.
    """
    value = (text or "").lower()
    speed = None
    if any(token in value for token in ("很快", "快速", "迅速", "加速", "加快", "快一点", "快点", "稍微快", "faster", "quick")):
        speed = "fast"
    elif any(token in value for token in ("很慢", "缓慢", "慢速", "稍慢", "慢一点", "slow")):
        speed = "slow"
    elif "正常" in value or "normal" in value:
        speed = "normal"

    direction = None
    direction_tokens = (
        (("推进", "向前", "前进", "push", "forward"), "forward"),
        (("后退", "拉远", "pull", "backward"), "backward"),
        (("平移", "pan", "横移"), "pan"),
        (("环绕", "arc", "orbit"), "arc"),
        (("升高", "上升", "rise", "升空"), "rise"),
        (("降低", "下降", "lower", "descend"), "lower"),
    )
    for aliases, parsed in direction_tokens:
        if any(token in value for token in aliases):
            direction = parsed
            break

    ending = None
    if any(token in value for token in ("停留", "停下", "定格", "hold", "settle")):
        ending = "hold"
    elif any(token in value for token in ("持续移动", "keep moving", "continue moving")):
        ending = "continue"
    return {"speed": speed, "direction": direction, "ending": ending}


def validate_prompt_intent(prompt: str, user_intent: str) -> list[str]:
    """Return contradictions between explicit controls and generated text."""
    controls = parse_control_intent(user_intent)
    text = (prompt or "").lower()
    errors: list[str] = []
    if controls["speed"] == "fast" and "slow speed" in text and "faster" not in text:
        errors.append("PROMPT_INTENT_CONTRADICTION: explicit faster movement became slow speed")
    if controls["speed"] == "slow" and "faster controlled" in text:
        errors.append("PROMPT_INTENT_CONTRADICTION: explicit slow movement became faster movement")
    if controls["ending"] == "hold" and not any(token in text for token in ("stable hold", "settle", "hold at")):
        errors.append("PROMPT_INTENT_CONTRADICTION: explicit endpoint hold is missing")
    return errors


class OfflineH3Compiler:
    """Compile an H3-valid prompt without image understanding or an LLM."""

    provider = "OFFLINE_COMPILER"
    multimodal_capable = False

    def __init__(self, validator: H3PromptValidator | None = None) -> None:
        self.validator = validator or H3PromptValidator()

    @staticmethod
    def _camera(request: PromptReasoningRequest) -> str:
        value = (request.camera_motion or "").lower()
        intent = (request.user_intent or "").lower()
        controls = parse_control_intent(intent)
        speed = controls["speed"]
        speed_suffix = {
            "fast": "at a slightly faster controlled speed",
            "normal": "at a natural controlled speed",
            "slow": "at slow speed",
            None: "at slow speed",
        }[speed]
        mapping = {
            "slow_push": f"The camera pushes in with small amplitude {speed_suffix}",
            "slow_pull": f"The camera pulls out with small amplitude {speed_suffix}",
            "slow_pan": f"The camera pans gently with small amplitude {speed_suffix}",
            "slow_arc": f"The camera moves in a small arc {speed_suffix}",
            "walkthrough": f"The camera tracks forward {speed_suffix}",
            "aerial_reveal": "The camera rises and reveals the wider site at slow speed",
            "static": "The camera holds a static shot",
        }
        if value in mapping:
            return mapping[value]
        return f"The camera moves with small amplitude {speed_suffix}"

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
        contradictions = validate_prompt_intent(prompt, request.user_intent)
        if contradictions:
            raise H3PromptValidationError("; ".join(contradictions))
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
            "control_intent": parse_control_intent(request.user_intent),
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

    def describe(self) -> dict[str, Any]:
        """Return safe configuration metadata; never include credentials."""
        return {"provider": self.provider, "model": None,
                "multimodal_capable": bool(self.multimodal_capable),
                "configured": False, "available": False}


class OfflineCompilerProvider(PromptReasoningProvider):
    provider = "OFFLINE_COMPILER"

    def __init__(self, compiler: OfflineH3Compiler | None = None) -> None:
        self.compiler = compiler or OfflineH3Compiler()

    def generate(self, request: PromptReasoningRequest, bundle: Mapping[str, Any]) -> dict[str, Any]:
        return self.compiler.compile(request)

    def describe(self) -> dict[str, Any]:
        return {"provider": self.provider, "model": None, "configured": True,
                "available": True, "multimodal_capable": False}


class CLIReasoningProvider(PromptReasoningProvider):
    provider = "CLI_BRIDGE"

    def __init__(self, executable: str | None = None, args: Sequence[str] | None = None,
                 timeout: int = 120, multimodal_capable: bool = False,
                 provider_name: str = "CLI_BRIDGE") -> None:
        self.provider = str(provider_name or "CLI_BRIDGE").upper()
        self.executable = executable
        self.args = list(args or [])
        self.timeout = int(timeout)
        self.multimodal_capable = bool(multimodal_capable)

    @property
    def available(self) -> bool:
        return bool(self.executable and (Path(self.executable).is_file() or shutil.which(self.executable)))

    def describe(self) -> dict[str, Any]:
        return {"provider": self.provider, "model": None,
                "executable": self.executable or "", "arguments": list(self.args),
                "multimodal_capable": bool(self.multimodal_capable),
                "configured": bool(self.executable), "available": self.available}

    def test_connection(self) -> dict[str, Any]:
        if not self.available:
            return {"ok": False, "message": "CLI 可执行文件不存在或不可运行"}
        try:
            result = subprocess.run([self.executable, "--version"],
                                    capture_output=True, text=True,
                                    timeout=min(self.timeout, 15), check=False)
            identity = (result.stdout or result.stderr or "").strip().splitlines()
            return {"ok": result.returncode == 0,
                    "message": identity[0][:240] if identity else f"exit={result.returncode}"}
        except (OSError, subprocess.SubprocessError) as exc:
            return {"ok": False, "message": f"CLI 测试失败：{type(exc).__name__}"}

    def _is_antigravity(self) -> bool:
        return self.provider == "ANTIGRAVITY" or Path(self.executable or "").stem.lower() == "agy"

    @staticmethod
    def _strip_code_fence(value: str) -> str:
        value = value.strip()
        fence = chr(96) * 3
        if value.startswith(fence) and value.endswith(fence):
            value = value[len(fence):].strip()
            if value.lower().startswith("json"):
                value = value[4:].strip()
            return value[:-len(fence)].strip()
        return value

    @classmethod
    def _parse_output(cls, raw: str) -> tuple[str, dict[str, Any]]:
        """Extract a final prompt from the observed AGY print envelope."""
        raw = (raw or "").strip()
        if not raw:
            raise ValueError("CLI provider returned an empty response")
        outer: dict[str, Any] = {}
        candidate = raw
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                outer = parsed
                candidate = str(parsed.get("response") or parsed.get("optimized_prompt") or parsed.get("prompt") or "")
                if not candidate and "choices" in parsed:
                    candidate = str(((parsed.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
                if not candidate:
                    raise ValueError("CLI JSON response contained no prompt field")
        except json.JSONDecodeError:
            candidate = raw
        candidate = cls._strip_code_fence(candidate)
        try:
            inner = json.loads(candidate)
            if isinstance(inner, dict):
                prompt = str(inner.get("optimized_prompt") or inner.get("prompt") or "")
                if prompt:
                    return prompt, {**outer, **inner}
        except json.JSONDecodeError:
            pass
        if not candidate:
            raise ValueError("CLI provider returned no final prompt")
        return candidate, outer

    def _request_text(self, request: PromptReasoningRequest, bundle: Mapping[str, Any]) -> str:
        request_data = dict(request.__dict__)
        # Text-only providers must never receive a local image path.
        if not self.multimodal_capable or not request.image_consent:
            request_data["reference_image_path"] = None
        return (
            "Follow the supplied official MiniMax H3 Skill specification. "
            "Return ONLY the final H3 prompt payload, with no explanation, "
            "markdown fence, or session metadata.\n"
            f"REQUEST_JSON={json.dumps(request_data, ensure_ascii=False)}\n"
            f"OFFICIAL_SKILL_BUNDLE={json.dumps(dict(bundle), ensure_ascii=False)}"
        )

    def _build_command(self, prompt_text: str) -> list[str]:
        command = [str(self.executable)]
        args = list(self.args)
        if not self._is_antigravity():
            return command + args
        # AGY 1.1.22 requires the prompt to be attached to --print.
        print_index = next((i for i, item in enumerate(args)
                            if item == "--print" or item == "--prompt" or
                            item.startswith("--print=") or item.startswith("--prompt=")), None)
        if print_index is None:
            args.append(f"--print={prompt_text}")
        else:
            args[print_index] = f"--print={prompt_text}"
        if not any(item == "--output-format" or item.startswith("--output-format=") for item in args):
            args.extend(["--output-format", "json"])
        if not any(item == "--disable-slash-commands" for item in args):
            args.append("--disable-slash-commands")
        if not any(item == "--effort" or item.startswith("--effort=") for item in args):
            args.extend(["--effort", "medium"])
        if not any(item == "--model" or item.startswith("--model=") for item in args):
            args.extend(["--model", "gemini-3.7-flash-medium"])
        return command + args

    def generate(self, request: PromptReasoningRequest, bundle: Mapping[str, Any]) -> dict[str, Any]:
        if not self.available:
            raise RuntimeError("configured CLI provider is unavailable")
        prompt_text = self._request_text(request, bundle)
        command = self._build_command(prompt_text)
        input_payload = None if self._is_antigravity() else json.dumps(
            {"request": dict(request.__dict__), "official_skill_bundle": bundle,
             "reference_image": request.reference_image_path if self.multimodal_capable and request.image_consent else None},
            ensure_ascii=False)
        completed = subprocess.run(
            command, input=input_payload, text=True, encoding="utf-8", errors="replace", capture_output=True,
            timeout=self.timeout, check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"CLI provider exited with code {completed.returncode}")
        raw = completed.stdout.strip()
        prompt, parsed = self._parse_output(raw)
        if not prompt.strip():
            raise ValueError("CLI provider returned an empty final prompt")
        result = dict(parsed)
        result["optimized_prompt"] = prompt
        result.update({"provider": self.provider,
                       "model": result.get("model") or (
                           "gemini-3.7-flash-medium" if self._is_antigravity() else None),
                       "multimodal_capable": self.multimodal_capable,
                       "engine_mode": "MULTIMODAL_H3" if self.multimodal_capable else "TEXT_REASONING_H3",
                       "evidence": {
                           "executable_name": Path(self.executable or "").name,
                           "exit_code": completed.returncode,
                           "stdout_length": len(completed.stdout or ""),
                           "stderr_length": len(completed.stderr or ""),
                           "raw_output_hash": stable_hash(raw),
                           "command_mode": "agy_print" if self._is_antigravity() else "stdin_json",
                       }})
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

    def describe(self) -> dict[str, Any]:
        return {"provider": self.provider, "model": self.model,
                "base_url": self.base_url, "api_key_configured": bool(self.api_key_env),
                "api_key_env": self.api_key_env or "",
                "multimodal_capable": bool(self.multimodal_capable),
                "configured": bool(self.base_url and self.model), "available": True}

    def test_connection(self) -> dict[str, Any]:
        if self.transport is not None:
            return {"ok": True, "message": "已连接测试传输适配器", "model": self.model}
        headers = {}
        if self.api_key_env and os.environ.get(self.api_key_env):
            headers["Authorization"] = "Bearer " + os.environ[self.api_key_env]
        request_obj = urllib.request.Request(self.base_url + "/models", headers=headers, method="GET")
        try:
            with urllib.request.urlopen(request_obj, timeout=min(self.timeout, 15)) as response:
                response.read(1024)
            return {"ok": True, "message": "Endpoint 可访问", "model": self.model}
        except (OSError, urllib.error.URLError) as exc:
            return {"ok": False, "message": f"Endpoint 测试失败：{type(exc).__name__}", "model": self.model}


def provider_summary(config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Normalize a provider config for UI; secrets are intentionally omitted."""
    raw = dict(config or {})
    provider = str(raw.get("provider") or "OFFLINE_COMPILER").upper()
    if provider == "OFFLINE_COMPILER":
        return {"provider": provider, "model": None, "configured": True,
                "available": True, "multimodal_capable": False}
    if provider in CLI_PROVIDER_IDS:
        return CLIReasoningProvider(
            raw.get("executable"), raw.get("arguments") or raw.get("args") or [],
            timeout=int(raw.get("timeout", 120)),
            multimodal_capable=bool(raw.get("multimodal_capable")),
            provider_name=provider,
        ).describe()
    return OpenAICompatibleProvider(
        str(raw.get("base_url") or ""), str(raw.get("model") or ""),
        api_key_env=raw.get("api_key_env"),
        multimodal_capable=bool(raw.get("multimodal_capable")),
        timeout=int(raw.get("timeout", 120)),
    ).describe()


def test_provider_configuration(config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Test only the selected provider's transport, never run prompt generation."""
    summary = provider_summary(config)
    if summary["provider"] == "OFFLINE_COMPILER":
        return {"ok": True, "message": "离线 H3 编译器始终可用", **summary}
    raw = dict(config or {})
    if summary["provider"] in CLI_PROVIDER_IDS:
        result = CLIReasoningProvider(raw.get("executable"), raw.get("arguments") or raw.get("args") or [],
                                      timeout=int(raw.get("timeout", 120)),
                                      multimodal_capable=bool(raw.get("multimodal_capable")),
                                      provider_name=summary["provider"]).test_connection()
    else:
        result = OpenAICompatibleProvider(str(raw.get("base_url") or ""), str(raw.get("model") or ""),
                                          api_key_env=raw.get("api_key_env"),
                                          multimodal_capable=bool(raw.get("multimodal_capable")),
                                          timeout=int(raw.get("timeout", 120))).test_connection()
    return {**summary, **result}


def discover_providers() -> list[dict[str, Any]]:
    """Detect configuration only; never invoke a provider."""
    discovered = [{"provider": "OFFLINE_COMPILER", "available": True, "selected_by_default": True}]
    configured_cli = os.environ.get("AVS_PROMPT_CLI_EXECUTABLE")
    local_appdata = os.environ.get("LOCALAPPDATA")
    agy_candidates = [os.environ.get("AVS_ANTIGRAVITY_EXECUTABLE"), shutil.which("agy")]
    if local_appdata:
        agy_candidates.append(str(Path(local_appdata) / "agy" / "bin" / "agy.exe"))
    agy_executable = next((value for value in agy_candidates
                           if value and (Path(value).is_file() or shutil.which(value))), None)
    known_cli = {
        "CODEX": os.environ.get("AVS_CODEX_EXECUTABLE") or shutil.which("codex"),
        "ANTIGRAVITY": agy_executable,
        "DEEPSEEK_HARNESS": os.environ.get("AVS_DEEPSEEK_EXECUTABLE") or shutil.which("deepseek"),
        "CLI_BRIDGE": configured_cli,
    }
    for provider, executable in known_cli.items():
        if executable:
            discovered.append({"provider": provider, "executable": str(executable),
                               "available": bool(Path(executable).is_file() or shutil.which(executable)),
                               "configured": True})
    # CUSTOM_CLI is deliberately not discovered from arbitrary environment
    # state.  The user can configure it explicitly in the Provider panel.
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
            # Auto may use explicitly configured local providers, but never
            # silently selects a cloud endpoint or invokes an unconfigured
            # executable. Offline compilation remains the deterministic
            # fallback when no local provider is configured.
            local_candidates = (
                "LOCAL_OPENAI_COMPATIBLE", "CODEX", "ANTIGRAVITY",
                "DEEPSEEK_HARNESS", "CUSTOM_CLI", "CLI_BRIDGE",
            )
            selected = next(
                (name for name in local_candidates
                 if name in self.providers
                 and bool(self.providers[name].describe().get("configured"))
                 and bool(self.providers[name].describe().get("available"))),
                "OFFLINE_COMPILER",
            )
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
            # Providers may return only the final H3 payload. Normalize the
            # common product result contract once at the engine boundary.
            sections = {}
            field_names = ("integrated_multimodal_description", "overall_soundscape", "non_diegetic_music")
            for index, field in enumerate(field_names):
                start = prompt.find(f"{field}:")
                if start < 0:
                    continue
                start += len(field) + 1
                end = len(prompt)
                for next_field in field_names[index + 1:]:
                    marker = prompt.find(f"{next_field}:", start)
                    if marker >= 0:
                        end = min(end, marker)
                sections[field] = prompt[start:end].strip()
            result.update({
                "mode": mode,
                "workflow": result.get("workflow") or request.workflow_id,
                "duration_seconds": result.get("duration_seconds", request.duration),
                "reference_count": result.get("reference_count", request.reference_count),
                "alignment": result.get("alignment") or (prompt.split("\n\n", 1)[0] if mode != "T2VA" else ""),
                "integrated_multimodal_description": result.get("integrated_multimodal_description") or sections.get("integrated_multimodal_description", ""),
                "overall_soundscape": result.get("overall_soundscape") or sections.get("overall_soundscape", ""),
                "non_diegetic_music": result.get("non_diegetic_music") or sections.get("non_diegetic_music", ""),
            })
            result.update({"prompt": prompt, "optimized_prompt": prompt, "validator_result": validation,
                           "verified": validation, "skill_hash": self.bundle["skill_hash"],
                           "bundle_manifest_sha256": self.bundle["bundle_manifest_sha256"],
                           "payload_manifest_sha256": self.bundle["payload_manifest_sha256"],
                           "skill_version": self.bundle["version"], "skill_source": self.bundle["source"],
                            "skill_execution": selected != "OFFLINE_COMPILER" and not fallback_reason,
                            "fallback": bool(fallback_reason), "fallback_reason": fallback_reason})
            return result
        except Exception as exc:  # optional providers must never block generation
            offline = self.providers["OFFLINE_COMPILER"].generate(request, self.bundle)
            offline.update({"fallback": True, "fallback_reason": f"{type(exc).__name__}: {exc}",
                            "bundle_manifest_sha256": self.bundle["bundle_manifest_sha256"],
                            "payload_manifest_sha256": self.bundle["payload_manifest_sha256"],
                            "skill_execution": False,
                            "engine_mode": "OFFLINE_COMPILER"})
            return offline
