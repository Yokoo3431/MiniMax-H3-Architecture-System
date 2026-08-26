"""PATCH2.8-I2 installer service behind Environment Center.

The service owns planning, trusted HTTPS downloads, resume state, SHA-256
verification, safe extraction, atomic promotion, cancellation and repair.  It
never changes the frozen inference/runtime contracts or workflow assets.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import tarfile
import threading
import time
import uuid
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional
from urllib.parse import parse_qsl, urlparse

from ._paths import REPO_ROOT
from .environment_resolution import pread_compatible, resolve_install_roots
from .setup_state import SetupState
from .yaml_compat import safe_load
from runtime.storage_policy import ensure_cache_dirs, process_environment
from runtime.h3_sidecar import (
    load_h3_sidecar_manifest,
    sidecar_target_root,
    validate_h3_sidecar_tree,
)
from runtime.h3_asset_contract import evaluate_h3_asset_contract
from runtime.support_layer import (
    apply_unified_patch,
    load_release_runtime_manifest,
    load_support_manifest,
    source_tree_fingerprint,
    support_entries,
    validate_support_entry,
    validate_support_manifest,
)


STATUSES = (
    "NOT_INSTALLED", "QUEUED", "DOWNLOADING", "VERIFYING", "EXTRACTING",
    "INSTALLING", "READY", "FAILED", "CANCELLED",
)


class InstallerError(RuntimeError):
    """A safe, user-facing installation failure."""

    def __init__(self, code: str, message: str, details: Optional[dict] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def _sha256(path: Path, progress: Optional[Callable[[int], None]] = None) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            block = fh.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
            if progress:
                progress(len(block))
    return digest.hexdigest().upper()


def _redact(value: Any) -> str:
    text = str(value)
    text = re.sub(r"(?i)(authorization\s*[:=]\s*)([^\s,;]+)", r"\1<REDACTED>", text)
    text = re.sub(r"(?i)([?&](?:token|access_token|api_key|signature|sig)=)[^&\s]+", r"\1<REDACTED>", text)
    return text


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlparse(newurl).scheme.lower() != "https":
            raise InstallerError("NETWORK_ERROR", "Redirect to an insecure URL was rejected.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class InstallationService:
    """Installer state machine used by the System API.

    The constructor accepts injectable paths, opener, disk provider and sleep
    functions so the complete behavior can be tested without live Internet or
    production model files.
    """

    RUNTIME_COMPONENT = "comfyui_runtime"
    H3_SUPPORT_COMPONENT = "minimax_h3_nodes"
    VHS_SUPPORT_COMPONENT = "video_helper_suite"
    SUPPORT_DEPENDENCY_COMPONENT = "support_layer_dependencies"
    PREAD_COMPONENT = "pread_shim"
    SKILL_COMPONENT = "prompt_skill"
    MODEL_COMPONENTS = ("dit", "text_encoder", "video_vae", "audio_vae")
    H3_SIDECAR_COMPONENT = "h3_model_configuration"
    SUPPORT_COMPONENTS = (H3_SUPPORT_COMPONENT, VHS_SUPPORT_COMPONENT)

    def __init__(self, store, env_overrides: Optional[Dict[str, Any]] = None,
                 manifest_path: Optional[Path] = None,
                 repo_root: Optional[Path] = None,
                 job_root: Optional[Path] = None,
                 cache_root: Optional[Path] = None,
                 log_path: Optional[Path] = None,
                 opener=None,
                 extractor: Optional[str] = None,
                 disk_usage: Optional[Callable[[str], Any]] = None,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.store = store
        self.overrides = env_overrides or {}
        self.repo_root = Path(repo_root or REPO_ROOT).resolve()
        self.manifest_path = Path(manifest_path or self.repo_root / "configs" / "installation_manifest.yaml")
        self.job_root = Path(job_root or self.repo_root / "userdata" / "system" / "install_jobs")
        if cache_root is None:
            ensure_cache_dirs(self.repo_root)
        self.cache_root = Path(cache_root or self.repo_root / "userdata" / "cache" / "downloads")
        self.extract_root = self.repo_root / "userdata" / "cache" / "extract"
        self.log_path = Path(log_path or self.repo_root / "logs" / "installer.log")
        self._opener = opener or urllib.request.build_opener(_SafeRedirectHandler())
        project_extractor = self.repo_root / "userdata" / "cache" / "extract" / "7zr.exe"
        self._extractor = (extractor or os.environ.get("H3_7Z_EXE")
                           or (str(project_extractor) if project_extractor.is_file() else None)
                           or shutil.which("7z") or shutil.which("7zz"))
        self._disk_usage = disk_usage or shutil.disk_usage
        self._sleep = sleep
        self._threads: Dict[str, threading.Thread] = {}
        self._cancel: Dict[str, threading.Event] = {}
        self.state = SetupState(store)

    # ------------------------------------------------------------------ #
    # Manifest / paths
    # ------------------------------------------------------------------ #
    def manifest(self) -> dict:
        if not self.manifest_path.is_file():
            raise InstallerError("INSTALL_MANIFEST_MISSING", "Installation manifest is missing.")
        try:
            data = safe_load(self.manifest_path.read_text(encoding="utf-8")) or {}
        except Exception as exc:
            raise InstallerError("INSTALL_MANIFEST_INVALID", "Installation manifest could not be read.", {"error": str(exc)}) from exc
        if data.get("schema_version") != 1:
            raise InstallerError("INSTALL_MANIFEST_INVALID", "Unsupported installation manifest schema.")
        if data.get("support_layers"):
            try:
                validate_support_manifest(load_support_manifest(self.repo_root))
            except (OSError, TypeError, ValueError) as exc:
                raise InstallerError(
                    "SUPPORT_MANIFEST_INVALID",
                    "Pinned support-layer provenance is invalid.",
                    {"type": type(exc).__name__, "detail": str(exc)},
                ) from exc
        return data

    def _support_manifest(self) -> Optional[dict]:
        if not self.manifest().get("support_layers"):
            return None
        try:
            data = load_support_manifest(self.repo_root)
            validate_support_manifest(data)
            return data
        except (OSError, TypeError, ValueError) as exc:
            raise InstallerError("SUPPORT_MANIFEST_INVALID", "Pinned support-layer provenance is invalid.", {"detail": str(exc)}) from exc

    def _h3_sidecar_manifest(self) -> dict:
        try:
            return load_h3_sidecar_manifest(self.repo_root)
        except (OSError, TypeError, ValueError) as exc:
            raise InstallerError(
                "H3_SUPPORT_DATA_INCOMPLETE",
                "Pinned MiniMax H3 model configuration metadata is invalid.",
                {"detail": str(exc)},
            ) from exc

    def _h3_sidecar_state(self, models: Path, verify: bool = True) -> dict:
        manifest = self._h3_sidecar_manifest()
        target = sidecar_target_root(models)
        if verify:
            state = validate_h3_sidecar_tree(models, manifest)
            if state["ready"]:
                state.update({"status": "READY", "code": None})
                return state
        # Existing layouts are adopted only when the same required asset
        # contract used by the runtime detector is complete.  In particular,
        # tokenizer_config/vocab/merges without tokenizer.json is incompatible
        # with the pinned use_fast=True loader.
        asset_state = evaluate_h3_asset_contract(models, self.repo_root)
        if asset_state["ready"]:
            return {
                "target": str(target), "status": "READY", "code": None,
                "provenance_status": "EXISTING_COMPATIBLE_LAYOUT",
                "missing": [], "mismatched": [], "asset_contract": asset_state,
            }
        return {
            "target": str(target), "status": "FAILED",
            "code": "INCOMPATIBLE_RUNTIME",
            "missing": sorted(set((state.get("missing", []) if verify else []) + asset_state["missing"])),
            "mismatched": state.get("mismatched", []) if verify else [],
            "asset_contract": asset_state,
        }

    @staticmethod
    def _support_target(native: Path, entry: dict) -> Path:
        custom_nodes = native / "ComfyUI" / "custom_nodes"
        directory = str(entry.get("directory") or "")
        if not directory or Path(directory).name != directory:
            raise InstallerError("SUPPORT_MANIFEST_INVALID", "Support install directory is invalid.")
        return InstallationService._safe_component_path(custom_nodes, directory)

    def _support_state(self, native: Path, layer_id: str, entry: dict) -> dict:
        target = self._support_target(native, entry)
        # The release contract is owned by the shared custom_nodes lock.  A
        # historical lock inside ComfyUI_RH_MinMaxH3 may describe an older
        # node-only snapshot and must not make a healthy managed Runtime look
        # reinstallable.  Keep the per-target path only as a legacy fallback
        # for older trees that have no shared lock yet.
        shared_lock = target.parent / "support_layer.lock.json"
        legacy_lock = target / "support_layer.lock.json"
        lock = shared_lock if shared_lock.is_file() else legacy_lock
        if not target.is_dir():
            return {"status": "NOT_INSTALLED", "code": "NOT_INSTALLED", "target": str(target)}
        if not lock.is_file():
            # Existing production trees predate the installer lockfile.  A
            # read-only adoption may still recognize the frozen registration
            # contract; the installer will not replace a READY target.
            required = set(entry.get("required_nodes") or [])
            found: set[str] = set()
            for source in target.rglob("*.py"):
                try:
                    text = source.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                found.update(name for name in required if name in text)
            if found == required:
                return {"status": "READY", "code": "READY",
                        "target": str(target), "provenance": "adopted_existing_tree"}
            return {"status": "FAILED", "code": "SUPPORT_LAYER_UNVERIFIED", "target": str(target)}
        try:
            data = json.loads(lock.read_text(encoding="utf-8"))
            # Current managed trees use one shared lock with one record per
            # support layer. Older node directories used that record directly.
            record = data.get("h3" if layer_id == self.H3_SUPPORT_COMPONENT
                              else "video_helper_suite") or data
            release_h3 = (load_release_runtime_manifest(self.repo_root).get("h3") or {})
            expected_commit = release_h3.get("upstream_commit") or entry.get("commit")
            expected = release_h3.get("managed_runtime_fingerprint")
            expected = expected or entry.get("production_snapshot", {}).get("source_tree_fingerprint_without_backups")
            if not expected:
                expected = entry.get("source_tree_fingerprint", {}).get("value")
            if record.get("commit") != expected_commit or record.get("source_tree_fingerprint") != expected:
                return {"status": "FAILED", "code": "SUPPORT_LAYER_PROVENANCE_MISMATCH", "target": str(target)}
            if layer_id == self.H3_SUPPORT_COMPONENT:
                patch = entry.get("production_snapshot", {}).get("local_patch", {})
                actual_patch = record.get("project_patch_sha256") or record.get("patch_sha256")
                if actual_patch != patch.get("sha256"):
                    return {"status": "FAILED", "code": "SUPPORT_LAYER_PROVENANCE_MISMATCH", "target": str(target)}
            return {"status": "READY", "code": "READY", "target": str(target), "commit": record.get("commit")}
        except (OSError, ValueError, TypeError):
            return {"status": "FAILED", "code": "SUPPORT_LAYER_PROVENANCE_MISMATCH", "target": str(target)}

    def _support_dependency_state(self, native: Path, support_manifest: dict) -> dict:
        python = native / "python_embeded" / "python.exe"
        if not python.is_file():
            return {"status": "NOT_INSTALLED", "code": "NOT_INSTALLED"}
        specs = support_manifest.get("dependency_policy", {}).get("install_required", [])
        try:
            probe = subprocess.run(
                [str(python), "-c", (
                    "import importlib.metadata as m, json; "
                    "names=" + repr([str(s).split("==", 1)[0] for s in specs]) + "; "
                    "d={x.metadata['Name'].lower():x.version for x in m.distributions() if x.metadata.get('Name')}; "
                    "print(json.dumps({n:d.get(n.lower()) for n in names}))"
                )], capture_output=True, text=True, timeout=60, check=False,
            )
            values = json.loads((probe.stdout or "{}").splitlines()[-1])
        except (OSError, subprocess.SubprocessError, ValueError, IndexError):
            return {"status": "FAILED", "code": "SUPPORT_DEPENDENCY_AUDIT_FAILED"}
        expected = {str(s).split("==", 1)[0]: str(s).split("==", 1)[1] for s in specs if "==" in str(s)}
        if all(values.get(name) == version for name, version in expected.items()):
            return {"status": "READY", "code": "READY", "versions": values}
        return {"status": "NOT_INSTALLED", "code": "SUPPORT_DEPENDENCIES_REQUIRED", "versions": values}

    def _configured_roots(self) -> tuple[Path, Path]:
        state = self.state.load()
        try:
            project_local = self.store.data_root.resolve().is_relative_to(self.repo_root)
        except (AttributeError, OSError):
            project_local = False
        native_root, models_root, _active = resolve_install_roots(
            self.repo_root, state, os.environ,
            use_legacy_config=project_local,
            auto_discover=project_local)
        return native_root, models_root

    @staticmethod
    def _safe_component_path(root: Path, relative: str) -> Path:
        target = (root / relative).resolve()
        if not str(target).startswith(str(root.resolve())):
            raise InstallerError("PERMISSION_ERROR", "Installer target escaped its configured root.")
        return target

    def _runtime_state(self, root: Path) -> dict:
        main = root / "ComfyUI" / "main.py"
        shim = root / "ComfyUI" / "custom_nodes" / "windows_safe_load"
        marker = root / "runtime_version.json"
        version = None
        if marker.is_file():
            try:
                version = json.loads(marker.read_text(encoding="utf-8")).get("comfyui")
            except Exception:
                version = "UNVERIFIED"
        if version and version != str(self.manifest()["runtime"]["comfyui"]["version"]):
            return {"status": "FAILED", "code": "INCOMPATIBLE_RUNTIME", "version": version}
        if main.is_file() and (shim.is_dir() or pread_compatible(root, os.environ)):
            return {"status": "READY", "code": "READY", "version": version or "UNVERIFIED"}
        if main.is_file() and not (shim.is_dir() or pread_compatible(root, os.environ)):
            return {"status": "FAILED", "code": "INCOMPATIBLE_RUNTIME", "version": version or "UNVERIFIED"}
        return {"status": "NOT_INSTALLED", "code": "NOT_INSTALLED", "version": version}

    def _model_state(self, path: Path, meta: dict, verify: bool = True) -> dict:
        if not path.is_file():
            return {"status": "NOT_INSTALLED", "code": "NOT_INSTALLED"}
        expected_size = int(meta.get("expected_size") or 0)
        if expected_size and path.stat().st_size != expected_size:
            return {"status": "FAILED", "code": "CHECKSUM_MISMATCH", "detail": "size mismatch"}
        if verify and meta.get("sha256"):
            actual = _sha256(path)
            if actual != str(meta["sha256"]).upper():
                return {"status": "FAILED", "code": "CHECKSUM_MISMATCH", "detail": "sha256 mismatch"}
        return {"status": "READY", "code": "READY", "sha_verified": bool(verify and meta.get("sha256"))}

    def _skill_state(self) -> dict:
        try:
            from runtime.prompt_bridge.skill_version import check_skill_version
            gate = check_skill_version()
        except Exception as exc:
            return {"status": "FAILED", "code": "SKILL_INSTALL_FAILED", "detail": str(exc)}
        if gate.get("status") != "GENERATION_ALLOWED":
            return {"status": "FAILED", "code": "SKILL_INSTALL_FAILED", "detail": gate.get("flags", [])}
        return {"status": "READY", "code": "READY", "pinned_revision": gate.get("pinned_revision")}

    def _source_url(self, source: dict) -> Optional[str]:
        url = source.get("url")
        if not url:
            return None
        parsed = urlparse(str(url))
        if parsed.scheme.lower() != "https" or parsed.username or parsed.password:
            raise InstallerError("NETWORK_ERROR", "Only trusted HTTPS sources without embedded credentials are allowed.")
        for key, _ in parse_qsl(parsed.query, keep_blank_values=True):
            if key.lower() in {"token", "access_token", "api_key", "authorization"}:
                raise InstallerError("NETWORK_ERROR", "Credential-bearing download URLs are not allowed.")
        return str(url)

    def _validate_runtime_source(self, source: dict) -> str:
        """Validate the exact approved ComfyUI release source.

        Fixture manifests may use a local HTTPS-shaped source for unit tests,
        but the production manifest is accepted only when every provenance
        field matches the pinned Comfy-Org release asset.
        """
        url = self._source_url(source)
        if not url:
            return "MANUAL_SOURCE_REQUIRED"
        if source.get("type") != "official_github_release":
            return str(source.get("status") or "PINNED")
        expected_url = (
            "https://github.com/Comfy-Org/ComfyUI/releases/download/"
            "v0.33.1/ComfyUI_windows_portable_nvidia.7z"
        )
        expected = {
            "url": expected_url,
            "asset": "ComfyUI_windows_portable_nvidia.7z",
            "release_tag": "v0.33.1",
            "source_repository": "Comfy-Org/ComfyUI",
            "expected_size": 2133107036,
            "sha256": "4a221588979b96b8244e0e50b2edca03af732acae1deba69d60aa3b4d60b9dba",
        }
        for key, value in expected.items():
            actual = source.get(key)
            if key == "sha256" and actual:
                actual = str(actual).lower()
            if actual != value:
                raise InstallerError(
                    "UNTRUSTED_RUNTIME_SOURCE",
                    "The runtime source does not match the approved Comfy-Org release asset.",
                    {"field": key},
                )
        parsed = urlparse(url)
        if parsed.netloc.lower() != "github.com" or url != expected_url:
            raise InstallerError(
                "UNTRUSTED_RUNTIME_SOURCE",
                "Only the exact pinned GitHub release URL is trusted for Native Runtime.",
            )
        return "TRUSTED_PINNED_SOURCE"

    # ------------------------------------------------------------------ #
    # Install plan
    # ------------------------------------------------------------------ #
    def build_install_plan(self, native_root: Optional[str] = None,
                           models_root: Optional[str] = None,
                           verify_existing: bool = True,
                           verify_dependencies: bool = True) -> dict:
        manifest = self.manifest()
        configured_native, configured_models = self._configured_roots()
        native = Path(native_root).resolve() if native_root else configured_native
        models = Path(models_root).resolve() if models_root else configured_models
        components = []
        blocked = []
        download_bytes = 0
        support_manifest = self._support_manifest()

        runtime_meta = manifest["runtime"]["comfyui"]
        runtime_state = self._runtime_state(native)
        runtime_source = runtime_meta.get("source", {})
        runtime_source_status = self._validate_runtime_source(runtime_source)
        runtime_status = "READY" if runtime_state["status"] == "READY" else "NOT_INSTALLED"
        runtime_item = {
            "component_id": self.RUNTIME_COMPONENT,
            "type": "runtime",
            "name": "ComfyUI Native",
            "version": runtime_meta.get("version"),
            "frontend": manifest["runtime"].get("frontend", {}).get("version"),
            "source": runtime_source.get("url"),
            "source_status": runtime_source_status,
            "target": str(native),
            "expected_size": runtime_meta.get("expected_size"),
            "sha256": runtime_meta.get("checksum"),
            "status": runtime_status,
            "error": runtime_state.get("code") if runtime_state.get("code") not in ("READY", "NOT_INSTALLED") else None,
            "license_notice": "ComfyUI and MiniMax H3 runtime components remain subject to their upstream licenses.",
        }
        components.append(runtime_item)
        if runtime_status != "READY":
            if runtime_state.get("code") == "INCOMPATIBLE_RUNTIME":
                blocked.append("INCOMPATIBLE_RUNTIME")
            elif runtime_source_status == "MANUAL_SOURCE_REQUIRED":
                blocked.append("MANUAL_SOURCE_REQUIRED")

        if support_manifest:
            for layer_id, entry in support_entries(support_manifest):
                state = self._support_state(native, layer_id, entry)
                item = {
                    "component_id": layer_id,
                    "type": "support_layer",
                    "name": entry.get("package_name") or layer_id,
                    "version": str(entry.get("commit"))[:12],
                    "source": entry.get("source_archive_url"),
                    "source_status": "TRUSTED_PINNED_COMMIT",
                    "repository": entry.get("repository"),
                    "commit": entry.get("commit"),
                    "target": str(state.get("target") or self._support_target(native, entry)),
                    "expected_size": entry.get("archive_size"),
                    "sha256": entry.get("archive_sha256"),
                    "required_nodes": list(entry.get("required_nodes") or []),
                    "status": state["status"],
                    "error": state.get("code") if state.get("code") not in ("READY", "NOT_INSTALLED") else None,
                    "license_notice": f"{entry.get('license')}; source is pinned to an immutable commit.",
                }
                components.append(item)
                # A mismatched or unverifiable existing support tree is a
                # repairable state: the pinned installer can replace it from
                # the immutable source. It must not be presented as a hard
                # install-plan block.

            dependency_state = (self._support_dependency_state(native, support_manifest)
                                if verify_dependencies else {
                                    "status": "NOT_INSTALLED",
                                    "code": "SUPPORT_DEPENDENCY_AUDIT_DEFERRED",
                                })
            components.append({
                "component_id": self.SUPPORT_DEPENDENCY_COMPONENT,
                "type": "python_dependencies",
                "name": "Pinned support-layer Python dependencies",
                "version": "production-pinned",
                "source": "configs/support_layer_manifest.yaml",
                "source_status": "PINNED_NO_DEPS_NON_CORE_ONLY",
                "target": str(native / "python_embeded" / "python.exe"),
                "expected_size": None,
                "sha256": None,
                "status": dependency_state["status"],
                "error": dependency_state.get("code") if dependency_state.get("code") != "READY" else None,
                "license_notice": "Torch, torchvision, torchaudio, CUDA and comfy-kitchen remain frozen host components.",
            })

        pread_meta = manifest["runtime"]["pread_shim"]
        pread_ready = pread_compatible(native, os.environ)
        components.append({
            "component_id": self.PREAD_COMPONENT,
            "type": "pread_shim",
            "name": "Windows PREAD safe-load shim",
            "version": pread_meta.get("version"),
            "source": pread_meta.get("source", {}).get("path"),
            "source_status": "PINNED",
            "target": str(native / "ComfyUI" / "custom_nodes" / "windows_safe_load"),
            "expected_size": None,
            "sha256": None,
            "status": "READY" if pread_ready else "NOT_INSTALLED",
            "error": None,
            "license_notice": "Project-pinned compatibility shim.",
        })

        skill_state = self._skill_state()
        components.append({
            "component_id": self.SKILL_COMPONENT,
            "type": "prompt_skill",
            "name": "Official MiniMax H3 Prompt Skill",
            "version": manifest["prompt_skill"].get("pinned_revision"),
            "source": "bundled",
            "source_status": "PINNED",
            "target": str(self.repo_root / manifest["prompt_skill"].get("path", "references/known_good_h3")),
            "expected_size": None,
            "sha256": None,
            "status": skill_state["status"],
            "error": skill_state.get("code") if skill_state["status"] != "READY" else None,
            "license_notice": "Official H3 Skill is pinned and is never silently upgraded.",
        })

        for key in self.MODEL_COMPONENTS:
            meta = manifest["models"][key]
            target = self._safe_component_path(models, meta["target_subdir"])
            target = self._safe_component_path(target, meta["filename"])
            state = self._model_state(target, meta, verify=verify_existing)
            source = meta.get("source", {})
            item = {
                "component_id": key,
                "type": "model",
                "name": key.replace("_", " ").title(),
                "version": "pinned",
                "source": source.get("url"),
                "source_status": source.get("status", "PINNED"),
                "target": str(target),
                "expected_size": int(meta.get("expected_size") or 0),
                "sha256": meta.get("sha256"),
                "status": state["status"],
                "error": state.get("code") if state.get("code") not in ("READY", "NOT_INSTALLED") else None,
                "license_notice": "Model weights are provided under upstream licensing terms. Architect Video Studio does not relicense model weights.",
            }
            components.append(item)
            if state["status"] != "READY":
                if state.get("code") == "CHECKSUM_MISMATCH":
                    blocked.append("CHECKSUM_MISMATCH")
                if source.get("url"):
                    download_bytes += int(meta.get("expected_size") or 0)
                else:
                    blocked.append("MANUAL_SOURCE_REQUIRED")

        if manifest.get("installation", {}).get("h3_model_sidecar"):
            sidecar_manifest = self._h3_sidecar_manifest()
            sidecar_state = self._h3_sidecar_state(models, verify=verify_existing)
            sidecar_files = list(sidecar_manifest["files"])
            sidecar_bytes = sum(int(item["expected_size"]) for item in sidecar_files)
            sidecar_item = {
                "component_id": self.H3_SIDECAR_COMPONENT,
                "type": "model_configuration",
                "name": sidecar_manifest.get("display_name", "MiniMax H3 Model Configuration"),
                "version": sidecar_manifest["source"]["revision"],
                "source": sidecar_manifest["source"]["base_url"],
                "source_status": "TRUSTED_IMMUTABLE_SOURCE",
                "repository": sidecar_manifest["source"]["repository"],
                "revision": sidecar_manifest["source"]["revision"],
                "target": str(sidecar_target_root(models)),
                "expected_size": sidecar_bytes,
                "sha256": None,
                "file_count": len(sidecar_files),
                "status": sidecar_state["status"],
                "error": sidecar_state.get("code") if sidecar_state["status"] != "READY" else None,
                "license_notice": sidecar_manifest["license"]["identifier"],
                "files": sidecar_files,
            }
            components.append(sidecar_item)
            if sidecar_state["status"] != "READY":
                download_bytes += sidecar_bytes
                if sidecar_state.get("code"):
                    blocked.append(sidecar_state["code"])

        safety_gb = float(manifest.get("installation", {}).get("safety_margin_gb", 10))
        temporary_bytes = int(download_bytes * 0.25)
        required_bytes = download_bytes + temporary_bytes + int(safety_gb * 1024 ** 3)
        available = self._available_bytes(models)
        disk_ok = available is None or available >= required_bytes
        if not disk_ok:
            blocked.append("INSUFFICIENT_DISK")

        plan_id = "plan-" + uuid.uuid4().hex[:12]
        plan = {
            "schema_version": 1,
            "plan_id": plan_id,
            "created_at": _now(),
            "components": components,
            "required_disk_bytes": required_bytes,
            "required_disk_gb": round(required_bytes / 1024 ** 3, 2),
            "download_size_bytes": download_bytes,
            "download_size_gb": round(download_bytes / 1024 ** 3, 2),
            "temporary_size_bytes": temporary_bytes,
            "available_disk_gb": round(available / 1024 ** 3, 2) if available is not None else None,
            "disk_ok": disk_ok,
            "install_root": str(native),
            "models_root": str(models),
            "requires_confirmation": True,
            "blocked_reasons": sorted(set(blocked)),
            "source_notice": "Downloads begin only after the user reviews this plan and explicitly confirms Install.",
            "model_license_notice": "Model weights are provided under upstream licensing terms. Architect Video Studio does not relicense model weights.",
        }
        self.job_root.mkdir(parents=True, exist_ok=True)
        self._atomic_json(self.job_root / f"{plan_id}.plan.json", plan)
        return plan

    def _available_bytes(self, path: Path) -> Optional[int]:
        override = self.overrides.get("disk_free_gb")
        if override is not None:
            return int(float(override) * 1024 ** 3)
        try:
            probe = path if path.exists() else path.parent
            return int(self._disk_usage(str(probe)).free)
        except Exception:
            return None

    # ------------------------------------------------------------------ #
    # Job persistence / API operations
    # ------------------------------------------------------------------ #
    def _atomic_json(self, path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(path.name + ".tmp." + uuid.uuid4().hex[:8])
        temp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        for attempt in range(3):
            try:
                os.replace(temp, path)
                return
            except PermissionError:
                if attempt == 2:
                    raise
                self._sleep(0.01)

    def _job_path(self, job_id: str) -> Path:
        if not re.fullmatch(r"job-[a-f0-9]{12}", job_id):
            raise InstallerError("INSTALL_FAILED", "Invalid installation job id.")
        return self.job_root / f"{job_id}.json"

    def _load_job(self, job_id: str) -> dict:
        path = self._job_path(job_id)
        if not path.is_file():
            raise KeyError(f"installation job not found: {job_id}")
        for attempt in range(5):
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except PermissionError:
                if attempt == 4:
                    raise
                self._sleep(0.01)
        raise KeyError(f"installation job not found: {job_id}")

    def _save_job(self, job: dict) -> dict:
        job["updated_at"] = _now()
        self._atomic_json(self._job_path(job["job_id"]), job)
        return job

    def _log(self, message: str) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(f"[{_now()}] {_redact(message)}\n")

    def start_install(self, body: Optional[dict] = None) -> dict:
        body = body or {}
        if not body.get("confirmed"):
            raise InstallerError("INSTALL_CONFIRMATION_REQUIRED", "Review the installation plan and confirm Install.")
        native = body.get("native_root") or None
        models = body.get("models_root") or None
        plan = self.build_install_plan(native, models)
        selected = body.get("components") or [
            c["component_id"] for c in plan["components"] if c["status"] != "READY"
        ]
        selected_set = set(selected)
        relevant_blocked = []
        for item in plan["components"]:
            if item["component_id"] in selected_set and item["status"] != "READY":
                if item.get("source_status") == "MANUAL_SOURCE_REQUIRED" or (
                        item.get("type") in ("runtime", "model") and not item.get("source")):
                    relevant_blocked.append("MANUAL_SOURCE_REQUIRED")
                elif item.get("error") and item["error"] not in (
                        "NOT_INSTALLED", "SUPPORT_DEPENDENCIES_REQUIRED",
                        "SUPPORT_LAYER_PROVENANCE_MISMATCH",
                        "SUPPORT_LAYER_UNVERIFIED"):
                    relevant_blocked.append(item["error"])
        if "INSUFFICIENT_DISK" in plan["blocked_reasons"]:
            raise InstallerError("INSUFFICIENT_DISK", "There is not enough disk space for this installation.", plan)
        if relevant_blocked:
            code = "MANUAL_SOURCE_REQUIRED" if "MANUAL_SOURCE_REQUIRED" in relevant_blocked else relevant_blocked[0]
            raise InstallerError(code, self._friendly_error(code), {"plan": plan})
        if not selected_set:
            return {"job_id": None, "status": "READY", "plan": plan, "message": "All required components are already ready."}
        self._assert_no_gpu_job()
        job_id = "job-" + uuid.uuid4().hex[:12]
        job = {
            "job_id": job_id,
            "component_id": "required_components",
            "components": list(selected),
            "status": "QUEUED",
            "bytes_total": sum(int(c.get("expected_size") or 0) for c in plan["components"] if c["component_id"] in selected_set),
            "bytes_downloaded": 0,
            "progress": 0.0,
            "speed": 0.0,
            "eta": None,
            "error": None,
            "started_at": None,
            "updated_at": _now(),
            "plan_id": plan["plan_id"],
            "install_root": plan["install_root"],
            "models_root": plan["models_root"],
        }
        self._save_job(job)
        event = threading.Event()
        self._cancel[job_id] = event
        thread = threading.Thread(target=self._run_job, args=(job_id, plan, event), daemon=True)
        self._threads[job_id] = thread
        thread.start()
        return job

    def get_job(self, job_id: str) -> dict:
        return self._load_job(job_id)

    def cancel_job(self, job_id: str) -> dict:
        job = self._load_job(job_id)
        if job["status"] in ("READY", "FAILED", "CANCELLED"):
            return job
        event = self._cancel.get(job_id)
        if event:
            event.set()
        job["status"] = "CANCELLED"
        return self._save_job(job)

    def repair(self, body: Optional[dict] = None) -> dict:
        body = dict(body or {})
        body["confirmed"] = bool(body.get("confirmed"))
        plan = self.build_install_plan(body.get("native_root") or None,
                                       body.get("models_root") or None)
        body["components"] = [item["component_id"] for item in plan["components"]
                               if item["status"] != "READY"]
        if not body["components"]:
            body["components"] = [self.RUNTIME_COMPONENT, self.PREAD_COMPONENT,
                                   self.SKILL_COMPONENT]
        return self.start_install(body)

    def _assert_no_gpu_job(self) -> None:
        lock_path = Path(os.environ.get("H3_RUNTIME_LOCK", str(self.repo_root / "runtime.lock")))
        if not lock_path.is_file():
            return
        try:
            data = json.loads(lock_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        if data.get("job_running"):
            raise InstallerError(
                "INSTALL_BLOCKED_JOB_RUNNING",
                "GPU job is running: installation and repair are blocked.",
            )

    # ------------------------------------------------------------------ #
    # Job worker / component installation
    # ------------------------------------------------------------------ #
    def _run_job(self, job_id: str, plan: dict, cancel: threading.Event) -> None:
        job = self._load_job(job_id)
        job["status"] = "INSTALLING"
        job["started_at"] = _now()
        self._save_job(job)
        self._log(f"job={job_id} start components={job['components']}")
        try:
            for item in plan["components"]:
                if item["component_id"] not in job["components"]:
                    continue
                if cancel.is_set():
                    raise InstallerError("INSTALL_CANCELLED", "Installation cancelled by the user.")
                self._install_item(item, plan, job, cancel)
            self.state.save({
                "native_root": plan["install_root"],
                "models_root": plan["models_root"],
                "setup_completed": False,
                "environment_status": "SETUP_REQUIRED",
            })
            job["status"] = "READY"
            job["progress"] = 1.0
            job["error"] = None
            self._log(f"job={job_id} status=READY")
        except InstallerError as exc:
            job["status"] = "CANCELLED" if exc.code == "INSTALL_CANCELLED" else "FAILED"
            job["error"] = {"code": exc.code, "message": exc.message, "details": exc.details}
            self._log(f"job={job_id} status={job['status']} error={exc.code} {exc.message}")
        except Exception as exc:  # noqa: BLE001 - worker boundary
            job["status"] = "FAILED"
            job["error"] = {"code": "INSTALL_FAILED", "message": "Installation failed.", "details": {"type": type(exc).__name__}}
            self._log(f"job={job_id} status=FAILED error={type(exc).__name__}: {exc}")
        finally:
            self._save_job(job)

    def _install_item(self, item: dict, plan: dict, job: dict, cancel: threading.Event) -> None:
        component = item["component_id"]
        self._log(f"job={job['job_id']} component={component} phase=start")
        if component == self.RUNTIME_COMPONENT:
            self._install_runtime(item, Path(plan["install_root"]), job, cancel)
        elif component in self.SUPPORT_COMPONENTS:
            self._install_support_layer(item, Path(plan["install_root"]), job, cancel)
        elif component == self.SUPPORT_DEPENDENCY_COMPONENT:
            self._install_support_dependencies(Path(plan["install_root"]), job, cancel)
        elif component == self.PREAD_COMPONENT:
            self._install_pread(Path(plan["install_root"]))
        elif component == self.SKILL_COMPONENT:
            if self._skill_state()["status"] != "READY":
                raise InstallerError("SKILL_INSTALL_FAILED", "Pinned Official Skill validation failed.")
        elif component in self.MODEL_COMPONENTS:
            self._install_model(item, Path(plan["models_root"]), job, cancel)
        elif component == self.H3_SIDECAR_COMPONENT:
            self._install_h3_sidecar(item, Path(plan["models_root"]), job, cancel)
        else:
            raise InstallerError("INSTALL_FAILED", f"Unknown install component: {component}")

    def _extract_source_archive(self, archive: Path, stage: Path, expected_directory: str) -> None:
        extracted = stage / "_archive"
        extracted.mkdir(parents=True, exist_ok=True)
        if archive.suffix.lower() != ".zip":
            raise InstallerError("SUPPORT_INSTALL_FAILED", "Pinned support source must be a ZIP archive.")
        try:
            with zipfile.ZipFile(archive) as zf:
                members = zf.infolist()
                # GitHub commit archives contain one synthetic top-level
                # directory named ``<repo>-<sha>``.  Strip only that single
                # directory while extracting: retaining it can push nested
                # files beyond the Windows MAX_PATH boundary in a project
                # path that is otherwise valid.  Every original member is
                # still validated before its normalized target is written.
                top_levels = {
                    name.replace("\\", "/").split("/", 1)[0]
                    for name in (info.filename for info in members)
                    if name.replace("\\", "/").strip("/")
                }
                if len(top_levels) != 1:
                    raise InstallerError("SUPPORT_INSTALL_FAILED", "Support archive has multiple top-level roots.")
                archive_root = next(iter(top_levels))
                prefix = archive_root + "/"
                for info in members:
                    original_name = info.filename.replace("\\", "/")
                    if original_name.rstrip("/") == archive_root:
                        continue
                    if not original_name.startswith(prefix):
                        raise InstallerError("SUPPORT_INSTALL_FAILED", "Support archive root is malformed.")
                    normalized_name = original_name[len(prefix):]
                    # Validate the original archive member before stripping
                    # the trusted synthetic root.
                    self._safe_member_path(extracted, original_name)
                    target = self._safe_member_path(extracted, normalized_name)
                    mode = (info.external_attr >> 16) & 0o170000
                    if mode == 0o120000:
                        raise InstallerError("SUPPORT_INSTALL_FAILED", "Support archive contains a symbolic link.")
                    if info.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(info) as src, target.open("wb") as dst:
                            shutil.copyfileobj(src, dst)
        except (OSError, zipfile.BadZipFile) as exc:
            raise InstallerError(
                "SUPPORT_INSTALL_FAILED",
                "Pinned support archive could not be extracted safely.",
                {"type": type(exc).__name__, "path": str(getattr(exc, "filename", "") or "")},
            ) from exc
        if not (extracted / "__init__.py").is_file():
            raise InstallerError("SUPPORT_INSTALL_FAILED", "Support archive has an unexpected source root.")
        for child in extracted.iterdir():
            os.replace(child, stage / child.name)
        shutil.rmtree(extracted, ignore_errors=True)

    def _install_support_layer(self, item: dict, native_root: Path, job: dict,
                               cancel: threading.Event) -> None:
        support_manifest = self._support_manifest()
        if not support_manifest:
            raise InstallerError("SUPPORT_MANIFEST_INVALID", "Support-layer manifest is not configured.")
        layer_id = item["component_id"]
        entry = dict(support_manifest["support_layers"][layer_id])
        validate_support_entry(layer_id, entry)
        target = self._support_target(native_root, entry)
        if target.exists():
            raise InstallerError(
                "SUPPORT_LAYER_TARGET_EXISTS",
                "An existing custom-node directory is not overwritten by the installer.",
                {"target": str(target)},
            )
        archive = self._download_component(item["source"], item, cancel, job=job)
        stage = target.with_name(target.name + ".installing")
        if stage.exists():
            shutil.rmtree(stage)
        stage.mkdir(parents=True, exist_ok=True)
        try:
            self._extract_source_archive(archive, stage, entry["directory"])
            base_fingerprint = source_tree_fingerprint(stage)
            expected_base = entry["source_tree_fingerprint"]["value"]
            if base_fingerprint != expected_base:
                raise InstallerError(
                    "SUPPORT_SOURCE_MISMATCH",
                    "Pinned support archive source fingerprint did not match the immutable commit.",
                    {"expected": expected_base, "actual": base_fingerprint},
                )
            patch_meta = entry.get("production_snapshot", {}).get("local_patch", {})
            patch_chain = ([patch_meta] if patch_meta else []) + list(
                entry.get("production_snapshot", {}).get("additional_patches", []) or []
            )
            patch_sha = None
            applied_patch_shas = []
            for patch_spec in patch_chain:
                patch_path = self.repo_root / str(patch_spec.get("path"))
                expected_sha = str(patch_spec.get("sha256", ""))
                if not patch_path.is_file() or _sha256(patch_path) != expected_sha.upper():
                    raise InstallerError("SUPPORT_PATCH_MISMATCH", "The audited production support patch is missing or altered.")
                apply_unified_patch(patch_path, stage)
                applied_patch_shas.append(expected_sha.lower())
            if patch_meta:
                patch_sha = str(patch_meta["sha256"]).lower()
            final_fingerprint = source_tree_fingerprint(stage)
            release_h3 = (load_release_runtime_manifest(self.repo_root).get("h3") or {})
            expected_final = release_h3.get("managed_runtime_fingerprint")
            expected_final = expected_final or entry.get("production_snapshot", {}).get("source_tree_fingerprint_without_backups")
            expected_final = expected_final or entry["source_tree_fingerprint"]["value"]
            if final_fingerprint != expected_final:
                raise InstallerError(
                    "SUPPORT_SOURCE_MISMATCH",
                    "Installed support source did not match the production fingerprint.",
                    {"expected": expected_final, "actual": final_fingerprint},
                )
            lock = {
                "schema_version": 1,
                "package_name": entry["package_name"],
                "repository": entry["repository"],
                "commit": entry["commit"],
                "base_source_tree_fingerprint": base_fingerprint,
                "source_tree_fingerprint": final_fingerprint,
                "patch_sha256": patch_sha,
                "additional_patch_sha256": applied_patch_shas[1:],
                "runtime_unification": {
                    "nvfp4_loader": "native_comfy_minimax_h3",
                    "vae_offload_sync": any("vae_offload_sync" in str(p.get("path")) for p in patch_chain),
                    "model_files_modified": False,
                },
                "license": entry["license"],
                "installed_at": _now(),
            }
            (stage / "support_layer.lock.json").write_text(json.dumps(lock, indent=2), encoding="utf-8")
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(stage, target)
        except Exception:
            if stage.exists():
                shutil.rmtree(stage, ignore_errors=True)
            raise

    def _install_support_dependencies(self, native_root: Path, job: dict,
                                      cancel: threading.Event) -> None:
        support_manifest = self._support_manifest()
        if not support_manifest:
            return
        python = native_root / "python_embeded" / "python.exe"
        if not python.is_file():
            raise InstallerError("SUPPORT_DEPENDENCY_INSTALL_FAILED", "Native Python is missing.")
        specs = support_manifest.get("dependency_policy", {}).get("install_required", [])
        env = process_environment(self.repo_root)
        ensure_cache_dirs(self.repo_root)
        for spec in specs:
            package = str(spec).split("==", 1)[0].strip().lower()
            if package in {"torch", "torchvision", "torchaudio", "comfy-kitchen", "cuda", "cuda-runtime"}:
                raise InstallerError("FROZEN_CORE_REPLACEMENT", "Support dependencies attempted to replace the frozen Torch/CUDA stack.")
            if cancel.is_set():
                raise InstallerError("INSTALL_CANCELLED", "Installation cancelled by the user.")
            result = subprocess.run(
                [str(python), "-m", "pip", "install", "--no-deps", "--disable-pip-version-check", "--no-input", str(spec)],
                capture_output=True, text=True, timeout=1800, env=env, check=False,
            )
            if result.returncode != 0:
                raise InstallerError(
                    "SUPPORT_DEPENDENCY_INSTALL_FAILED",
                    "A pinned support dependency could not be installed.",
                    {"package": package, "returncode": result.returncode},
                )
        state = self._support_dependency_state(native_root, support_manifest)
        if state["status"] != "READY":
            raise InstallerError("SUPPORT_DEPENDENCY_INSTALL_FAILED", "Pinned support dependency validation failed.", state)

    def _install_runtime(self, item: dict, native_root: Path, job: dict,
                         cancel: threading.Event) -> None:
        current = self._runtime_state(native_root)
        if current["status"] == "READY":
            return
        if current.get("code") == "INCOMPATIBLE_RUNTIME":
            raise InstallerError("INCOMPATIBLE_RUNTIME", "Existing Native runtime is incompatible and was not modified.")
        url = item.get("source")
        if not url:
            raise InstallerError("MANUAL_SOURCE_REQUIRED", "A verified Native ComfyUI archive URL is required before runtime installation.")
        archive = self._download_component(url, item, cancel, job=job)
        stage = native_root.with_name(native_root.name + ".installing")
        if stage.exists():
            shutil.rmtree(stage)
        stage.mkdir(parents=True, exist_ok=True)
        try:
            self._extract_archive(archive, stage)
            self._install_pread_into(stage)
            if self._runtime_state(stage)["status"] != "READY":
                raise InstallerError("RUNTIME_INSTALL_FAILED", "Runtime archive did not contain the required production layout.")
            validation = self._validate_runtime_contents(
                stage, item, strict=item.get("source_status") == "TRUSTED_PINNED_SOURCE")
            (stage / "runtime_version.json").write_text(
                json.dumps(validation, indent=2), encoding="utf-8")
            self._promote_runtime(stage, native_root)
            os.environ["H3_WINDOWS_SAFE_LOAD"] = "pread"
        except Exception:
            if stage.exists():
                shutil.rmtree(stage, ignore_errors=True)
            raise

    def _install_pread(self, native_root: Path) -> None:
        state = self._runtime_state(native_root)
        if state["status"] == "FAILED" and state.get("code") == "INCOMPATIBLE_RUNTIME":
            raise InstallerError("INCOMPATIBLE_RUNTIME", "Existing runtime is incompatible; PREAD was not changed.")
        self._install_pread_into(native_root)
        os.environ["H3_WINDOWS_SAFE_LOAD"] = "pread"

    def _install_pread_into(self, native_root: Path) -> None:
        source = self.repo_root / "runtime" / "native_shim" / "windows_safe_load.py"
        if not source.is_file():
            raise InstallerError("RUNTIME_INSTALL_FAILED", "Bundled PREAD shim is missing.")
        target = native_root / "ComfyUI" / "custom_nodes" / "windows_safe_load"
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target / "__init__.py")

    def _validate_runtime_contents(self, root: Path, item: dict,
                                   strict: bool = True) -> dict:
        """Validate the extracted runtime without loading models or inferring."""
        python = root / "python_embeded" / "python.exe"
        main = root / "ComfyUI" / "main.py"
        frontend = str(item.get("frontend") or "1.48.7")
        if not python.is_file() or not main.is_file():
            raise InstallerError(
                "RUNTIME_INSTALL_FAILED",
                "Runtime is missing python_embeded/python.exe or ComfyUI/main.py.",
            )
        result = {
            "comfyui": str(item.get("version") or "0.33.1"),
            "frontend": frontend,
            "python": "UNVERIFIED",
            "torch": "UNVERIFIED",
            "cuda": "UNVERIFIED",
            "pread": "pread",
            "validated_at": _now(),
            "source": item.get("source"),
        }
        if not strict:
            return result
        try:
            version = subprocess.run(
                [str(python), "--version"], capture_output=True, text=True,
                timeout=30, check=False,
            )
            result["python"] = (version.stdout or version.stderr).strip()
            if not re.search(r"Python 3\.13(?:\.\d+)?", result["python"]):
                raise InstallerError("RUNTIME_VERSION_MISMATCH", "Native runtime Python is not 3.13.x.")
            version_text = root / "ComfyUI" / "comfyui_version.py"
            match = re.search(
                r"__version__\s*=\s*[\"']([^\"']+)",
                version_text.read_text(encoding="utf-8"),
            ) if version_text.is_file() else None
            if not match or match.group(1) != str(item.get("version")):
                raise InstallerError("RUNTIME_VERSION_MISMATCH", "ComfyUI source version is not the pinned 0.33.1 release.")
            probe = subprocess.run(
                [str(python), "-c", (
                    "import importlib.metadata as m; "
                    "print(m.version('comfyui-frontend-package')); "
                    "import torch; print(torch.__version__); "
                    "print(torch.version.cuda or 'None')"
                )], capture_output=True, text=True, timeout=60, check=False,
            )
            lines = [line.strip() for line in (probe.stdout or "").splitlines() if line.strip()]
            if probe.returncode != 0 or len(lines) < 3:
                raise InstallerError("RUNTIME_VERSION_MISMATCH", "Native runtime package versions could not be verified.")
            result["frontend"], result["torch"], result["cuda"] = lines[-3:]
            if result["frontend"] != frontend:
                raise InstallerError("RUNTIME_VERSION_MISMATCH", "Frontend package is not the pinned 1.48.7 version.")
            if not result["cuda"].startswith("13"):
                raise InstallerError("RUNTIME_VERSION_MISMATCH", "Torch CUDA build is not the pinned CUDA 13 line.")
            if not (root / "ComfyUI" / "comfy_extras" / "nodes_minimax_h3.py").is_file():
                raise InstallerError("H3_CAPABILITY_MISSING", "Official runtime lacks the bundled MiniMax H3 node module.")
        except InstallerError:
            raise
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            raise InstallerError(
                "RUNTIME_VERSION_MISMATCH", "Native runtime validation failed.",
                {"type": type(exc).__name__},
            ) from exc
        return result

    def _promote_runtime(self, stage: Path, target: Path) -> None:
        backup = target.with_name(target.name + ".backup." + uuid.uuid4().hex[:8])
        moved_backup = False
        try:
            if target.exists():
                os.replace(target, backup)
                moved_backup = True
            os.replace(stage, target)
        except Exception:
            if target.exists() and not stage.exists():
                shutil.rmtree(target, ignore_errors=True)
            if moved_backup and backup.exists() and not target.exists():
                os.replace(backup, target)
            raise InstallerError("RUNTIME_INSTALL_FAILED", "Runtime promotion failed; active runtime was restored.")
        if backup.exists():
            shutil.rmtree(backup, ignore_errors=True)

    def _install_model(self, item: dict, models_root: Path, job: dict, cancel: threading.Event) -> None:
        target = self._safe_component_path(models_root, item["target"].replace(str(models_root.resolve()) + os.sep, "")) if Path(item["target"]).is_absolute() else self._safe_component_path(models_root, item["target"])
        meta = {"expected_size": item.get("expected_size"), "sha256": item.get("sha256")}
        existing = self._model_state(target, meta, verify=True)
        if existing["status"] == "READY":
            return
        url = item.get("source")
        if not url:
            raise InstallerError("MANUAL_SOURCE_REQUIRED", f"No trusted source is configured for {item['component_id']}.")
        download = self._download_component(url, item, cancel, job=job)
        target.parent.mkdir(parents=True, exist_ok=True)
        installing = target.with_name(target.name + ".installing")
        if installing.exists():
            installing.unlink()
        shutil.copy2(download, installing)
        try:
            os.replace(installing, target)
        except Exception as exc:
            if installing.exists():
                installing.unlink()
            raise InstallerError("MODEL_INSTALL_FAILED", "Model promotion failed.") from exc

    def _install_h3_sidecar(self, item: dict, models_root: Path, job: dict,
                            cancel: threading.Event) -> None:
        manifest = self._h3_sidecar_manifest()
        if self._h3_sidecar_state(models_root, verify=True)["status"] == "READY":
            return
        target = sidecar_target_root(models_root)
        stage = target.with_name(target.name + ".installing")
        if stage.exists():
            shutil.rmtree(stage, ignore_errors=True)
        stage.mkdir(parents=True, exist_ok=True)
        try:
            for source_item in manifest["files"]:
                if cancel.is_set():
                    raise InstallerError("INSTALL_CANCELLED", "Installation cancelled by the user.")
                relative = str(source_item["path"])
                download_item = dict(source_item)
                download_item.update({
                    "component_id": self.H3_SIDECAR_COMPONENT,
                    "cache_name": relative.replace("/", "__"),
                })
                download = self._download_component(
                    source_item["source_url"], download_item, cancel, job=job,
                )
                destination = stage / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(download, destination)
            lock = {
                "schema_version": 1,
                "repository": manifest["source"]["repository"],
                "revision": manifest["source"]["revision"],
                "license": manifest["license"]["identifier"],
                "files": [{"path": str(item["path"]), "sha256": str(item["sha256"])}
                          for item in manifest["files"]],
                "installed_at": _now(),
            }
            (stage / "h3_sidecar.lock.json").write_text(
                json.dumps(lock, indent=2), encoding="utf-8")
            target.parent.mkdir(parents=True, exist_ok=True)
            backup = target.with_name(target.name + ".backup." + uuid.uuid4().hex[:8])
            if target.exists():
                os.replace(target, backup)
            try:
                os.replace(stage, target)
            except Exception:
                if backup.exists() and not target.exists():
                    os.replace(backup, target)
                raise
            if backup.exists():
                shutil.rmtree(backup, ignore_errors=True)
        except InstallerError as exc:
            if stage.exists():
                shutil.rmtree(stage, ignore_errors=True)
            if exc.code == "CHECKSUM_MISMATCH":
                raise InstallerError(
                    "H3_SUPPORT_DATA_HASH_MISMATCH",
                    "MiniMax H3 model configuration failed SHA-256 verification.",
                    exc.details,
                ) from exc
            if exc.code == "DOWNLOAD_FAILED":
                raise InstallerError(
                    "H3_SUPPORT_DATA_DOWNLOAD_FAILED",
                    "MiniMax H3 model configuration download failed.",
                    exc.details,
                ) from exc
            raise
        except Exception as exc:
            if stage.exists():
                shutil.rmtree(stage, ignore_errors=True)
            raise InstallerError(
                "H3_SUPPORT_DATA_INCOMPLETE",
                "MiniMax H3 model configuration could not be promoted atomically.",
                {"type": type(exc).__name__},
            ) from exc

    def _download_component(self, url: str, item: dict, cancel: threading.Event,
                            job: Optional[dict] = None) -> Path:
        self._source_url({"url": url})
        filename = str(item.get("cache_name") or Path(urlparse(url).path).name or item["component_id"] + ".download")
        cache_base = self.cache_root.parent / "runtime" if item["component_id"] == self.RUNTIME_COMPONENT else self.cache_root
        component_cache = cache_base / item["component_id"]
        component_cache.mkdir(parents=True, exist_ok=True)
        part = component_cache / (filename + ".part")
        final = component_cache / filename
        expected_size = item.get("expected_size")
        expected_sha = item.get("sha256")
        if final.is_file() and expected_sha and _sha256(final) == str(expected_sha).upper():
            if item["component_id"] == self.RUNTIME_COMPONENT:
                self._record_runtime_cache(final, item)
            return final
        self.download_resumable(url, part, final, expected_size=expected_size,
                                expected_sha256=expected_sha,
                                cancel_event=cancel,
                                progress=(lambda n: self._job_progress(job, n)) if job else None)
        if item["component_id"] == self.RUNTIME_COMPONENT:
            self._record_runtime_cache(final, item)
        return final

    def _record_runtime_cache(self, archive: Path, item: dict) -> None:
        metadata = {
            "verified_at": _now(),
            "filename": archive.name,
            "size": archive.stat().st_size,
            "sha256": _sha256(archive),
            "source": item.get("source"),
            "release": "Comfy-Org/ComfyUI@v0.33.1",
        }
        self._atomic_json(archive.parent / "verified_runtime.json", metadata)

    def _job_progress(self, job: Optional[dict], increment: int) -> None:
        if not job:
            return
        job["bytes_downloaded"] = int(job.get("bytes_downloaded", 0)) + increment
        total = int(job.get("bytes_total", 0))
        job["progress"] = min(1.0, job["bytes_downloaded"] / total) if total else 0.0
        last = int(job.get("_progress_checkpoint", 0))
        if job["bytes_downloaded"] - last >= 16 * 1024 * 1024 or job["bytes_downloaded"] >= total:
            job["_progress_checkpoint"] = job["bytes_downloaded"]
            self._save_job(job)

    # ------------------------------------------------------------------ #
    # Download / archive primitives
    # ------------------------------------------------------------------ #
    def download_resumable(self, url: str, part_path: Path, final_path: Path,
                           expected_size: Optional[int] = None,
                           expected_sha256: Optional[str] = None,
                           cancel_event: Optional[threading.Event] = None,
                           progress: Optional[Callable[[int], None]] = None,
                           retry_count: int = 3) -> Path:
        self._source_url({"url": url})
        part_path = Path(part_path)
        final_path = Path(final_path)
        part_path.parent.mkdir(parents=True, exist_ok=True)
        last_error = None
        for attempt in range(1, retry_count + 1):
            offset = part_path.stat().st_size if part_path.is_file() else 0
            headers = {"User-Agent": "ArchitectVideoStudio-I2/1"}
            if offset:
                headers["Range"] = f"bytes={offset}-"
            try:
                request = urllib.request.Request(url, headers=headers)
                with self._opener.open(request, timeout=30) as response:
                    status = int(getattr(response, "status", response.getcode() or 200))
                    append = offset > 0 and status == 206
                    if offset > 0 and not append:
                        offset = 0
                    mode = "ab" if append else "wb"
                    length = response.headers.get("Content-Length")
                    total = (offset + int(length)) if length and append else (int(length) if length else expected_size)
                    with part_path.open(mode) as fh:
                        while True:
                            if cancel_event and cancel_event.is_set():
                                raise InstallerError("INSTALL_CANCELLED", "Installation cancelled by the user.")
                            block = response.read(8 * 1024 * 1024)
                            if not block:
                                break
                            fh.write(block)
                            if progress:
                                progress(len(block))
                        fh.flush()
                        os.fsync(fh.fileno())
                if expected_size and part_path.stat().st_size != int(expected_size):
                    raise InstallerError("DOWNLOAD_FAILED", "Downloaded file size does not match the pinned manifest.")
                if expected_sha256:
                    actual = _sha256(part_path)
                    if actual != str(expected_sha256).upper():
                        corrupt = part_path.with_name(part_path.name + ".corrupt")
                        os.replace(part_path, corrupt)
                        raise InstallerError("CHECKSUM_MISMATCH", "Downloaded file failed SHA-256 verification.")
                os.replace(part_path, final_path)
                return final_path
            except InstallerError as exc:
                if exc.code in {"INSTALL_CANCELLED", "CHECKSUM_MISMATCH"}:
                    raise
                last_error = exc
            except (OSError, urllib.error.URLError, TimeoutError, ValueError) as exc:
                last_error = exc
            if attempt < retry_count:
                self._sleep(min(8.0, 0.5 * (2 ** (attempt - 1))))
        raise InstallerError("DOWNLOAD_FAILED", "Download failed after the retry limit.", {"error": _redact(last_error)})

    @staticmethod
    def _safe_member_path(root: Path, name: str) -> Path:
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise InstallerError("RUNTIME_INSTALL_FAILED", "Archive contains an unsafe path.")
        target = (root / relative).resolve()
        if not str(target).startswith(str(root.resolve())):
            raise InstallerError("RUNTIME_INSTALL_FAILED", "Archive escaped the staging directory.")
        return target

    def _extract_archive(self, archive: Path, stage: Path) -> None:
        extract = stage / "_extract"
        extract.mkdir(parents=True, exist_ok=True)
        suffix = archive.suffix.lower()
        if suffix == ".zip":
            with zipfile.ZipFile(archive) as zf:
                for info in zf.infolist():
                    target = self._safe_member_path(extract, info.filename)
                    if info.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(info) as src, target.open("wb") as dst:
                            shutil.copyfileobj(src, dst)
        elif suffix in {".tar", ".gz", ".tgz", ".bz2", ".xz"} or archive.name.lower().endswith(".tar.gz"):
            with tarfile.open(archive) as tf:
                for member in tf.getmembers():
                    if member.issym() or member.islnk():
                        raise InstallerError("RUNTIME_INSTALL_FAILED", "Archive links are not allowed.")
                    self._safe_member_path(extract, member.name)
                tf.extractall(extract)
        elif suffix == ".7z":
            self._extract_7z(archive, extract)
        else:
            raise InstallerError("RUNTIME_INSTALL_FAILED", "Unsupported runtime archive format.")
        content_root = extract
        if not (content_root / "ComfyUI").is_dir():
            candidates = [
                p for p in extract.iterdir()
                if p.is_dir() and (p / "ComfyUI").is_dir()
            ]
            if len(candidates) == 1:
                content_root = candidates[0]
        if not (content_root / "ComfyUI").is_dir() or not (content_root / "python_embeded").is_dir():
            raise InstallerError("RUNTIME_INSTALL_FAILED", "Runtime archive lacks the expected ComfyUI directory.")
        for path in extract.rglob("*"):
            if path.is_symlink():
                raise InstallerError("RUNTIME_INSTALL_FAILED", "Runtime archive contains a link, which is not allowed.")
        for child in content_root.iterdir():
            os.replace(child, stage / child.name)
        shutil.rmtree(extract, ignore_errors=True)

    def _extract_7z(self, archive: Path, extract: Path) -> None:
        """Extract 7z through an explicit local 7-Zip binary after safe listing."""
        if not self._extractor:
            raise InstallerError(
                "RUNTIME_ARCHIVE_TOOL_MISSING",
                "A 7-Zip extractor is required for the official Native .7z archive.",
            )
        extractor = str(self._extractor)
        try:
            listing = subprocess.run(
                [extractor, "l", "-slt", str(archive)],
                capture_output=True, text=True, timeout=120, check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise InstallerError("RUNTIME_ARCHIVE_TOOL_MISSING", "The configured 7-Zip extractor could not be started.") from exc
        if listing.returncode != 0:
            raise InstallerError("RUNTIME_INSTALL_FAILED", "The runtime archive could not be listed safely.")
        for line in listing.stdout.splitlines():
            if not line.startswith("Path = "):
                continue
            name = line[7:].strip()
            if name and name != str(archive):
                self._safe_member_path(extract, name)
        try:
            extracted = subprocess.run(
                [extractor, "x", "-y", f"-o{extract}", str(archive)],
                capture_output=True, text=True, timeout=900, check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise InstallerError("RUNTIME_INSTALL_FAILED", "The runtime archive could not be extracted.") from exc
        if extracted.returncode != 0:
            raise InstallerError("RUNTIME_INSTALL_FAILED", "The runtime archive extraction failed.")

    @staticmethod
    def _friendly_error(code: str) -> str:
        return {
            "MANUAL_SOURCE_REQUIRED": "A verified download source for this component is not configured yet.",
            "INCOMPATIBLE_RUNTIME": "The selected runtime does not match the pinned production baseline.",
            "CHECKSUM_MISMATCH": "The downloaded file failed SHA-256 verification.",
            "H3_SUPPORT_DATA_DOWNLOAD_FAILED": "MiniMax H3 model configuration download failed.",
            "H3_SUPPORT_DATA_HASH_MISMATCH": "MiniMax H3 model configuration verification failed.",
            "H3_SUPPORT_DATA_INCOMPLETE": "MiniMax H3 model configuration is incomplete.",
            "H3_MODEL_ROOT_CONFIGURATION_FAILED": "MiniMax H3 model root could not be configured.",
            "H3_COMPONENT_CONTRACT_FAILED": "MiniMax H3 component contract validation failed.",
            "INSUFFICIENT_DISK": "There is not enough free disk space for this installation.",
            "INSTALL_CONFIRMATION_REQUIRED": "Review the plan and explicitly confirm installation.",
        }.get(code, "Installation could not be started.")
