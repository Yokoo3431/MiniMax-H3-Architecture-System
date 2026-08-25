"""One supervised I2-G1 Strategy-A language load/offload validation.

This diagnostic consumes exactly one authorized GPU child process.  It loads
only the pinned H3 Qwen text encoder, records the BF16 static contract and the
I2 reservation state, then calls the real ``load_for_inference`` operation.
If that succeeds it calls the real ``offload_after_inference`` once.  It never
executes visual conditioning, language forward, /prompt, W01, DiT, VAE, VHS,
or a sampler.
"""

from __future__ import annotations

from collections import Counter
import ctypes
import ctypes.wintypes as wintypes
import json
import logging
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import traceback


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.probe_qwen_visual_device_cycle import (  # noqa: E402
    ACCESS_VIOLATION_CODES,
    _marker,
    _module_inventory,
    _runtime_and_models,
)


EXPECTED_H3_COMMIT = "d6c5f7b0d4e03936ac4a9834be63ecc6b5637dad"
EXPECTED_H3_FINGERPRINT = "2ba065a0f5d68471cd621c87b458088b9dc4ee67e5d56abe7b360ecb662cd713"
EXPECTED_H3_PATCH_SHA256 = "488ab271e68d226a690f3c1dc322a9fc15a0eba7273045e890a871de2c0196bd"
EXPECTED_BOUNDARY_PATCH_SHA256 = "67ca71fd28ddedf7cad6f3bb837b6b825ee08145efe518671574e19522dad2ac"
EXPECTED_VHS_COMMIT = "4ee72c065db22c9d96c2427954dc69e7b908444b"
EXPECTED_MARGIN_BYTES = 1_556_874_496
EXPECTED_STATIC_BYTES = 1_556_874_496
EXPECTED_FP32_STATIC_BYTES = 3_113_748_992
EXPECTED_HEADROOM = 3_221_225_472
EXPECTED_RESERVE = 6_334_974_464
EXPECTED_PARENT_MIN_FREE_COMMIT = 64_444_190_720

# Historical I2-G1 remains available; F1-G1 selects the corrected 203-slot
# contract plus the mandatory post-materialization resource gate. C1-G1 adds
# only the owner-controlled clean-host parent gate before materialization.
STAGE_PREFIX = "I2G1"


def _stage(value: str) -> str:
    return value.replace("I2G1", STAGE_PREFIX)


class _PERFORMANCE_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("CommitTotal", ctypes.c_size_t),
        ("CommitLimit", ctypes.c_size_t),
        ("CommitPeak", ctypes.c_size_t),
        ("PhysicalTotal", ctypes.c_size_t),
        ("PhysicalAvailable", ctypes.c_size_t),
        ("SystemCache", ctypes.c_size_t),
        ("KernelTotal", ctypes.c_size_t),
        ("KernelPaged", ctypes.c_size_t),
        ("KernelNonpaged", ctypes.c_size_t),
        ("PageSize", ctypes.c_size_t),
        ("HandleCount", wintypes.DWORD),
        ("ProcessCount", wintypes.DWORD),
        ("ThreadCount", wintypes.DWORD),
    ]


class _MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", wintypes.DWORD),
        ("dwMemoryLoad", wintypes.DWORD),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def _windows_memory() -> dict[str, int | float]:
    info = _PERFORMANCE_INFORMATION()
    info.cb = ctypes.sizeof(info)
    psapi = ctypes.WinDLL("psapi")
    if not psapi.GetPerformanceInfo(ctypes.byref(info), info.cb):
        raise OSError("GetPerformanceInfo failed")
    status = _MEMORYSTATUSEX()
    status.dwLength = ctypes.sizeof(status)
    kernel32 = ctypes.WinDLL("kernel32")
    if not kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise OSError("GlobalMemoryStatusEx failed")
    free_commit = (info.CommitLimit - info.CommitTotal) * info.PageSize
    return {
        "free_commit_bytes": int(free_commit),
        "free_commit_gib": round(free_commit / 2**30, 3),
        "available_ram_bytes": int(status.ullAvailPhys),
        "available_ram_gib": round(status.ullAvailPhys / 2**30, 3),
    }


