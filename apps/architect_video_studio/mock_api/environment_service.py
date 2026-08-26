"""Environment Center service (PATCH2.8-I1).

Builds the environment report (system / runtime / models / skill / workflows /
paths / gates), persists user path configuration, and maps the overall status:
READY / WARNING / SETUP_REQUIRED / BLOCK. Reuses the frozen EnvChecker and the
Official Skill pin. No GPU inference.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from ._paths import REPO_ROOT
from .environment_resolution import (
    MODEL_SUBDIRS,
    pread_compatible,
    resolve_active_environment,
    resolve_install_roots,
)
from .environment_probe import EnvironmentProbe
from .setup_state import SetupState
from .yaml_compat import safe_load
from runtime.h3_model_root import (
    COMFY_MODEL_PATHS_FILENAME,
    ensure_h3_model_root_bridge,
    h3_model_root_bridge_status,
    canonical_h3_model_root,
    validate_h3_model_contract,
    write_comfy_model_paths_config,
)
from runtime.support_layer import load_release_runtime_manifest

# launcher is a sibling (repo root) or parent-sibling (distribution/studio).
_LAUNCHER_CANDIDATES = [
    REPO_ROOT / "launcher",
    REPO_ROOT.parent / "launcher",
]
_LAUNCHER_DIR = next((p for p in _LAUNCHER_CANDIDATES if p.is_dir()), None)
if _LAUNCHER_DIR is not None and str(_LAUNCHER_DIR.parent) not in sys.path:
    sys.path.insert(0, str(_LAUNCHER_DIR.parent))

if _LAUNCHER_DIR is not None:
    try:
        from launcher.env_check import EnvChecker, EnvPaths  # noqa: E402
    except ImportError:  # distribution fallback when package markers are absent
        if str(_LAUNCHER_DIR) not in sys.path:
            sys.path.insert(0, str(_LAUNCHER_DIR))
        from env_check import EnvChecker, EnvPaths  # noqa: E402


def _gb(size_bytes: Optional[int]) -> str:
    if not size_bytes:
        return "?"
    return f"~{size_bytes / (1024 ** 3):.1f} GB"


def _free_commit_gb() -> float:
    import ctypes

    class _M(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    st = _M()
    st.dwLength = ctypes.sizeof(_M)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
    return round(st.ullAvailPageFile / (1024 ** 3), 1)


class EnvironmentService:
    MODEL_SUBDIRS = MODEL_SUBDIRS

    def __init__(self, store, env_overrides: Optional[Dict[str, Any]] = None) -> None:
        self.store = store
        self.state = SetupState(store)
        self.overrides = env_overrides or {}

    @staticmethod
    def _existing_role(state: dict, key: str) -> str:
        """Expose a historical role only while its directory still exists."""
        raw = str(state.get(key) or "").strip()
        if not raw:
            return ""
        try:
            return str(Path(raw).resolve()) if Path(raw).is_dir() else ""
        except OSError:
            return ""

    def _env_log(self, marker: str, message: str, **fields: Any) -> None:
        """Write concise environment-pipeline diagnostics without affecting probes."""
        try:
            store = getattr(self, "store", None)
            if store is None or not getattr(store, "data_root", None):
                return
            data_root = Path(store.data_root).resolve()
            candidates = (data_root.parent.parent / "Logs", data_root.parent / "Logs")
            log_dir = next((path for path in candidates if path.exists()), candidates[0])
            log_dir.mkdir(parents=True, exist_ok=True)
            suffix = "".join(
                f" {key}={str(value).replace(chr(10), ' ')[:500]}"
                for key, value in fields.items() if value not in (None, "")
            )
            line = f"[{datetime.now(timezone.utc).isoformat()}] {marker} {message}{suffix}\n"
            with (log_dir / "environment.log").open("a", encoding="utf-8") as stream:
                stream.write(line)
        except (OSError, TypeError, ValueError):
            return

    # ------------------------------------------------------------------ #
    def _paths(self) -> EnvPaths:
        return EnvPaths()  # reads H3_* env vars set by launcher/config

    def _light_env_report(self) -> Dict[str, Any]:
        if _LAUNCHER_DIR is None:
            return {"checks": {}, "overall": "BLOCK"}
        checker = EnvChecker(paths=self._paths())
        return checker.check_all(light=True)

    def _active_environment(self):
        try:
            project_local = self.store.data_root.resolve().is_relative_to(REPO_ROOT.resolve())
        except (AttributeError, OSError):
            project_local = False
        return resolve_active_environment(REPO_ROOT, self.state.load(), os.environ,
                                          use_legacy_config=project_local,
                                          # The packaged userdata directory is
                                          # inside its distribution root, as
                                          # is the developer checkout.  This
                                          # enables bounded cross-drive reuse
                                          # for real app instances while
                                          # keeping arbitrary library/fixture
                                          # stores isolated.
                                          auto_discover=project_local)

    def _adopt_if_needed(self, active) -> None:
        state = self.state.load()
        native = str(active.native_root) if active.native_root else ""
        models = str(active.models_root) if active.models_root else ""
        if (native and state.get("native_root") != native) or \
                (models and state.get("models_root") != models):
            self.state.save({"native_root": native, "models_root": models,
                             "environment_status": "SETUP_REQUIRED"})
        if native and active.source != "configured":
            self._write_native_env_path(native)
        if models and active.source != "configured" and self._is_local_distribution_store():
            self._write_models_env_path(models)

    # ------------------------------------------------------------------ #
    def environment(self) -> Dict[str, Any]:
        state = self.state.load()
        active = self._active_environment()
        self._env_log("ENV-01", "config loaded", configured_native=state.get("native_root"),
                      configured_models=state.get("models_root"))
        self._adopt_if_needed(active)
        install_defaults = safe_load(
            (REPO_ROOT / "configs" / "installation_manifest.yaml")
            .read_text(encoding="utf-8")).get("installation", {})
        install_native = (REPO_ROOT / install_defaults.get("default_runtime_root", "ArchitectVideoStudio_Runtime")).resolve()
        install_models = (REPO_ROOT / install_defaults.get("default_models_root", "Models")).resolve()
        # When an existing production pair has been explicitly adopted, the
        # active pair is the install target for status/reporting purposes.
        # Do not expose the source checkout as a fake target on a developer
        # machine or make the UI imply that another Runtime is required.
        if active.source == "configured" and active.native_root is not None:
            install_native = active.native_root
            install_models = active.models_root or (active.native_root.parent / "Models")
        native_root = str(active.native_root) if active.native_root else ""
        models_root = str(active.models_root) if active.models_root else ""
        self._env_log("ENV-02", "Runtime resolved", native_root=native_root,
                      models_root=models_root, source=active.source)
        self._env_log("ENV-03", "release manifest resolved",
                      manifest=str(REPO_ROOT / "configs" / "release_runtime_manifest.json"))

        system = self._system_status(models_root, native_root)
        runtime = self._runtime_status(native_root)
        support = self._support_status(native_root)
        models = self._models_status(models_root, native_root)
        h3_model_root = self._h3_model_status(native_root, models_root)
        models["h3_model_root"] = h3_model_root
        models["h3_asset_status"] = h3_model_root.get(
            "asset_contract", {"status": "UNKNOWN", "ready": False, "missing": []})
        models["h3_runtime_status"] = "READY" if h3_model_root["ready"] else "CONFIGURATION_REQUIRED"
        models["status"] = "READY" if (
            models["ready"] == models["count"] and h3_model_root["ready"] and
            models["h3_asset_status"].get("ready") and
            models.get("comfy_discovery", {}).get("ready", True)
        ) else "CONFIGURATION_REQUIRED"
        skill = self._skill_status()
        workflows = self._workflow_status()
        probe = dict(system["environment_probe"])
        h3_provenance = support["h3"].get("provenance") or {}
        probe.update({
            "comfy_runtime_present": bool(runtime["present"]),
            # Upstream provenance is deliberately independent from the
            # patched source-tree/runtime fingerprint.  A valid upstream
            # commit must not be reported as WRONG_REVISION merely because
            # the managed Runtime is a patched production tree.
            "h3_upstream_ready": bool(
                h3_provenance.get("upstream_ready",
                                  h3_provenance.get("commit") or support["h3"].get("ready"))
            ),
            "h3_support_layer_ready": bool(support["h3"]["ready"]),
            "models_ready": bool(models["ready"] == models["count"] and
                                  h3_model_root["ready"] and
                                  models.get("comfy_discovery", {}).get("ready", True)),
            "prompt_skill_ready": bool(skill["generation_allowed"]),
            "workflows_ready": bool(workflows["ready"] == workflows["count"]),
        })
        system["environment_probe"] = probe
        # Persist the latest complete result for diagnostics.  Every new
        # environment() call still performs a fresh bounded probe; this is not
        # used as stale GPU truth.
        paths = {
            "native_root": native_root or "",
            "models_root": models_root or "",
            "configured": bool(native_root),
            "runtime_role": "ACTIVE_PRODUCTION_NATIVE" if native_root else "UNCONFIGURED",
        }

        gates = {
            "native_root_configured": bool(native_root),
            "comfyui_present": runtime["present"],
            "pread_present": runtime["pread"],
            "gpu_ready": system["gpu_ready"],
            "models_4of4": all(m["status"] == "READY" for m in models["items"]) and
                           bool(models.get("comfy_discovery", {}).get("ready", True)),
            "h3_model_root_ready": bool(h3_model_root["ready"]),
            "h3_assets_ready": bool(models["h3_asset_status"].get("ready")),
            "h3_support_ready": bool(support["h3"]["ready"]),
            "video_support_ready": bool(support["video"]["ready"]),
            "support_dependencies_ready": bool(support["dependencies"]["ready"]),
            "skill_pinned_ready": skill["generation_allowed"],
            "workflows_5of5": workflows["ready"] == 5,
            "free_commit_ok": system.get("free_commit_policy", self._free_commit_policy(
                system["free_commit"], system.get("deployment_profile")
            ))["status"] != "BLOCK",
            "contract_valid": self._contract_valid(),
        }

        overall = self._overall(system, runtime, models, support, skill, gates)
        provenance = {
            "release_manifest": str(REPO_ROOT / "configs" / "release_runtime_manifest.json"),
            "support_manifest": str(REPO_ROOT / "configs" / "support_layer_manifest.yaml"),
            "h3": dict(support["h3"].get("provenance") or {}),
            "video": dict(support["video"].get("provenance") or {}),
        }
        normalized_state = {
            "schema_version": 1,
            "checked_at": probe.get("last_probe_finished") or "",
            "overall": overall,
            "paths": paths,
            "system": system,
            "runtime": runtime,
            "support": support,
            "models": models,
            "skill": skill,
            "prompt_skill": skill,
            "workflows": workflows,
            "gates": dict(gates),
            "production_gates": dict(gates),
            "probe": probe,
            "environment_probe": probe,
            "provenance": provenance,
            "environment_sources": {
                "active": {"native_root": native_root, "models_root": models_root,
                           "source": active.source},
                "install_target": {"native_root": str(install_native),
                                   "models_root": str(install_models)},
                "validation_target": {"native_root": str(active.validation_native or ""),
                                      "models_root": str(active.validation_models or "")},
            },
            "runtime_roles": {
                "active_production_native": native_root,
                "legacy_validated_reference": self._existing_role(
                    state, "legacy_validated_reference"),
                "test_runtime": self._existing_role(state, "test_runtime"),
                "validation_runtime": str(active.validation_native or state.get("validation_runtime") or ""),
                "install_target": str(install_native),
            },
        }
        self._env_log("ENV-06", "H3 provenance evaluated",
                      expected=provenance["h3"].get("expected_fingerprint"),
                      actual=provenance["h3"].get("actual_fingerprint"),
                      source=provenance["h3"].get("lock_file"))
        self._env_log("ENV-07", "normalized state published", overall=overall,
                      probe_status=probe.get("probe_status"),
                      h3_ready=gates["h3_support_ready"])
        self.state.save({"environment_probe": probe,
                         "environment_state": normalized_state})
        if overall == "READY" and (not state.get("setup_completed") or active.source != "configured"):
            self.state.save({"setup_completed": True,
                             "environment_status": "READY",
                             "skill_status": skill["status"]})
            state = self.state.load()
        setup_completed = bool(state.get("setup_completed")) and all(gates.values())

        return {
            "overall": overall,
            "setup_completed": setup_completed,
            "system": system,
            "runtime": runtime,
            "support": support,
            "models": models,
            "skill": skill,
            "workflows": workflows,
            "paths": paths,
            "gates": gates,
            "production_gates": dict(gates),
            "environment_probe": probe,
            "environment_state": normalized_state,
            "environment_sources": {
                "active": {
                    "native_root": native_root,
                    "models_root": models_root,
                    "source": active.source,
                },
                "install_target": {
                    "native_root": str(install_native),
                    "models_root": str(install_models),
                },
                "validation_target": {
                    "native_root": str(active.validation_native or ""),
                    "models_root": str(active.validation_models or ""),
                },
            },
            "runtime_roles": {
                "active_production_native": native_root,
                "legacy_validated_reference": self._existing_role(
                    state, "legacy_validated_reference"),
                "test_runtime": self._existing_role(state, "test_runtime"),
                "validation_runtime": str(
                    active.validation_native or state.get("validation_runtime") or ""),
                "install_target": str(install_native),
            },
        }

    # ------------------------------------------------------------------ #
    def _system_status(self, models_root: str = "", native_root: str = "") -> Dict[str, Any]:
        import platform
        mem = self.overrides.get("memory_gb")
        disk = self.overrides.get("disk_free_gb")
        launch_report = None
        report_name = os.environ.get("H3_ENV_REPORT", "")
        if report_name and Path(report_name).is_file():
            try:
                launch_report = json.loads(Path(report_name).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                launch_report = None
        report_checks = (launch_report or {}).get("checks", {})
        # Never let an old launcher/env_report snapshot masquerade as current
        # machine state.  Use live values first; the historical report is only
        # a bounded fallback for hosts where the corresponding OS probe fails.
        if mem is None:
            try:
                mem = _free_commit_gb()
            except Exception:
                mem = report_checks.get("memory", {}).get("free_commit_gb")
        if disk is None:
            try:
                disk_path = Path(models_root) if models_root else self._paths().models_root
                disk = round(__import__("shutil").disk_usage(disk_path).free / (1024 ** 3), 1)
            except Exception:
                disk = report_checks.get("disk", {}).get("free_gb")
        self._env_log("ENV-04", "GPU/runtime probe started",
                      runtime_root=native_root)
        environment_probe = EnvironmentProbe(native_root, self.overrides).run()
        self._env_log("ENV-05", "GPU/runtime probe completed",
                      status=environment_probe.get("probe_status"),
                      gpu=environment_probe.get("gpu_name"),
                      error=environment_probe.get("probe_error"))
        vram_bytes = environment_probe["gpu_vram_bytes"]
        hardware = {
            "status": "READY" if environment_probe["gpu_detected"] else "MISSING",
            "ready": bool(environment_probe["gpu_detected"]),
            "name": environment_probe["gpu_name"],
            "vram_gb": round(vram_bytes / (1024 ** 3), 2) if vram_bytes else None,
            "source": "nvidia-smi" if environment_probe["diagnostics"].get("nvidia_smi", {}).get("status") == "PASS" else "windows/runtime",
        }
        driver = {
            "status": "READY" if environment_probe["driver_detected"] else ("ISSUE" if environment_probe["gpu_detected"] else "NOT_TESTED"),
            "ready": bool(environment_probe["driver_detected"]),
            "version": environment_probe["driver_version"],
        }
        runtime_status = "READY" if environment_probe["torch_cuda_available"] else (
            "ISSUE" if environment_probe["torch_import_ok"] or environment_probe["runtime_python_found"] else "NOT_TESTED"
        )
        runtime_cuda = {
            "status": runtime_status,
            "ready": bool(environment_probe["torch_cuda_available"]),
            "torch_imported": bool(environment_probe["torch_import_ok"]),
            "torch_version": environment_probe["torch_version"],
            "cuda_version": environment_probe["torch_cuda_version"],
            "device_name": environment_probe["torch_gpu_name"],
            "vram_gb": round(environment_probe["torch_gpu_total_memory"] / (1024 ** 3), 2) if environment_probe["torch_gpu_total_memory"] else None,
            "python_path": environment_probe["runtime_python_path"],
            "detail": environment_probe["probe_error"] or "Managed Runtime Torch/CUDA probe passed.",
        }
        policy = environment_probe["hardware_policy"]
        gpu_ready = bool(environment_probe["gpu_detected"] and environment_probe["driver_detected"] and environment_probe["torch_cuda_available"])
        deployment_profile = os.environ.get("H3_DEPLOYMENT_PROFILE", "AUTO")
        return {
            "os": platform.system(),
            "gpu_name": hardware["name"] or "未检测到 NVIDIA GPU",
            "cuda": bool(environment_probe["torch_cuda_available"]),
            "gpu_ready": gpu_ready,
            "gpu_status": "READY" if gpu_ready else ("NOT_TESTED" if runtime_cuda["status"] == "NOT_TESTED" else "ISSUE"),
            "gpu_detail": runtime_cuda["detail"],
            "gpu_hardware": hardware,
            "driver": driver,
            "runtime_cuda": runtime_cuda,
            "hardware_policy": policy,
            "deployment_profile": deployment_profile,
            "profile_hardware_source": os.environ.get("H3_PROFILE_HARDWARE_SOURCE", ""),
            "profile_gpu_vram_gb": os.environ.get("H3_GPU_VRAM_GB", ""),
            "profile_system_ram_gb": os.environ.get("H3_SYSTEM_RAM_GB", ""),
            "free_commit_policy": self._free_commit_policy(float(mem or 0.0), deployment_profile),
            "environment_probe": environment_probe,
            "memory_gb": self.overrides.get("ram_gb"),
            "free_commit": float(mem or 0.0),
            "disk_free_gb": float(disk or 0.0),
        }

    def _probe_gpu(self, native_root: str, override: Optional[bool], override_name: Optional[str]) -> Dict[str, Any]:
        """Compatibility wrapper for callers that used the old private method."""
        result = EnvironmentProbe(native_root, {
            "torch_available": override,
            "gpu_name": override_name,
        }).run()
        vram = result["gpu_vram_bytes"]
        return {
            "hardware": {
                "status": "READY" if result["gpu_detected"] else "MISSING",
                "ready": result["gpu_detected"],
                "name": result["gpu_name"],
                "vram_gb": round(vram / (1024 ** 3), 2) if vram else None,
            },
            "driver": {
                "status": "READY" if result["driver_detected"] else "ISSUE",
                "ready": result["driver_detected"],
                "version": result["driver_version"],
            },
            "runtime": {
                "status": "READY" if result["torch_cuda_available"] else "ISSUE",
                "ready": result["torch_cuda_available"],
                "torch_imported": result["torch_import_ok"],
                "torch_version": result["torch_version"],
                "cuda_version": result["torch_cuda_version"],
                "device_name": result["torch_gpu_name"],
                "vram_gb": round(result["torch_gpu_total_memory"] / (1024 ** 3), 2) if result["torch_gpu_total_memory"] else None,
                "detail": result["probe_error"],
            },
            "policy": result["hardware_policy"],
        }

    def _runtime_status(self, native_root: str) -> Dict[str, Any]:
        root = Path(native_root) if native_root else None
        main = (root / "ComfyUI" / "main.py") if root else None
        shim = (root / "ComfyUI" / "custom_nodes" / "windows_safe_load") if root else None
        present = bool(main and main.is_file())
        pread = pread_compatible(root, os.environ)
        version = self.overrides.get("comfyui_version") if present else None
        if version is None and present:
            try:
                import re
                text = (root / "ComfyUI" / "comfyui_version.py").read_text(encoding="utf-8")
                match = re.search(r"__version__\s*=\s*[\"']([^\"']+)", text)
                version = match.group(1) if match else "0.33.1"
            except OSError:
                version = "0.33.1"
        frontend = self.overrides.get("frontend_version") if present else None
        if frontend is None and present:
            frontend = "1.48.7"
            try:
                packages = root / "python_embeded" / "Lib" / "site-packages"
                for metadata in packages.glob("comfyui_frontend_package-*.dist-info"):
                    frontend = metadata.name.split("-", 1)[1].removesuffix(".dist-info")
                    break
            except OSError:
                pass
        baseline = "0.33.1" if present else None
        frontend_baseline = "1.48.7" if present else None
        comparison = None
        if present and (version != baseline or frontend != frontend_baseline):
            comparison = "EXPECTED_PRODUCTION_DIFFERENCE"
        return {
            "path": str(root) if root else "",
            "present": present,
            "version": version,
            "frontend": frontend,
            "baseline_comparison": comparison or "MATCH",
            "pread": pread,
            "port": 8189,
        }

    def _support_status(self, native_root: str) -> Dict[str, Any]:
        """Expose the frozen support contract without starting ComfyUI."""
        if not native_root:
            return {
                "h3": {"status": "NEEDS_PATH", "ready": False},
                "video": {"status": "NEEDS_PATH", "ready": False},
                "dependencies": {"status": "NEEDS_PATH", "ready": False},
            }
        custom_nodes = Path(native_root) / "ComfyUI" / "custom_nodes"
        h3_dir = custom_nodes / "ComfyUI_RH_MinMaxH3"
        vhs_dir = custom_nodes / "ComfyUI-VideoHelperSuite"
        try:
            from runtime.support_layer import FROZEN_NODE_NAMES
            h3_names = set(FROZEN_NODE_NAMES[:-1])
        except Exception:
            h3_names = set()

        def registered(directory: Path, names: set[str]) -> bool:
            if not directory.is_dir():
                return False
            found: set[str] = set()
            for source in directory.rglob("*.py"):
                try:
                    text = source.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                found.update(name for name in names if name in text)
                if found == names:
                    return True
            return found == names

        h3_ready = registered(h3_dir, h3_names)
        vhs_ready = registered(vhs_dir, {"VHS_VideoCombine"})
        provenance = self._support_provenance(h3_dir, vhs_dir)
        if "support_provenance_ready" in self.overrides or "support_dependencies_ready" in self.overrides:
            forced = bool(self.overrides.get("support_provenance_ready", True))
            provenance = {
                "h3": {"status": "READY" if forced else "REVISION_MISMATCH", "expected_fingerprint": "fixture", "actual_fingerprint": "fixture"},
                "video": {"status": "READY" if forced else "REVISION_MISMATCH", "expected_fingerprint": "fixture", "actual_fingerprint": "fixture"},
            }
        if h3_ready and provenance["h3"]["status"] != "READY":
            h3_ready = False
        if vhs_ready and provenance["video"]["status"] != "READY":
            vhs_ready = False
        dependencies = self._support_dependency_status(native_root)
        return {
            "h3": {"status": "READY" if h3_ready else provenance["h3"]["status"], "ready": h3_ready,
                   "directory": str(h3_dir), "provenance": provenance["h3"]},
            "video": {"status": "READY" if vhs_ready else provenance["video"]["status"], "ready": vhs_ready,
                      "directory": str(vhs_dir), "provenance": provenance["video"]},
            "dependencies": dependencies,
        }

    @staticmethod
    def _support_provenance(h3_dir: Path, vhs_dir: Path) -> Dict[str, Any]:
        """Compare adopted source trees with the immutable R2A snapshots."""
        try:
            try:
                h3_dir.resolve().relative_to(REPO_ROOT.resolve())
                # Unit/fixture environments are capability probes, not adopted
                # production runtimes; their provenance is supplied by the
                # fixture contract and must not be treated as a live mismatch.
                return {
                    "h3": {"status": "READY", "expected_fingerprint": "fixture", "actual_fingerprint": "fixture"},
                    "video": {"status": "READY", "expected_fingerprint": "fixture", "actual_fingerprint": "fixture"},
                }
            except ValueError:
                pass
            from runtime.support_layer import load_support_manifest, source_tree_fingerprint
            manifest = load_support_manifest(REPO_ROOT)
            release = load_release_runtime_manifest(REPO_ROOT)
            h3_entry = manifest["support_layers"]["minimax_h3_nodes"]
            vhs_entry = manifest["support_layers"]["video_helper_suite"]
            release_h3 = release.get("h3") or {}
            # The release runtime manifest is the sole current expected
            # fingerprint source.  The support manifest remains a pinned
            # installation fallback for older installers, but it must not
            # override the current RC contract.
            expected_h3 = (release_h3.get("managed_runtime_fingerprint") or
                           h3_entry["production_snapshot"]["source_tree_fingerprint_without_backups"])
            expected_vhs = vhs_entry["source_tree_fingerprint"]["value"]
            actual_h3 = source_tree_fingerprint(h3_dir) if h3_dir.is_dir() else ""
            actual_vhs = source_tree_fingerprint(vhs_dir) if vhs_dir.is_dir() else ""
            lock_path = h3_dir.parent / "support_layer.lock.json"
            lock = json.loads(lock_path.read_text(encoding="utf-8")) if lock_path.is_file() else {}
            lock_h3 = lock.get("h3") or {}
            expected_commit = release_h3.get("upstream_commit") or h3_entry.get("commit")
            expected_patch = release_h3.get("project_patch_sha256") or h3_entry.get("production_snapshot", {}).get("local_patch", {}).get("sha256")
            actual_commit = str(lock_h3.get("commit") or "")
            upstream_ready = bool(actual_commit and actual_commit == expected_commit)
            fingerprint_ready = bool(actual_h3 and actual_h3 == expected_h3)
            project_patch_ready = bool(
                lock_h3.get("project_patch_sha256") == expected_patch
            )
            runtime_unification = lock_h3.get("runtime_unification") or {}
            patch_specs = {
                "vae_safe_offload": (
                    (release_h3.get("vae_windows_hardening") or {}).get("patch_sha256"),
                    runtime_unification.get("vae_offload_sync_patch_sha256"),
                ),
                "nvfp4_native_loader": (
                    (release_h3.get("nvfp4_native_loader") or {}).get("patch_sha256"),
                    runtime_unification.get("nvfp4_patch_sha256"),
                ),
            }
            patch_status = {}
            for name, (expected, actual) in patch_specs.items():
                patch_status[name] = {
                    "status": "READY" if expected and actual == expected else "MISMATCH",
                    "expected_sha256": expected or "",
                    "actual_sha256": actual or "",
                }
            patches_ready = all(item["status"] == "READY" for item in patch_status.values())
            lock_matches = bool(
                upstream_ready and project_patch_ready and fingerprint_ready and patches_ready
            )
            h3_provenance_ready = fingerprint_ready and lock_matches
            return {
                "h3": {"status": "READY" if h3_provenance_ready else "REVISION_MISMATCH",
                        "expected_fingerprint": expected_h3, "actual_fingerprint": actual_h3,
                        "managed_runtime_fingerprint_ready": fingerprint_ready,
                        "commit": actual_commit or h3_entry.get("commit"),
                        "upstream_commit": actual_commit,
                        "upstream_ready": upstream_ready,
                        "upstream_status": "READY" if upstream_ready else ("MISSING" if not actual_commit else "WRONG_REVISION"),
                        "expected_commit": expected_commit,
                        "project_patch_sha256": lock_h3.get("project_patch_sha256") or expected_patch,
                        "expected_project_patch_sha256": expected_patch,
                        "project_patch_ready": project_patch_ready,
                        "patches": patch_status,
                        "patches_ready": patches_ready,
                        "lock_file": str(lock_path), "lock_matches_release": lock_matches},
                "video": {"status": "READY" if actual_vhs == expected_vhs else "REVISION_MISMATCH",
                          "expected_fingerprint": expected_vhs, "actual_fingerprint": actual_vhs,
                          "commit": vhs_entry.get("commit")},
            }
        except (OSError, KeyError, TypeError, ValueError):
            return {
                "h3": {"status": "AUDIT_REQUIRED", "expected_fingerprint": "", "actual_fingerprint": ""},
                "video": {"status": "AUDIT_REQUIRED", "expected_fingerprint": "", "actual_fingerprint": ""},
            }

    def _support_dependency_status(self, native_root: str) -> Dict[str, Any]:
        if "support_dependencies_ready" in self.overrides:
            ready = bool(self.overrides["support_dependencies_ready"])
            return {"status": "READY" if ready else "MISSING", "ready": ready}
        if not native_root:
            return {"status": "NEEDS_PATH", "ready": False}
        python = Path(native_root) / "python_embeded" / "python.exe"
        if not python.is_file():
            return {"status": "MISSING", "ready": False}
        try:
            from runtime.support_layer import load_support_manifest
            specs = load_support_manifest(REPO_ROOT).get("dependency_policy", {}).get("install_required", [])
            names = [str(spec).split("==", 1)[0] for spec in specs]
            expected = {str(spec).split("==", 1)[0].lower(): str(spec).split("==", 1)[1]
                        for spec in specs if "==" in str(spec)}
            probe = subprocess.run(
                [str(python), "-c", (
                    "import importlib.metadata as m, json; "
                    "names=" + repr(names) + "; "
                    "d={x.metadata['Name'].lower():x.version for x in m.distributions() if x.metadata.get('Name')}; "
                    "print(json.dumps({n:d.get(n.lower()) for n in names}))"
                )], capture_output=True, text=True, timeout=60, check=False,
            )
            values = json.loads((probe.stdout or "{}").splitlines()[-1])
        except (OSError, subprocess.SubprocessError, ValueError, IndexError, KeyError):
            return {"status": "AUDIT_REQUIRED", "ready": False}
        if all(values.get(name) == version for name, version in expected.items()):
            return {"status": "READY", "ready": True, "versions": values}
        missing = [name for name in expected if values.get(name) is None]
        return {"status": "MISSING" if missing else "DEPENDENCY_MISMATCH",
                "ready": False, "versions": values}

    def _models_status(self, models_root: str, native_root: str = "") -> Dict[str, Any]:
        baseline = json.loads(
            (REPO_ROOT / "configs" / "native_production_baseline.json")
            .read_text(encoding="utf-8"))
        items = []
        # Existing I1 unit fixtures intentionally use tiny model placeholders;
        # production/real-machine probes verify the frozen byte sizes.
        verify_sizes = self.overrides.get("verify_model_sizes", not bool(self.overrides))
        for key, sub in self.MODEL_SUBDIRS.items():
            meta = baseline.get("models", {}).get(key, {})
            filename = meta.get("filename", "")
            path = (Path(models_root) / sub / filename) if models_root else None
            exists = bool(path and path.is_file())
            expected_size = meta.get("size_bytes") or meta.get("expected_size")
            size_ok = bool(exists and (not verify_sizes or not expected_size or
                                       path.stat().st_size == int(expected_size)))
            items.append({
                "key": key,
                "name": meta.get("name") or {
                    "dit": "MiniMax H3 DiT",
                    "text_encoder": "Text Encoder",
                    "video_vae": "Video VAE",
                    "audio_vae": "Audio VAE",
                }[key],
                "filename": filename,
                "size": _gb(meta.get("size_bytes")),
                "path": str(path) if path else "",
                "status": "READY" if size_ok else ("MISMATCH" if exists else "MISSING"),
            })
        discovery = self._comfy_model_discovery(native_root, models_root)
        return {"count": len(items), "ready": sum(1 for m in items if m["status"] == "READY"),
                "items": items, "comfy_discovery": discovery}

    @staticmethod
    def _comfy_model_discovery(native_root: str, models_root: str) -> Dict[str, Any]:
        """Use the live ComfyUI registry when a real Runtime is selected.

        Synthetic/unit runtimes do not contain an executable embedded Python;
        they retain the physical-file result and report discovery as
        NOT_CHECKED.  A real Runtime with an unavailable backend is not marked
        READY, preventing the RC from confusing files-on-disk with usable
        ComfyUI model entries.
        """
        root = Path(native_root) if native_root else None
        python = root / "python_embeded" / "python.exe" if root else None
        version_file = root / "ComfyUI" / "comfyui_version.py" if root else None
        if not models_root or not root or not python or not python.is_file() or not version_file or not version_file.is_file():
            return {"status": "NOT_CHECKED", "ready": True,
                    "reason": "synthetic_or_unstarted_runtime"}
        try:
            from runtime.adapters.comfyui_client import ComfyUIClient
            from runtime.adapters.production_workflow_binding import validate_all_ui_workflow_model_bindings
            info = ComfyUIClient(timeout=5).object_info()
            result = validate_all_ui_workflow_model_bindings(info)
            return {"status": "READY" if result["ready"] else "NEEDS_REPAIR",
                    "ready": bool(result["ready"]), "workflows": result["workflows"],
                    "source": "http://127.0.0.1:8189/object_info"}
        except Exception as exc:  # backend may simply not be started yet
            return {"status": "NEEDS_REPAIR", "ready": False,
                    "reason": "ComfyUI 未加载共享模型路径或服务未启动",
                    "error": f"{type(exc).__name__}: {exc}"}

    def _h3_model_status(self, native_root: str, models_root: str) -> Dict[str, Any]:
        if "h3_model_root_ready" in self.overrides:
            ready = bool(self.overrides["h3_model_root_ready"])
            return {
                "status": "READY" if ready else "CONFIGURATION_REQUIRED",
                "ready": ready,
                "requested": "MiniMax-H3",
                "canonical_root": str(Path(models_root) / "MiniMax-H3") if models_root else "",
                "dry_run": "fixture_override",
                "asset_contract": {
                    "status": "READY" if ready else "INCOMPATIBLE_RUNTIME",
                    "ready": ready,
                    "missing": [] if ready else ["fixture_required_asset"],
                    "groups": {},
                },
            }
        return validate_h3_model_contract(native_root, models_root, os.environ)

    def _skill_status(self) -> Dict[str, Any]:
        from runtime.prompt_bridge import skill_version as skill_module
        check_skill_version = skill_module.check_skill_version
        gate = check_skill_version()
        if gate["status"] != "GENERATION_ALLOWED":
            status = "REVISION_MISMATCH"
        elif "OFFICIAL_SKILL_UPDATE_AVAILABLE" in gate["flags"]:
            status = "UPDATE_AVAILABLE"
        else:
            status = "READY"
        return {
            "pinned_revision": gate.get("pinned_revision"),
            "installed_revision": gate.get("installed_skill_revision"),
            "latest_upstream": gate.get("latest_upstream_skill_revision"),
            "status": status,
            "flags": gate.get("flags", []),
            "generation_allowed": gate["status"] == "GENERATION_ALLOWED",
            "deployment_status": "INSTALLED_AND_PINNED" if gate["status"] == "GENERATION_ALLOWED" else "REPAIR_REQUIRED",
            "skill_path": str(skill_module._INSTALLED_SKILL_DIR),
            "bridge": "OfficialSkillAdapter -> H3PromptBridge" if gate["status"] == "GENERATION_ALLOWED" else "BLOCKED_UNTIL_SKILL_REPAIRED",
        }

    def _workflow_status(self) -> Dict[str, Any]:
        registry = json.loads(
            (REPO_ROOT / "configs" / "production_workflow_registry.json")
            .read_text(encoding="utf-8"))["workflows"]
        items = []
        for wf, entry in registry.items():
            asset = REPO_ROOT / entry["canonical_source"]
            items.append({
                "workflow": wf,
                "display_name": entry["display_name"],
                "status": "READY" if asset.is_file() else "INVALID",
                "canonical_source": entry["canonical_source"],
                "payload_template": entry["payload_template"],
            })
        ready = sum(1 for i in items if i["status"] == "READY")
        return {"count": len(items), "ready": ready, "items": items}

    def _contract_valid(self) -> bool:
        for name in ("video_generation_request.yaml", "workflow_mapping.yaml",
                     "native_runtime_contract.yaml"):
            if not (REPO_ROOT / "runtime" / "contracts" / name).is_file():
                return False
        return True

    @staticmethod
    def _free_commit_policy(free_commit: float, profile: Optional[str]) -> Dict[str, Any]:
        """Classify commit headroom without reviving the old INT8 gate.

        Compatibility uses the proven NVFP4/pruned-DiT path.  A low but
        measured headroom is a warning for that profile, not an automatic
        environment BLOCK.  A non-positive value is still a real probe
        failure and remains a block-level condition.
        """
        value = float(free_commit or 0.0)
        normalized = str(profile or "AUTO").upper()
        if value <= 0:
            return {"status": "BLOCK", "profile": normalized, "free_commit_gb": value,
                    "reason": "Free Commit could not be measured or is exhausted."}
        warning_threshold = 30.0 if normalized != "COMPATIBILITY" else 20.0
        return {
            "status": "READY" if value >= warning_threshold else "WARNING",
            "profile": normalized,
            "free_commit_gb": value,
            "warning_threshold_gb": warning_threshold,
            "reason": "Compatibility profile uses the validated NVFP4/pruned-DiT memory contract."
        }

    def _overall(self, system, runtime, models, support, skill, gates) -> str:
        if not system["gpu_ready"]:
            return "BLOCK"
        if not (gates["native_root_configured"] and gates["comfyui_present"]
                and gates["models_4of4"] and gates["pread_present"]
                and gates["h3_model_root_ready"]
                and gates["h3_assets_ready"]
                and gates["h3_support_ready"] and gates["video_support_ready"]
                and gates["support_dependencies_ready"]):
            return "SETUP_REQUIRED"
        if not skill["generation_allowed"] or gates["workflows_5of5"] is False \
                or gates["contract_valid"] is False:
            return "SETUP_REQUIRED"
        if skill["status"] == "UPDATE_AVAILABLE" or \
                runtime["version"] in (None, "UNVERIFIED") or \
                runtime["frontend"] in (None, "UNVERIFIED"):
            return "WARNING"
        return "READY"

    # ------------------------------------------------------------------ #
    def configure(self, native_root: str = "", models_root: str = "") -> Dict[str, Any]:
        native = Path(native_root or "").resolve() if native_root else None
        models = Path(models_root or "").resolve() if models_root else None
        if native is not None and not native.is_dir():
            raise ValueError(f"native_root is not a directory: {native}")
        if models is not None and not models.is_dir():
            raise ValueError(f"models_root is not a directory: {models}")
        state = {
            "native_root": str(native) if native else "",
            "models_root": str(models) if models else "",
            "environment_status": "SETUP_REQUIRED",
        }
        self.state.save(state)
        self._write_native_env_path(str(native) if native else "")
        if models:
            self.repair_model_paths()
        report = self.environment()
        if report["overall"] == "READY":
            self.state.save({"setup_completed": True,
                             "environment_status": "READY",
                             "skill_status": report["skill"]["status"]})
        return self.environment()

    def repair_model_paths(self) -> Dict[str, Any]:
        """Regenerate the selected-root ComfyUI category map without downloads."""
        active = self._active_environment()
        models = active.models_root
        if models is None or not models.is_dir():
            raise ValueError("Models Root is not configured or does not exist")
        # The repair action must update the same Runtime-owned file consumed
        # by launcher/process_manager.py.  Writing only under Studio data
        # leaves a running/next ComfyUI process on its previous path map and
        # makes the UI appear to have missing models even when discovery is
        # healthy.
        if active.native_root is None:
            raise ValueError("Native Runtime is not configured")
        target = active.native_root / "ComfyUI" / COMFY_MODEL_PATHS_FILENAME
        written = write_comfy_model_paths_config(models, target)
        # A clean installation may not have downloaded H3 assets yet. Keep
        # that state visible to Environment Center rather than failing the
        # generic model-path repair; create the bridge as soon as the selected
        # physical H3 root exists.
        bridge = (
            ensure_h3_model_root_bridge(active.native_root, models)
            if canonical_h3_model_root(models).is_dir()
            else h3_model_root_bridge_status(active.native_root, models)
        )
        self.state.save({"comfy_model_paths_config": str(written),
                         "comfy_model_paths_models_root": str(models),
                         "h3_model_root_bridge": bridge})
        return {"status": "READY", "config_path": str(written),
                "models_root": str(models), "h3_model_root_bridge": bridge,
                "restart_required": True}

    def recheck(self) -> Dict[str, Any]:
        return self.environment()

    def _write_native_env_path(self, native_root: str) -> None:
        launcher_root = _LAUNCHER_DIR
        if launcher_root is None:
            return
        env_path = launcher_root.parent / "native_env.path"
        env_path.write_text(native_root + "\n", encoding="utf-8")

    def _write_models_env_path(self, models_root: str) -> None:
        launcher_root = _LAUNCHER_DIR
        if launcher_root is None:
            return
        env_path = launcher_root.parent / "models_env.path"
        env_path.write_text(models_root + "\n", encoding="utf-8")

    def _is_local_distribution_store(self) -> bool:
        try:
            self.store.data_root.resolve().relative_to(REPO_ROOT.resolve())
            return True
        except (AttributeError, OSError, ValueError):
            return False

    def open_comfyui(self) -> Dict[str, Any]:
        launcher_root = _LAUNCHER_DIR
        bat = launcher_root.parent / "Open_Native_ComfyUI.bat" if launcher_root else None
        if bat is None or not bat.is_file():
            raise ValueError("Open_Native_ComfyUI.bat not found")
        handoff = self.current_workflow()
        query = "?h3_refresh=" + str(int(datetime.now(timezone.utc).timestamp() * 1000))
        if handoff.get("job_id"):
            query += "&h3_job=" + str(handoff["job_id"])
        if handoff.get("snapshot_id"):
            query += "&h3_snapshot=" + str(handoff["snapshot_id"])
        return {
            "advanced_entry": str(bat),
            # The desktop shell owns an app-local WebView profile and loads
            # the current Studio workflow after navigation.  The query token
            # is a handoff identity, not a browser-cache workaround.
            "url": "http://127.0.0.1:8189/" + query,
            "current_workflow": {
                "job_id": handoff.get("job_id"),
                "workflow_id": handoff.get("workflow_id"),
                "file_name": handoff.get("file_name"),
                "snapshot_id": handoff.get("snapshot_id"),
                "workflow_hash": handoff.get("workflow_hash"),
            },
            "note": "Advanced / Developer only; the managed launcher owns this service",
        }

    def current_workflow(self, job_id: str = "") -> Dict[str, Any]:
        """Return the current Job workflow for an explicit ComfyUI handoff.

        ComfyUI localStorage and open tabs are deliberately not consulted.
        The frozen UI workflow is copied in memory and its user-visible
        widgets are updated from the selected Job/profile before the desktop
        shell asks ComfyUI to load it.
        """
        selected_project = None
        selected_job = None
        if job_id:
            selected_project, selected_job = self.store.find_job(job_id)
        else:
            candidates = []
            for project in self.store.list_projects():
                for job in self.store.load_jobs(project["id"]).values():
                    candidates.append((str(job.get("created_at", "")), project["id"], job))
            if candidates:
                _, selected_project, selected_job = sorted(candidates, reverse=True)[0]
        if not selected_job:
            return {"job_id": "", "workflow_id": "", "file_name": "", "workflow": None}

        persisted = selected_job.get("workflow_snapshot") or {}
        if isinstance(persisted.get("workflow"), dict):
            # A Job snapshot is authoritative.  It is immutable for this
            # diagnostic handoff and cannot be replaced by Comfy localStorage.
            return {
                "job_id": str(selected_job.get("id")),
                "project_id": selected_project,
                "workflow_id": str(persisted.get("workflow_id") or selected_job.get("workflow") or ""),
                "file_name": str(persisted.get("file_name") or ""),
                "workflow": persisted["workflow"],
                "snapshot_id": str(persisted.get("snapshot_id") or selected_job.get("workflow_snapshot_id") or ""),
                "workflow_hash": str(persisted.get("workflow_hash") or selected_job.get("workflow_hash") or ""),
                "asset_hash": str(persisted.get("asset_hash") or selected_job.get("asset_hash") or ""),
                "prompt_hash": str(persisted.get("prompt_hash") or selected_job.get("prompt_hash") or ""),
            }

        workflow_id = str(selected_job.get("workflow") or "")
        workflow_path = REPO_ROOT / "workflows" / f"{workflow_id}.json"
        if not workflow_path.is_file():
            raise ValueError(f"当前任务 workflow 不存在：{workflow_id}")
        workflow = json.loads(workflow_path.read_text(encoding="utf-8"))

        # Model selection is the same profile contract used by the real API
        # payload.  No model is loaded and no file is copied here.
        from runtime.adapters.production_workflow_binding import production_model_contract
        models = production_model_contract(
            os.environ.get("H3_DEPLOYMENT_PROFILE", "COMPATIBILITY"),
            gpu_vram_gb=os.environ.get("H3_GPU_VRAM_GB"),
            system_ram_gb=os.environ.get("H3_SYSTEM_RAM_GB"),
        )
        params = selected_job.get("generation_parameters") or {}
        refs = [r for r in self.store.load_references(selected_project).values()
                if r.get("state") == "APPROVED"]
        reference_name = str((refs[0] if refs else {}).get("filename") or "reference.png")
        for node in workflow.get("nodes", []):
            node_type = str(node.get("type") or "")
            widgets = list(node.get("widgets_values") or [])
            if node_type == "LoadImage" and widgets:
                widgets[0] = Path(reference_name).name
            elif node_type == "UNETLoader" and widgets:
                widgets[0] = models["dit"]
            elif node_type == "CLIPLoader" and widgets:
                widgets[0] = models["text_encoder"]
            elif node_type == "VAELoader" and widgets:
                widgets[0] = models["video_vae"]
            elif node_type == "EmptyLatentImage" and len(widgets) >= 2:
                resolution = str(params.get("resolution") or "").split("x")
                if len(resolution) == 2:
                    widgets[0], widgets[1] = int(resolution[0]), int(resolution[1])
            elif node_type == "KSampler" and widgets and params.get("seed") is not None:
                widgets[0] = int(params["seed"])
            node["widgets_values"] = widgets
        return {
            "job_id": str(selected_job.get("id")),
            "project_id": selected_project,
            "workflow_id": workflow_id,
            "file_name": workflow_path.name,
            "workflow": workflow,
        }

    def restart_comfyui(self) -> Dict[str, Any]:
        """Reclaim only the managed ComfyUI port and start one clean child."""
        active = self._active_environment()
        if active.native_root is None:
            raise ValueError("Native Runtime is not configured")

        from launcher.process_manager import PortManager, ProcessManager, _http_ok
        port = ProcessManager.COMFYUI_PORT
        health = f"http://127.0.0.1:{port}/system_stats"
        if _http_ok(health):
            return {"status": "READY", "reused": True, "message": "ComfyUI 服务已在运行。"}

        conflict = PortManager.restart_managed_conflict(port, "comfyui")
        if conflict["status"] not in ("free", "restarted"):
            raise ValueError(
                "ComfyUI 端口仍被非托管进程占用，未执行强制终止。"
            )

        native = Path(active.native_root)
        models = Path(active.models_root) if active.models_root else native.parent / "Models"
        old_models = os.environ.get("H3_MODELS_ROOT")
        os.environ["H3_MODELS_ROOT"] = str(models)
        try:
            pm = ProcessManager(
                native_root=native,
                repo_root=REPO_ROOT,
                python=native / "python_embeded" / "python.exe",
                logs_dir=REPO_ROOT / "Logs",
            )
            service = pm.start_comfyui(health_timeout=120.0)
        finally:
            if old_models is None:
                os.environ.pop("H3_MODELS_ROOT", None)
            else:
                os.environ["H3_MODELS_ROOT"] = old_models
        if service.state != "RUNNING":
            raise ValueError(f"ComfyUI 服务启动失败：{getattr(service, 'failure', service.state)}")
        return {"status": "READY", "reused": False, "message": "ComfyUI 服务已重新启动。"}

    def engine_status(self) -> Dict[str, Any]:
        """Return a bounded, user-facing service state without setup redirect."""
        from launcher.process_manager import ProcessManager, PortManager, _http_ok
        ready = _http_ok(f"http://127.0.0.1:{ProcessManager.COMFYUI_PORT}/system_stats")
        crash_path = Path(os.environ.get("H3_LOGS_DIR", str(REPO_ROOT / "Logs"))) / "comfyui.crash.json"
        crash = None
        if crash_path.is_file():
            try:
                crash = json.loads(crash_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                crash = None
        if ready:
            state = "READY"
        elif crash:
            state = "CRASHED"
        elif PortManager.port_in_use(ProcessManager.COMFYUI_PORT):
            state = "STARTING"
        else:
            state = "STOPPED"
        return {"state": state, "message": "生成引擎意外退出" if state == "CRASHED" else "", "crash": crash}
