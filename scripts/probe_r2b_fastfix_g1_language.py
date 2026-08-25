"""One authorized R2B-FASTFIX-G1 language lifecycle validation.

The parent performs the exact host gate, then starts one managed-runtime child.
The child materializes Qwen, runs the real FastFix language load once, and
offloads once only after LANGLOAD-04.  No visual, prompt, or generation path is
entered.
"""

from __future__ import annotations

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
    _runtime_and_models,
)
from scripts.probe_qwen_i2g1_memory_policy import (  # noqa: E402
    EXPECTED_H3_COMMIT,
    EXPECTED_H3_PATCH_SHA256,
    EXPECTED_VHS_COMMIT,
    EXPECTED_PARENT_MIN_FREE_COMMIT,
    _language_summary,
    _looks_like_cuda_oom,
    _module_inventory,
    _runtime_lock_state,
    _state_summary,
)

EXPECTED_H3_FINGERPRINT = "7bddba2e20e87c4eda7fd4f13109eca57e66c5b46548ca406fa054e008da6c69"
EXPECTED_HEADROOM_PATCH_SHA256 = "c6342b0417f9adb8dacfb72cdacab9a6c58500a0fb7ee27192eca098148e5aeb"
EXPECTED_BOUNDARY_PATCH_SHA256 = "67ca71fd28ddedf7cad6f3bb837b6b825ee08145efe518671574e19522dad2ac"
EXPECTED_STATIC_BYTES = 1_556_874_496
EXPECTED_HEADROOM_BYTES = 3_221_225_472
EXPECTED_MARGIN_BYTES = 1_556_874_496
EXPECTED_MEMORY_REQUIRED = 6_334_974_464
EXPECTED_PARENT_GATE = 64_444_190_720
POST_MATERIALIZATION_GATE = 30 * 2**30

LANG_MARKERS = (
    "LANGLOAD-01 BEFORE_LOAD_MODELS_GPU",
    "LANGLOAD-02 AFTER_LOAD_MODELS_GPU",
    "LANGLOAD-03 BEFORE_MOVE_STATIC",
    "LANGLOAD-04 AFTER_MOVE_STATIC",
)


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


def _host_memory() -> dict[str, int | float]:
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
    commit_charge = int(info.CommitTotal * info.PageSize)
    commit_limit = int(info.CommitLimit * info.PageSize)
    free_commit = commit_limit - commit_charge
    return {
        "physical_ram_bytes": int(status.ullTotalPhys),
        "physical_ram_gib": round(status.ullTotalPhys / 2**30, 3),
        "available_ram_bytes": int(status.ullAvailPhys),
        "available_ram_gib": round(status.ullAvailPhys / 2**30, 3),
        "commit_charge_bytes": commit_charge,
        "commit_charge_gib": round(commit_charge / 2**30, 3),
        "commit_limit_bytes": commit_limit,
        "commit_limit_gib": round(commit_limit / 2**30, 3),
        "free_commit_bytes": int(free_commit),
        "free_commit_gib": round(free_commit / 2**30, 3),
        "commit_percent": round(commit_charge / commit_limit * 100, 3),
    }