def _runtime_lock_state() -> dict:
    path = ROOT / "launcher" / "runtime.lock"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _support_lock(runtime: Path) -> dict:
    path = runtime / "ComfyUI" / "custom_nodes" / "support_layer.lock.json"
    lock = json.loads(path.read_text(encoding="utf-8"))
    h3 = lock.get("h3", {})
    vhs = lock.get("video_helper_suite", {})
    if h3.get("commit") != EXPECTED_H3_COMMIT:
        raise RuntimeError("H3 support commit mismatch")
    if h3.get("source_tree_fingerprint") != EXPECTED_H3_FINGERPRINT:
        raise RuntimeError("H3 support fingerprint mismatch")
    if h3.get("project_patch_sha256") != EXPECTED_H3_PATCH_SHA256:
        raise RuntimeError("H3 support patch mismatch")
    if h3.get("strategy_a", {}).get("target_dtype") != "bfloat16":
        raise RuntimeError("Strategy-A target dtype mismatch")
    if h3.get("strategy_a", {}).get("visual_dtype") != "preserved_fp32":
        raise RuntimeError("visual dtype contract mismatch")
    if h3.get("strategy_a", {}).get("quantized_linear_contract") != "preserved_350":
        raise RuntimeError("quantized Linear contract mismatch")
    if h3.get("memory_policy", {}).get("name") != "static_transfer_safety_margin":
        raise RuntimeError("I2 memory policy missing")
    if h3.get("language_boundary_instrumentation_patch_sha256") != EXPECTED_BOUNDARY_PATCH_SHA256:
        raise RuntimeError("language-load boundary instrumentation missing")
    if vhs.get("commit") != EXPECTED_VHS_COMMIT:
        raise RuntimeError("VHS support commit mismatch")
    if lock.get("pread", {}).get("environment") != "H3_WINDOWS_SAFE_LOAD=pread":
        raise RuntimeError("PREAD support lock mismatch")
    return lock


def _loaded_model_summary(mm, patcher=None) -> dict:
    loaded = list(getattr(mm, "current_loaded_models", ()) or ())
    matches = 0
    for item in loaded:
        model = getattr(item, "model", None)
        if model is patcher or getattr(model, "model", None) is patcher:
            matches += 1
    return {
        "current_loaded_models_count": len(loaded),
        "language_patcher_records": matches,
    }


def _safe_loaded_size(patcher) -> int | None:
    if patcher is None:
        return None
    method = getattr(patcher, "loaded_size", None)
    if not callable(method):
        return None
    try:
        return int(method())
    except BaseException:
        return None