def _pagefile_snapshot() -> object:
    command = (
        "Get-CimInstance Win32_PageFileUsage | "
        "Select-Object Name,AllocatedBaseSize,CurrentUsage,PeakUsage | "
        "ConvertTo-Json -Compress"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        value = result.stdout.strip()
        return json.loads(value) if value else {"query_error": result.stderr.strip()}
    except BaseException as exc:
        return {"query_error": f"{type(exc).__name__}: {exc}"}


def _gpu_snapshot() -> str:
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,memory.free",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return result.stdout.strip() or result.stderr.strip()
    except BaseException as exc:
        return f"UNAVAILABLE: {type(exc).__name__}: {exc}"


def _support_lock(runtime: Path) -> dict:
    lock = json.loads(
        (runtime / "ComfyUI/custom_nodes/support_layer.lock.json").read_text(
            encoding="utf-8"
        )
    )
    h3 = lock.get("h3", {})
    strategy = h3.get("strategy_a", {})
    if h3.get("commit") != EXPECTED_H3_COMMIT:
        raise RuntimeError("PRECHECK_BLOCKED: H3 commit mismatch")
    if h3.get("source_tree_fingerprint") != EXPECTED_H3_FINGERPRINT:
        raise RuntimeError("PRECHECK_BLOCKED: H3 fingerprint mismatch")
    if h3.get("project_patch_sha256") != EXPECTED_H3_PATCH_SHA256:
        raise RuntimeError("PRECHECK_BLOCKED: project patch mismatch")
    if strategy.get("static_transfer_headroom_patch_sha256") != EXPECTED_HEADROOM_PATCH_SHA256:
        raise RuntimeError("PRECHECK_BLOCKED: FastFix patch mismatch")
    if strategy.get("language_boundary_instrumentation_patch_sha256") != EXPECTED_BOUNDARY_PATCH_SHA256:
        raise RuntimeError("PRECHECK_BLOCKED: boundary patch mismatch")
    if strategy.get("static_transfer_headroom", {}).get("method") != "ModelPatcher.partially_unload":
        raise RuntimeError("PRECHECK_BLOCKED: FastFix method mismatch")
    if strategy.get("static_transfer_headroom", {}).get("before_static_transfer") is not True:
        raise RuntimeError("PRECHECK_BLOCKED: FastFix ordering mismatch")
    if strategy.get("target_dtype") != "bfloat16":
        raise RuntimeError("PRECHECK_BLOCKED: Strategy-A dtype mismatch")
    if strategy.get("visual_dtype") != "preserved_fp32":
        raise RuntimeError("PRECHECK_BLOCKED: visual dtype mismatch")
    if strategy.get("quantized_linear_contract") != "preserved_350":
        raise RuntimeError("PRECHECK_BLOCKED: quantized Linear mismatch")
    if h3.get("memory_policy", {}).get("name") != "static_transfer_safety_margin":
        raise RuntimeError("PRECHECK_BLOCKED: I2 policy missing")
    if lock.get("video_helper_suite", {}).get("commit") != EXPECTED_VHS_COMMIT:
        raise RuntimeError("PRECHECK_BLOCKED: VHS commit mismatch")
    if lock.get("pread", {}).get("environment") != "H3_WINDOWS_SAFE_LOAD=pread":
        raise RuntimeError("PRECHECK_BLOCKED: PREAD mismatch")
    return lock


def _disk_snapshot(models: Path) -> dict:
    return {
        "c_free_gib": round(shutil.disk_usage("C:/").free / 2**30, 3),
        "d_free_gib": round(shutil.disk_usage("D:/").free / 2**30, 3),
        "models_anchor": str(models.anchor),
    }


def _boundary_events(events: list[dict]) -> list[dict]:
    result = []
    for item in events:
        message = item.get("message") if isinstance(item, dict) else None
        if not isinstance(message, str) or not message.startswith("H3_LANGUAGE_LOAD_BOUNDARY "):
            continue
        try:
            payload = json.loads(message.split(" ", 1)[1])
        except (TypeError, json.JSONDecodeError):
            continue
        if payload.get("marker") in LANG_MARKERS:
            result.append(payload)
    return result


def _exception_events(events: list[dict]) -> list[dict]:
    result = []
    for item in events:
        message = item.get("message") if isinstance(item, dict) else None
        if not isinstance(message, str) or not message.startswith("H3_LANGUAGE_LOAD_EXCEPTION "):
            continue
        try:
            result.append(json.loads(message.split(" ", 1)[1]))
        except (TypeError, json.JSONDecodeError):
            pass
    return result


def _contract_ok(state: dict) -> bool:
    return (
        state["language"]["direct_static_tensor_count"] == 203
        and state["language"]["direct_static_dtype_distribution"] == {"torch.bfloat16": 203}
        and state["language"]["direct_static_bytes"] == EXPECTED_STATIC_BYTES
        and state["language"]["quantized_linear_count"] == 350
        and state["visual"]["tensor_count"] == 352
        and state["visual"]["device_distribution"] == {"cpu": 352}
        and state["visual"]["dtype_distribution"] == {"torch.float32": 352}
    )


def _child(log_path: Path, stdout_path: Path, stderr_path: Path) -> int:
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    events: list[dict] = []
    log_handle = log_path.open("a", encoding="utf-8", buffering=1)
    stdout_handle = stdout_path.open("a", encoding="utf-8", buffering=1)
    stderr_handle = stderr_path.open("a", encoding="utf-8", buffering=1)

    class Tee:
        def __init__(self, original, mirror):
            self.original = original
            self.mirror = mirror

        def write(self, value):
            self.original.write(value)
            self.mirror.write(value)
            self.mirror.flush()
            return len(value)

        def flush(self):
            self.original.flush()
            self.mirror.flush()

    class TraceHandler(logging.Handler):
        def emit(self, record):
            message = record.getMessage()
            events.append({"stage": "H3_LOG", "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "message": message})
            _marker(log_handle, "H3_LOG", message=message)
            if message.startswith("H3_LANGUAGE_LOAD_BOUNDARY "):
                try:
                    payload = json.loads(message.split(" ", 1)[1])
                    if payload.get("marker") == "LANGLOAD-02 AFTER_LOAD_MODELS_GPU":
                        _marker(log_handle, "FASTFIX-BEFORE_PARTIAL_UNLOAD", state=payload)
                    elif payload.get("marker") == "LANGLOAD-03 BEFORE_MOVE_STATIC":
                        _marker(log_handle, "FASTFIX-AFTER_PARTIAL_UNLOAD", state=payload)
                except (TypeError, json.JSONDecodeError):
                    pass

    trace = TraceHandler()
    h3_logger = logging.getLogger("minimax_h3_nodes")
    old_level = h3_logger.level
    h3_logger.addHandler(trace)
    h3_logger.setLevel(logging.INFO)
    sys.stdout = Tee(original_stdout, stdout_handle)
    sys.stderr = Tee(original_stderr, stderr_handle)
    try:
        runtime, models = _runtime_and_models()
        lock = _support_lock(runtime)
        memory = _host_memory()
        runtime_lock = _runtime_lock_state()
        _marker(
            log_handle,
            "FASTFIX-CHILD_PRECHECK",
            runtime=str(runtime),
            models_root=str(models),
            h3_fingerprint=lock["h3"]["source_tree_fingerprint"],
            windows_memory=memory,
            pagefile=_pagefile_snapshot(),
            job_running=bool(runtime_lock.get("job_running", False)),
            gpu=_gpu_snapshot(),
            **_disk_snapshot(models),
        )
        if bool(runtime_lock.get("job_running", False)):
            _marker(log_handle, "FASTFIX-PRECHECK_BLOCKED", reason="GPU_JOB_ALREADY_RUNNING")
            return 20

        comfy_root = runtime / "ComfyUI"
        h3_root = comfy_root / "custom_nodes/ComfyUI_RH_MinMaxH3"
        os.chdir(comfy_root)
        sys.path.insert(0, str(comfy_root))
        sys.path.insert(0, str(h3_root))
        import torch
        from minimax_h3_nodes.api import _shared
        from minimax_h3_nodes.runtime.qwen_encoder.loading import load_h3_text_encoder
        import comfy.model_management as mm

        if not torch.cuda.is_available():
            _marker(log_handle, "FASTFIX-PRECHECK_BLOCKED", reason="CUDA_UNAVAILABLE")
            return 20

        selector = _shared._default_te_model_name()
        partition_root, _info, _sigma = _shared._resolve_t2va_release(
            "MiniMax-H3",
            required_component=_shared._selector_to_component_dirname(
                selector, "text_encoder", "fl2va", model_root="MiniMax-H3"
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
            _contract_ok(fresh)
            and fresh["language"]["fp32_equivalent_static_bytes"] == 3_113_748_992
            and fresh["comfy_model_management"]["current_loaded_models_count"] == 0
            and not fresh["patcher"]["present"]
            and fresh["compute_device"] is None
            and not fresh["inference_active"]
        )
        _marker(
            log_handle,
            "FASTFIX-MATERIALIZED",
            selected_component=str(selected_component),
            selected_weights=str(selected_weights) if selected_weights else None,
            contract_pass=fresh_ok,
            memory=fresh["windows_memory"],
            state=fresh,
        )
        if not fresh_ok:
            return 30
        if fresh["windows_memory"]["free_commit_bytes"] < POST_MATERIALIZATION_GATE:
            _marker(
                log_handle,
                "FASTFIX-POST_MATERIALIZATION_RESOURCE_BLOCKED",
                required_free_commit_bytes=POST_MATERIALIZATION_GATE,
                state=fresh,
            )
            return 20

        _marker(
            log_handle,
            "FASTFIX-BEFORE_LOAD_FOR_INFERENCE",
            expected_memory_required_bytes=EXPECTED_MEMORY_REQUIRED,
            expected_static_bytes=EXPECTED_STATIC_BYTES,
            expected_margin_bytes=EXPECTED_MARGIN_BYTES,
            expected_headroom_bytes=EXPECTED_HEADROOM_BYTES,
            state=_state_summary(handle, mm, torch),
        )
        try:
            handle.load_for_inference()
        except BaseException as exc:
            traceback.print_exc()
            boundaries = _boundary_events(events)
            exceptions = _exception_events(events)
            _marker(
                log_handle,
                "FASTFIX-LANGUAGE_LOAD_FAILURE",
                classification="FASTFIX_LANGUAGE_LIFECYCLE_FAILED",
                exception=type(exc).__name__,
                message=str(exc),
                cuda_oom=_looks_like_cuda_oom(exc),
                boundaries=boundaries,
                exceptions=exceptions,
                state=_state_summary(handle, mm, torch),
            )
            return 41 if _looks_like_cuda_oom(exc) else 40

        boundaries = _boundary_events(events)
        if "LANGLOAD-04 AFTER_MOVE_STATIC" not in [x.get("marker") for x in boundaries]:
            _marker(log_handle, "FASTFIX-LANGUAGE_LOAD_FAILURE", classification="FASTFIX_LANGUAGE_LIFECYCLE_FAILED", boundaries=boundaries)
            return 40
        loaded = _state_summary(handle, mm, torch)
        loaded_ok = (
            _contract_ok(loaded)
            and loaded["language"]["direct_static_device_distribution"] == {"cuda:0": 203}
            and loaded["patcher"]["present"]
            and loaded["compute_device"] is not None
            and loaded["inference_active"]
        )
        _marker(log_handle, "FASTFIX-LANGUAGE_LOAD_SUCCEEDED", state=loaded, boundaries=boundaries)
        if not loaded_ok:
            _marker(log_handle, "FASTFIX-LANGUAGE_LOAD_FAILURE", classification="FASTFIX_LANGUAGE_LIFECYCLE_FAILED", reason="SUCCESS_STATE_CONTRACT_FAILED", state=loaded)
            return 40

        _marker(log_handle, "FASTFIX-BEFORE_OFFLOAD", state=loaded)
        try:
            handle.offload_after_inference()
        except BaseException as exc:
            traceback.print_exc()
            _marker(log_handle, "FASTFIX-OFFLOAD_FAILURE", exception=type(exc).__name__, message=str(exc), state=_state_summary(handle, mm, torch))
            return 43
        offloaded = _state_summary(handle, mm, torch)
        offloaded_ok = (
            offloaded["language"]["direct_static_device_distribution"] == {"cpu": 203}
            and offloaded["compute_device"] is None
            and not offloaded["inference_active"]
            and offloaded["patcher"]["loaded_size_bytes"] in (0, None)
            and offloaded["visual"]["device_distribution"] == {"cpu": 352}
            and offloaded["visual"]["dtype_distribution"] == {"torch.float32": 352}
        )
        _marker(log_handle, "FASTFIX-OFFLOAD_SUCCEEDED", state=offloaded)
        if not offloaded_ok:
            _marker(log_handle, "FASTFIX-LANGUAGE_LOAD_FAILURE", classification="FASTFIX_LANGUAGE_LIFECYCLE_FAILED", reason="OFFLOAD_STATE_CONTRACT_FAILED", state=offloaded)
            return 43
        _marker(log_handle, "FASTFIX-PROCESS_SURVIVED", state=offloaded)
        return 0
    except BaseException as exc:
        traceback.print_exc()
        _marker(log_handle, "FASTFIX-OTHER_FAILURE", exception=type(exc).__name__, message=str(exc))
        return 40
    finally:
        h3_logger.removeHandler(trace)
        h3_logger.setLevel(old_level)
        sys.stdout = original_stdout
        sys.stderr = original_stderr
        for stream in (log_handle, stdout_handle, stderr_handle):
            stream.flush()
            stream.close()


def _parent() -> int:
    runtime, models = _runtime_and_models()
    lock = _support_lock(runtime)
    runtime_lock = _runtime_lock_state()
    memory = _host_memory()
    preflight = {
        "runtime": str(runtime),
        "models_root": str(models),
        "h3_commit": lock["h3"]["commit"],
        "h3_fingerprint": lock["h3"]["source_tree_fingerprint"],
        "h3_patch_sha256": lock["h3"]["project_patch_sha256"],
        "fastfix_patch_sha256": lock["h3"]["strategy_a"]["static_transfer_headroom_patch_sha256"],
        "boundary_patch_sha256": lock["h3"]["strategy_a"]["language_boundary_instrumentation_patch_sha256"],
        "vhs_commit": lock["video_helper_suite"]["commit"],
        "windows_memory": memory,
        "pagefile": _pagefile_snapshot(),
        "gpu": _gpu_snapshot(),
        "job_running": bool(runtime_lock.get("job_running", False)),
        **_disk_snapshot(models),
        "start_timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    output_dir = ROOT / "userdata/cache/temp/r2b_fastfix_g1"
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    log_path = output_dir / f"fastfix_g1_language_child_{stamp}.log"
    stdout_path = output_dir / f"fastfix_g1_language_stdout_{stamp}.log"
    stderr_path = output_dir / f"fastfix_g1_language_stderr_{stamp}.log"
    result_path = output_dir / f"fastfix_g1_language_result_{stamp}.json"
    if preflight["job_running"] or memory["free_commit_bytes"] < EXPECTED_PARENT_GATE:
        classification = "PARENT_RESOURCE_PRECHECK_BLOCKED"
        summary = {
            "classification": classification,
            "reason": "GPU_JOB_ALREADY_RUNNING" if preflight["job_running"] else "FREE_COMMIT_BELOW_REQUIRED_PARENT_GATE",
            "required_parent_free_commit_bytes": EXPECTED_PARENT_GATE,
            **preflight,
            "child_started": False,
            "visual_executed": False,
            "language_forward_entered": False,
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
        [str(ROOT), str(comfy_root), str(comfy_root / "custom_nodes/ComfyUI_RH_MinMaxH3"), env.get("PYTHONPATH", "")]
    ).strip(os.pathsep)
    managed_python = runtime / "python_embeded/python.exe"
    if not managed_python.is_file():
        raise RuntimeError(f"managed embedded Python missing: {managed_python}")
    log_path.write_text(json.dumps({"parent": "FASTFIX-G1", **preflight}, ensure_ascii=False) + "\n", encoding="utf-8")
    stdout_handle = stdout_path.open("w", encoding="utf-8", buffering=1)
    stderr_handle = stderr_path.open("w", encoding="utf-8", buffering=1)
    started = time.time()
    child = subprocess.Popen(
        [str(managed_python), str(Path(__file__).resolve()), "--child", "--log", str(log_path), "--stdout", str(stdout_path), "--stderr", str(stderr_path)],
        cwd=str(comfy_root),
        env=env,
        stdout=stdout_handle,
        stderr=stderr_handle,
    )
    with log_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"parent": "FASTFIX-G1", "pid": child.pid}, ensure_ascii=False) + "\n")
    code = child.wait()
    ended = time.time()
    stdout_handle.close()
    stderr_handle.close()
    raw = log_path.read_text(encoding="utf-8", errors="replace")
    stages = re.findall(r'"stage":\s*"([^"]+)"', raw)
    boundary_markers = []
    exception_events = []
    for line in raw.splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if item.get("stage") == "H3_LOG":
            message = item.get("message", "")
            if message.startswith("H3_LANGUAGE_LOAD_BOUNDARY "):
                try:
                    payload = json.loads(message.split(" ", 1)[1])
                    if payload.get("marker") in LANG_MARKERS:
                        boundary_markers.append(payload)
                except (TypeError, json.JSONDecodeError):
                    pass
            elif message.startswith("H3_LANGUAGE_LOAD_EXCEPTION "):
                try:
                    exception_events.append(json.loads(message.split(" ", 1)[1]))
                except (TypeError, json.JSONDecodeError):
                    pass
    stage_set = set(stages)
    if code == 0 and "FASTFIX-PROCESS_SURVIVED" in stage_set and "LANGLOAD-04 AFTER_MOVE_STATIC" in [x.get("marker") for x in boundary_markers]:
        classification = "LANGUAGE_LIFECYCLE_PASS"
    elif "FASTFIX-POST_MATERIALIZATION_RESOURCE_BLOCKED" in stage_set:
        classification = "POST_MATERIALIZATION_RESOURCE_BLOCKED"
    elif "FASTFIX-LANGUAGE_LOAD_FAILURE" in stage_set and ("LANGLOAD-03 BEFORE_MOVE_STATIC" in [x.get("marker") for x in boundary_markers] or "FASTFIX-AFTER_PARTIAL_UNLOAD" in stage_set):
        classification = "FASTFIX_LANGUAGE_LIFECYCLE_FAILED"
    elif code in ACCESS_VIOLATION_CODES:
        classification = "FASTFIX_LANGUAGE_LIFECYCLE_FAILED"
    elif code == 20:
        classification = "PARENT_RESOURCE_PRECHECK_BLOCKED"
    else:
        classification = "OTHER_TARGETED_FAILURE"
    summary = {
        "classification": classification,
        "pid": child.pid,
        "start_timestamp": preflight["start_timestamp"],
        "end_timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "elapsed_seconds": round(ended - started, 3),
        "exit_code": code,
        "last_flushed_marker": stages[-1] if stages else "NONE",
        "stages": stages,
        "boundary_markers": boundary_markers,
        "exception_events": exception_events,
        "log_path": str(log_path),
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
        "result_path": str(result_path),
        "preflight": preflight,
        "child_started": True,
        "child_ended": True,
        "job_running_after": bool(_runtime_lock_state().get("job_running", False)),
        "prompt_submitted": False,
        "visual_executed": False,
        "language_forward_entered": False,
        "encode_ids_called": False,
        "studio_job_created": False,
        "no_second_child": True,
    }
    result_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--log", type=Path)
    parser.add_argument("--stdout", type=Path)
    parser.add_argument("--stderr", type=Path)
    args = parser.parse_args()
    if args.child:
        if not args.log or not args.stdout or not args.stderr:
            raise SystemExit("--child requires --log, --stdout, and --stderr")
        return _child(args.log, args.stdout, args.stderr)
    return _parent()


if __name__ == "__main__":
    raise SystemExit(main())