def _language_summary(handle) -> dict:
    roots = list(handle._movable())
    linears = tuple(getattr(handle, "_streaming_linears", ()) or ())
    linear_devices: Counter[str] = Counter()
    linear_dtypes: Counter[str] = Counter()
    for module in linears:
        for value in list(module.parameters(recurse=False)) + list(module.buffers(recurse=False)):
            linear_devices[str(value.device)] += 1
            linear_dtypes[str(value.dtype)] += 1

    helper = sys.modules[handle.__class__.__module__].__dict__
    collect_linears = helper.get("_quantized_language_linears")
    direct_slots = helper.get("_direct_tensor_slots")
    static_dtypes: Counter[str] = Counter()
    static_devices: Counter[str] = Counter()
    static_count = 0
    static_bytes = 0
    fp32_equivalent = 0
    if callable(collect_linears) and callable(direct_slots):
        candidate_linears = collect_linears(roots)
        excluded = {id(module) for module in candidate_linears}
        seen: set[int] = set()
        for _module, _collection, _name, tensor in direct_slots(roots, excluded):
            tensor_id = id(tensor)
            if tensor_id in seen:
                continue
            seen.add(tensor_id)
            static_count += 1
            static_bytes += int(tensor.nbytes)
            static_dtypes[str(tensor.dtype)] += 1
            static_devices[str(tensor.device)] += 1
            if tensor.is_floating_point():
                fp32_equivalent += int(tensor.numel()) * 4
        detected_linears = len(candidate_linears)
    else:
        detected_linears = len(linears)

    return {
        "quantized_linear_count": detected_linears,
        "streaming_linear_tensor_device_distribution": dict(linear_devices),
        "streaming_linear_tensor_dtype_distribution": dict(linear_dtypes),
        "direct_static_tensor_count": static_count,
        "direct_static_dtype_distribution": dict(static_dtypes),
        "direct_static_device_distribution": dict(static_devices),
        "direct_static_bytes": static_bytes,
        "fp32_equivalent_static_bytes": fp32_equivalent,
        "strategy_a_safety_margin_bytes": max(0, fp32_equivalent - static_bytes),
        "handle_static_storage_bytes": int(getattr(handle, "_static_storage_bytes", 0)),
        "handle_fp32_equivalent_bytes": int(getattr(handle, "_static_storage_bytes", 0))
        + int(getattr(handle, "_static_transfer_safety_margin_bytes", 0)),
        "handle_static_transfer_safety_margin_bytes": int(
            getattr(handle, "_static_transfer_safety_margin_bytes", 0)
        ),
    }


def _state_summary(handle, mm, torch) -> dict:
    patcher = getattr(handle, "_linear_patcher", None)
    free, total = torch.cuda.mem_get_info()
    return {
        "cuda_allocated_bytes": int(torch.cuda.memory_allocated()),
        "cuda_reserved_bytes": int(torch.cuda.memory_reserved()),
        "cuda_free_bytes": int(free),
        "cuda_total_bytes": int(total),
        "windows_memory": _windows_memory(),
        "comfy_model_management": _loaded_model_summary(mm, patcher),
        "patcher": {
            "present": patcher is not None,
            "type": type(patcher).__name__ if patcher is not None else None,
            "loaded_size_bytes": _safe_loaded_size(patcher),
        },
        "compute_device": str(getattr(handle, "_compute_device", None))
        if getattr(handle, "_compute_device", None) is not None
        else None,
        "inference_active": bool(getattr(handle, "_inference_active", False)),
        "language": _language_summary(handle),
        "visual": _module_inventory(handle.model.visual),
    }


def _looks_like_cuda_oom(exc: BaseException) -> bool:
    text = f"{type(exc).__name__}: {exc}".lower()
    return (
        "out of memory" in text
        or "cuda error: out of memory" in text
        or "cudnn_status_alloc_failed" in text
    )


def _child(log_path: Path) -> int:
    events: list[dict] = []
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    with log_path.open("w", encoding="utf-8", buffering=1) as stream:
        class Tee:
            def write(self, value):
                original_stdout.write(value)
                stream.write(value)
                stream.flush()

            def flush(self):
                original_stdout.flush()
                stream.flush()

        class TraceHandler(logging.Handler):
            def emit(self, record):
                events.append({"level": record.levelname, "message": record.getMessage()})

        trace = TraceHandler()
        h3_logger = logging.getLogger("minimax_h3_nodes")
        old_level = h3_logger.level
        h3_logger.addHandler(trace)
        h3_logger.setLevel(logging.INFO)
        sys.stdout = Tee()
        sys.stderr = Tee()
        try:
            runtime, models = _runtime_and_models()
            lock = _support_lock(runtime)
            memory = _windows_memory()
            disk = shutil.disk_usage(models.anchor)
            runtime_lock = _runtime_lock_state()
            _marker(
                stream,
                _stage("I2G1-PRECHECK"),
                runtime=str(runtime),
                models_root=str(models),
                h3_commit=lock["h3"]["commit"],
                h3_fingerprint=lock["h3"]["source_tree_fingerprint"],
                h3_patch_sha256=lock["h3"]["project_patch_sha256"],
                vhs_commit=lock["video_helper_suite"]["commit"],
                torch_env=os.environ.get("H3_WINDOWS_SAFE_LOAD"),
                job_running=bool(runtime_lock.get("job_running", False)),
                **memory,
                d_free_gib=round(disk.free / 2**30, 3),
            )
            if memory["free_commit_bytes"] < 30 * 2**30:
                _marker(stream, _stage("I2G1-PRECHECK_BLOCKED"), reason="FREE_COMMIT_BELOW_30_GIB", **memory)
                return 20
            if bool(runtime_lock.get("job_running", False)):
                _marker(stream, _stage("I2G1-PRECHECK_BLOCKED"), reason="GPU_JOB_ALREADY_RUNNING")
                return 20

            comfy_root = runtime / "ComfyUI"
            h3_root = comfy_root / "custom_nodes" / "ComfyUI_RH_MinMaxH3"
            os.chdir(comfy_root)
            sys.path.insert(0, str(comfy_root))
            sys.path.insert(0, str(h3_root))

            import torch
            from minimax_h3_nodes.api import _shared
            from minimax_h3_nodes.runtime.qwen_encoder.loading import load_h3_text_encoder
            import comfy.model_management as mm

            if not torch.cuda.is_available():
                _marker(stream, _stage("I2G1-PRECHECK_BLOCKED"), reason="CUDA_UNAVAILABLE")
                return 20

            selector = _shared._default_te_model_name()
            root_name = "MiniMax-H3"
            partition_root, _info, _sigma = _shared._resolve_t2va_release(
                root_name,
                required_component=_shared._selector_to_component_dirname(
                    selector, "text_encoder", "fl2va", model_root=root_name
                ),
                required_files=("config.json",),
            )
            selected_component, selected_weights = _shared._resolve_selected_component(
                partition_root,
                selector,
                keys=("text_encoder", "qwen3vl", "qwen"),
                label="Text Encoder",
                partition="FL2VA",
                required_files=("config.json",),
            )
            handle = load_h3_text_encoder(
                model_root=str(partition_root.parent),
                partition="FL2VA",
                require_multimodal_processor=True,
                text_encoder_path=str(selected_component),
                text_encoder_weights=str(selected_weights) if selected_weights else None,
                dtype="bfloat16",
                device="auto",
                offload_device="cpu",
            )

            fresh = _state_summary(handle, mm, torch)
            fresh_ok = (
                not fresh["patcher"]["present"]
                and fresh["compute_device"] is None
                and not fresh["inference_active"]
                and fresh["visual"]["parameter_count"] == 351
                and fresh["visual"]["buffer_count"] == 1
                and fresh["visual"]["tensor_count"] == 352
                and fresh["visual"]["device_distribution"] == {"cpu": 352}
                and fresh["visual"]["dtype_distribution"] == {"torch.float32": 352}
                and fresh["language"]["direct_static_tensor_count"] == 203
                and fresh["language"]["direct_static_bytes"] == EXPECTED_STATIC_BYTES
                and fresh["language"]["direct_static_dtype_distribution"] == {"torch.bfloat16": 203}
                and fresh["language"]["quantized_linear_count"] == 350
            )
            if not fresh_ok:
                _marker(stream, _stage("I2G1-OTHER_FAILURE"), reason="FRESH_STATE_CONTRACT_FAILED", state=fresh)
                return 30
            _marker(
                stream,
                _stage("I2G1-01"),
                label=("AFTER_QWEN_MATERIALIZATION" if STAGE_PREFIX in ("F1G1", "C1G1") else "FRESH_QWEN_READY"),
                component=str(selected_component),
                weights=str(selected_weights) if selected_weights else None,
                torch=str(torch.__version__),
                cuda=torch.version.cuda,
                memory_required_bytes=EXPECTED_RESERVE,
                expected_headroom_bytes=EXPECTED_HEADROOM,
                expected_margin_bytes=EXPECTED_MARGIN_BYTES,
                state=fresh,
            )

            # F1-G1 requires a second Free Commit check after Qwen
            # materialization and before the first language CUDA load.
            if STAGE_PREFIX in ("F1G1", "C1G1") and fresh["windows_memory"]["free_commit_bytes"] < 30 * 2**30:
                _marker(
                    stream,
                    _stage("I2G1-POST-MATERIALIZATION-BLOCKED" if STAGE_PREFIX == "C1G1" else "I2G1-RESOURCE_BLOCKED"),
                    classification="POST_MATERIALIZATION_RESOURCE_BLOCKED",
                    reason="FREE_COMMIT_BELOW_30_GIB_AFTER_QWEN_MATERIALIZATION",
                    state=fresh,
                )
                return 20

            before = _state_summary(handle, mm, torch)
            _marker(stream, _stage("I2G1-02"), label="BEFORE_LOAD_FOR_INFERENCE", state=before)
            try:
                handle.load_for_inference()
            except torch.OutOfMemoryError as exc:
                after_error = _state_summary(handle, mm, torch)
                _marker(
                    stream,
                    _stage("I2G1-OOM"),
                    classification="CUDA_OOM_AFTER_I2_MARGIN",
                    exception=type(exc).__name__,
                    message=str(exc),
                    state=after_error,
                    trace_messages=events[-40:],
                )
                return 41
            except BaseException as exc:
                after_error = _state_summary(handle, mm, torch)
                if _looks_like_cuda_oom(exc):
                    _marker(
                        stream,
                        _stage("I2G1-OOM"),
                        classification="CUDA_OOM_AFTER_I2_MARGIN",
                        exception=type(exc).__name__,
                        message=str(exc),
                        state=after_error,
                        trace_messages=events[-40:],
                    )
                    return 41
                _marker(
                    stream,
                    _stage("I2G1-OTHER_FAILURE"),
                    classification="OTHER_TARGETED_FAILURE",
                    exception=type(exc).__name__,
                    message=str(exc),
                    state=after_error,
                    trace_messages=events[-40:],
                )
                traceback.print_exc()
                return 40

            loaded = _state_summary(handle, mm, torch)
            if not loaded["patcher"]["present"] or not loaded["inference_active"]:
                _marker(
                    stream,
                    _stage("I2G1-OOM"),
                    classification="CUDA_OOM_AFTER_I2_MARGIN",
                    reason="LOAD_RETURNED_WITHOUT_ACTIVE_LANGUAGE_STATE",
                    state=loaded,
                    trace_messages=events[-40:],
                )
                return 41
            if loaded["language"]["direct_static_dtype_distribution"] != {"torch.bfloat16": 203}:
                _marker(stream, _stage("I2G1-DTYPE_FAILURE"), state=loaded)
                return 42
            _marker(
                stream,
                _stage("I2G1-03"),
                label="LANGUAGE_LOAD_SUCCEEDED",
                state=loaded,
                trace_messages=events[-40:],
            )

            _marker(stream, _stage("I2G1-04"), label="BEFORE_OFFLOAD", state=_state_summary(handle, mm, torch))
            try:
                handle.offload_after_inference()
            except BaseException as exc:
                failed = _state_summary(handle, mm, torch)
                _marker(
                    stream,
                    _stage("I2G1-PATCHER_FAILURE"),
                    classification="MODELPATCHER_LIFECYCLE_FAILURE",
                    exception=type(exc).__name__,
                    message=str(exc),
                    state=failed,
                )
                traceback.print_exc()
                return 43

            offloaded = _state_summary(handle, mm, torch)
            physical_unloaded = (
                offloaded["patcher"]["loaded_size_bytes"] in (0, None)
                and offloaded["compute_device"] is None
                and not offloaded["inference_active"]
            )
            if not physical_unloaded:
                _marker(
                    stream,
                    _stage("I2G1-PATCHER_FAILURE"),
                    classification="MODELPATCHER_LIFECYCLE_FAILURE",
                    reason="PHYSICAL_PATCHER_REMAINS_LOADED",
                    state=offloaded,
                )
                return 43
            _marker(stream, _stage("I2G1-05"), label="LANGUAGE_OFFLOAD_SUCCEEDED", state=offloaded)
            _marker(stream, _stage("I2G1-06"), label="PROCESS_SURVIVED", state=offloaded)
            return 0
        except BaseException as exc:
            _marker(stream, _stage("I2G1-OTHER_FAILURE"), exception=type(exc).__name__, message=str(exc))
            traceback.print_exc()
            return 40
        finally:
            h3_logger.removeHandler(trace)
            h3_logger.setLevel(old_level)
            sys.stdout = original_stdout
            sys.stderr = original_stderr


def _nvidia_smi_snapshot() -> str | None:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.free", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return result.stdout.strip() or result.stderr.strip() or None
    except BaseException as exc:
        return f"UNAVAILABLE: {type(exc).__name__}: {exc}"


def _parent() -> int:
    runtime, models = _runtime_and_models()
    lock = _support_lock(runtime)
    runtime_lock = _runtime_lock_state()
    if bool(runtime_lock.get("job_running", False)):
        print(json.dumps({"classification": "PRECHECK_BLOCKED", "reason": "GPU_JOB_ALREADY_RUNNING"}, indent=2))
        return 20
    if STAGE_PREFIX == "C1G1":
        output_dir_name = "f3_c2m1_i2_f1_g1_f2_c1_g1"
    elif STAGE_PREFIX == "F1G1":
        output_dir_name = "f3_c2m1_i2_f1_g1"
    else:
        output_dir_name = "f3_c2m1_i2_g1"
    output_dir = ROOT / "userdata" / "cache" / "temp" / output_dir_name
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    if STAGE_PREFIX == "C1G1":
        file_prefix = "c1g1"
    elif STAGE_PREFIX == "F1G1":
        file_prefix = "f1g1"
    else:
        file_prefix = "i2g1"
    log_path = output_dir / f"{file_prefix}_language_child_{stamp}.log"
    result_path = output_dir / f"{file_prefix}_language_result_{stamp}.json"
    preflight = {
        "runtime": str(runtime),
        "models_root": str(models),
        "h3_commit": lock["h3"]["commit"],
        "h3_fingerprint": lock["h3"]["source_tree_fingerprint"],
        "h3_patch_sha256": lock["h3"]["project_patch_sha256"],
        "vhs_commit": lock["video_helper_suite"]["commit"],
        "job_running": bool(runtime_lock.get("job_running", False)),
        "windows_memory": _windows_memory(),
        "d_free_gib": round(shutil.disk_usage(models.anchor).free / 2**30, 3),
        "gpu_query_before_child": _nvidia_smi_snapshot(),
        "start_timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    parent_gate = (
        EXPECTED_PARENT_MIN_FREE_COMMIT
        if STAGE_PREFIX == "C1G1"
        else 30 * 2**30
    )
    if preflight["windows_memory"]["free_commit_bytes"] < parent_gate:
        summary = {
            "classification": (
                "PARENT_RESOURCE_PRECHECK_BLOCKED"
                if STAGE_PREFIX == "C1G1"
                else "PRECHECK_BLOCKED"
            ),
            **preflight,
            "required_parent_free_commit_bytes": parent_gate,
            "reason": "FREE_COMMIT_BELOW_REQUIRED_PARENT_GATE",
        }
        result_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 20

    from runtime.h3_model_root import h3_process_environment

    env = os.environ.copy()
    env.update(h3_process_environment(str(models)))
    env["H3_WINDOWS_SAFE_LOAD"] = "pread"
    env["PYTHONUNBUFFERED"] = "1"
    comfy_root = runtime / "ComfyUI"
    env["PYTHONPATH"] = os.pathsep.join(
        [str(ROOT), str(comfy_root), str(comfy_root / "custom_nodes" / "ComfyUI_RH_MinMaxH3"), env.get("PYTHONPATH", "")]
    ).strip(os.pathsep)
    managed_python = runtime / "python_embeded" / "python.exe"
    if not managed_python.is_file():
        raise RuntimeError(f"managed embedded Python missing: {managed_python}")
    started = time.time()
    preflight["start_timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    log_path.write_text(json.dumps({"parent": STAGE_PREFIX, **preflight}, ensure_ascii=False) + "\n", encoding="utf-8")
    child = subprocess.Popen(
        [str(managed_python), str(Path(__file__).resolve()), "--child", "--log", str(log_path)]
        + (["--f1g1"] if STAGE_PREFIX == "F1G1" else [])
        + (["--c1g1"] if STAGE_PREFIX == "C1G1" else []),
        cwd=str(comfy_root),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    with log_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"parent": STAGE_PREFIX, "pid": child.pid}, ensure_ascii=False) + "\n")
    code = child.wait()
    ended = time.time()
    text = log_path.read_text(encoding="utf-8", errors="replace")
    stages = re.findall(r'"stage":\s*"([^"]+)"', text)
    last_stage = stages[-1] if stages else "NONE"
    success_stage = _stage("I2G1-06")
    oom_stage = _stage("I2G1-OOM")
    dtype_stage = _stage("I2G1-DTYPE_FAILURE")
    patcher_stage = _stage("I2G1-PATCHER_FAILURE")
    precheck_stage = _stage("I2G1-PRECHECK_BLOCKED")
    resource_stage = _stage("I2G1-RESOURCE_BLOCKED")
    if code == 0 and success_stage in stages:
        classification = (
            "LANGUAGE_MEMORY_LIFECYCLE_PASS"
            if STAGE_PREFIX == "C1G1"
            else "MEMORY_POLICY_LANGUAGE_LIFECYCLE_PASS"
        )
    elif oom_stage in stages or code == 41:
        classification = (
            "CUDA_OOM_AFTER_CLEAN_HOST_AND_I2_POLICY"
            if STAGE_PREFIX == "C1G1"
            else "CUDA_OOM_AFTER_I2_MARGIN"
        )
    elif dtype_stage in stages or code == 42:
        classification = "BF16_RUNTIME_DTYPE_FAILURE"
    elif patcher_stage in stages or code == 43:
        classification = "MODELPATCHER_LIFECYCLE_FAILURE"
    elif code in ACCESS_VIOLATION_CODES:
        classification = "NATIVE_RUNTIME_FAILURE"
    elif resource_stage in stages or (
        STAGE_PREFIX in ("F1G1", "C1G1") and code == 20
    ):
        classification = "POST_MATERIALIZATION_RESOURCE_BLOCKED"
    elif precheck_stage in stages or code == 20:
        classification = "PRECHECK_BLOCKED"
    else:
        classification = "OTHER_TARGETED_FAILURE"
    summary = {
        "classification": classification,
        "pid": child.pid,
        "start_timestamp": preflight["start_timestamp"],
        "end_timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "elapsed_seconds": round(ended - started, 3),
        "exit_code": code,
        "last_stage": last_stage,
        "stages": stages,
        "log_path": str(log_path),
        "result_path": str(result_path),
        "preflight": preflight,
        "prompt_submitted": False,
        "studio_job_created": False,
        "visual_executed": False,
        "language_forward_entered": False,
        "encode_ids_called": False,
        "dit_loaded": False,
        "vae_loaded": False,
        "vhs_loaded": False,
    }
    result_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--log", type=Path)
    parser.add_argument("--f1g1", action="store_true")
    parser.add_argument("--c1g1", action="store_true")
    args = parser.parse_args()
    global STAGE_PREFIX
    STAGE_PREFIX = "C1G1" if args.c1g1 else ("F1G1" if args.f1g1 else "I2G1")
    if args.child:
        if args.log is None:
            raise SystemExit("--child requires --log")
        return _child(args.log)
    return _parent()


if __name__ == "__main__":
    raise SystemExit(main())
