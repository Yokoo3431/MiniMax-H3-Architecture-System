"""One supervised D1 probe for the instrumented H3 language-load boundary.

The parent starts exactly one managed child.  The child materializes only the
pinned H3 Qwen component, calls the real language lifecycle once, and calls
the real offload once only when language loading reaches LANGLOAD-04.  No
visual path, prompt, workflow, or generation is entered.
"""

from __future__ import annotations

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

from scripts.probe_qwen_i2g1_memory_policy import (  # noqa: E402
    EXPECTED_H3_COMMIT,
    EXPECTED_H3_FINGERPRINT,
    EXPECTED_H3_PATCH_SHA256,
    EXPECTED_BOUNDARY_PATCH_SHA256,
    EXPECTED_VHS_COMMIT,
    EXPECTED_PARENT_MIN_FREE_COMMIT,
    _language_summary,
    _looks_like_cuda_oom,
    _runtime_and_models,
    _runtime_lock_state,
    _state_summary,
    _windows_memory,
)
from scripts.probe_qwen_visual_device_cycle import _marker  # noqa: E402


LANG_MARKERS = (
    "LANGLOAD-01 BEFORE_LOAD_MODELS_GPU",
    "LANGLOAD-02 AFTER_LOAD_MODELS_GPU",
    "LANGLOAD-03 BEFORE_MOVE_STATIC",
    "LANGLOAD-04 AFTER_MOVE_STATIC",
)


def _support_lock(runtime: Path) -> dict:
    lock = json.loads(
        (runtime / "ComfyUI/custom_nodes/support_layer.lock.json").read_text(encoding="utf-8")
    )
    h3 = lock.get("h3", {})
    strategy = h3.get("strategy_a", {})
    if h3.get("commit") != EXPECTED_H3_COMMIT:
        raise RuntimeError("RUNTIME_PROVENANCE_BLOCKED: H3 commit mismatch")
    if h3.get("source_tree_fingerprint") != EXPECTED_H3_FINGERPRINT:
        raise RuntimeError("RUNTIME_PROVENANCE_BLOCKED: H3 fingerprint mismatch")
    if h3.get("project_patch_sha256") != EXPECTED_H3_PATCH_SHA256:
        raise RuntimeError("RUNTIME_PROVENANCE_BLOCKED: project patch mismatch")
    if strategy.get("language_boundary_instrumentation_patch_sha256") != EXPECTED_BOUNDARY_PATCH_SHA256:
        raise RuntimeError("RUNTIME_PROVENANCE_BLOCKED: boundary patch mismatch")
    if strategy.get("target_dtype") != "bfloat16":
        raise RuntimeError("RUNTIME_PROVENANCE_BLOCKED: Strategy-A dtype mismatch")
    if strategy.get("visual_dtype") != "preserved_fp32":
        raise RuntimeError("RUNTIME_PROVENANCE_BLOCKED: visual dtype mismatch")
    if strategy.get("quantized_linear_contract") != "preserved_350":
        raise RuntimeError("RUNTIME_PROVENANCE_BLOCKED: quantized Linear mismatch")
    if h3.get("memory_policy", {}).get("name") != "static_transfer_safety_margin":
        raise RuntimeError("RUNTIME_PROVENANCE_BLOCKED: I2 policy missing")
    if lock.get("video_helper_suite", {}).get("commit") != EXPECTED_VHS_COMMIT:
        raise RuntimeError("RUNTIME_PROVENANCE_BLOCKED: VHS commit mismatch")
    if lock.get("pread", {}).get("environment") != "H3_WINDOWS_SAFE_LOAD=pread":
        raise RuntimeError("RUNTIME_PROVENANCE_BLOCKED: PREAD mismatch")
    return lock


def _disk_snapshot(models: Path) -> dict:
    return {
        "c_free_gib": round(shutil.disk_usage("C:/").free / 2**30, 3),
        "d_free_gib": round(shutil.disk_usage("D:/").free / 2**30, 3),
        "models_anchor": str(models.anchor),
    }


def _gpu_snapshot() -> str:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.free", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return result.stdout.strip() or result.stderr.strip()
    except BaseException as exc:
        return f"UNAVAILABLE: {type(exc).__name__}: {exc}"


def _logger_message_events(log: list[dict]) -> tuple[list[dict], list[dict]]:
    boundaries: list[dict] = []
    exceptions: list[dict] = []
    for record in log:
        message = record.get("message") if isinstance(record, dict) else None
        if not isinstance(message, str):
            continue
        if message.startswith("H3_LANGUAGE_LOAD_BOUNDARY "):
            try:
                payload = json.loads(message.split(" ", 1)[1])
                if payload.get("marker") in LANG_MARKERS:
                    boundaries.append(payload)
            except (TypeError, json.JSONDecodeError):
                pass
        elif message.startswith("H3_LANGUAGE_LOAD_EXCEPTION "):
            try:
                exceptions.append(json.loads(message.split(" ", 1)[1]))
            except (TypeError, json.JSONDecodeError):
                pass
    return boundaries, exceptions


def _classify_boundary(boundaries: list[dict], exceptions: list[dict], exit_code: int) -> str:
    names = [item.get("marker") for item in boundaries]
    joined_trace = "\n".join(
        str(item.get("traceback", "")) for item in exceptions
    ).lower()
    if "LANGLOAD-04 AFTER_MOVE_STATIC" in names:
        return "LANGUAGE_GPU_LOAD_BOUNDARY_PASS"
    if (
        "LANGLOAD-01 BEFORE_LOAD_MODELS_GPU" in names
        and "LANGLOAD-02 AFTER_LOAD_MODELS_GPU" not in names
        and "load_models_gpu" in joined_trace
    ):
        return "OOM_BOUNDARY_LOAD_MODELS_GPU_PROVEN"
    if (
        "LANGLOAD-02 AFTER_LOAD_MODELS_GPU" in names
        and "LANGLOAD-03 BEFORE_MOVE_STATIC" in names
        and "LANGLOAD-04 AFTER_MOVE_STATIC" not in names
        and ("_move_static_tensors" in joined_trace or "tensor.to" in joined_trace)
    ):
        return "OOM_BOUNDARY_STATIC_TRANSFER_PROVEN"
    if exit_code in (0,):
        return "LANGUAGE_BOUNDARY_INSTRUMENTATION_INCOMPLETE"
    return "OOM_SUB_BOUNDARY_UNRESOLVED"


def _child(log_path: Path, stdout_path: Path, stderr_path: Path) -> int:
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    events: list[dict] = []

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

    log_handle = log_path.open("a", encoding="utf-8", buffering=1)
    out_handle = stdout_path.open("a", encoding="utf-8", buffering=1)
    err_handle = stderr_path.open("a", encoding="utf-8", buffering=1)
    sys.stdout = Tee(original_stdout, log_handle)
    sys.stderr = Tee(original_stderr, err_handle)

    class BoundaryLogHandler(logging.Handler):
        def emit(self, record):
            message = record.getMessage()
            item = {"stage": "H3_LOG", "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "message": message}
            events.append(item)
            _marker(log_handle, "H3_LOG", message=message)

    handler = BoundaryLogHandler()
    h3_logger = logging.getLogger("minimax_h3_nodes")
    old_level = h3_logger.level
    h3_logger.addHandler(handler)
    h3_logger.setLevel(logging.INFO)
    try:
        runtime, models = _runtime_and_models()
        lock = _support_lock(runtime)
        memory = _windows_memory()
        runtime_lock = _runtime_lock_state()
        _marker(
            log_handle,
            "D1-CHILD_PRECHECK",
            runtime=str(runtime),
            models_root=str(models),
            h3_fingerprint=lock["h3"]["source_tree_fingerprint"],
            **memory,
            job_running=bool(runtime_lock.get("job_running", False)),
            **_disk_snapshot(models),
        )
        if bool(runtime_lock.get("job_running", False)):
            _marker(log_handle, "D1-PRECHECK_BLOCKED", reason="GPU_JOB_ALREADY_RUNNING")
            return 20
        if memory["free_commit_bytes"] < EXPECTED_PARENT_MIN_FREE_COMMIT:
            _marker(
                log_handle,
                "D1-PARENT_RESOURCE_PRECHECK_BLOCKED",
                required_parent_free_commit_bytes=EXPECTED_PARENT_MIN_FREE_COMMIT,
                **memory,
            )
            return 20

        runtime_comfy = runtime / "ComfyUI"
        h3_root = runtime_comfy / "custom_nodes/ComfyUI_RH_MinMaxH3"
        os.chdir(runtime_comfy)
        sys.path.insert(0, str(runtime_comfy))
        sys.path.insert(0, str(h3_root))
        import torch
        from minimax_h3_nodes.api import _shared
        from minimax_h3_nodes.runtime.qwen_encoder.loading import load_h3_text_encoder
        import comfy.model_management as mm

        if not torch.cuda.is_available():
            _marker(log_handle, "D1-PRECHECK_BLOCKED", reason="CUDA_UNAVAILABLE")
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
        contract = (
            fresh["language"]["direct_static_tensor_count"] == 203
            and fresh["language"]["direct_static_dtype_distribution"] == {"torch.bfloat16": 203}
            and fresh["language"]["direct_static_bytes"] == 1_556_874_496
            and fresh["language"]["quantized_linear_count"] == 350
            and fresh["visual"]["tensor_count"] == 352
            and fresh["visual"]["device_distribution"] == {"cpu": 352}
            and fresh["visual"]["dtype_distribution"] == {"torch.float32": 352}
            and not fresh["patcher"]["present"]
            and fresh["compute_device"] is None
            and not fresh["inference_active"]
        )
        _marker(
            log_handle,
            "LANGBOUNDARY-MATERIALIZED",
            selected_component=str(selected_component),
            selected_weights=str(selected_weights) if selected_weights else None,
            state=fresh,
            contract_pass=contract,
        )
        if not contract:
            return 30
        post_materialization = fresh["windows_memory"]
        if post_materialization["free_commit_bytes"] < 30 * 2**30:
            _marker(
                log_handle,
                "D1-POST_MATERIALIZATION_RESOURCE_BLOCKED",
                required_free_commit_bytes=30 * 2**30,
                **post_materialization,
            )
            return 20

        _marker(log_handle, "D1-BEFORE_LOAD_FOR_INFERENCE", state=_state_summary(handle, mm, torch))
        try:
            handle.load_for_inference()
        except BaseException as exc:
            traceback.print_exc()
            boundaries, exceptions = _logger_message_events(events)
            _marker(
                log_handle,
                "D1-LANGUAGE_LOAD_FAILURE",
                exception=type(exc).__name__,
                message=str(exc),
                cuda_oom=_looks_like_cuda_oom(exc),
                boundaries=boundaries,
                exceptions=exceptions,
                state=_state_summary(handle, mm, torch),
            )
            return 41 if _looks_like_cuda_oom(exc) else 40

        boundaries, exceptions = _logger_message_events(events)
        _marker(log_handle, "D1-LANGUAGE_LOAD_SUCCEEDED", state=_state_summary(handle, mm, torch), boundaries=boundaries)
        _marker(log_handle, "D1-BEFORE_OFFLOAD", state=_state_summary(handle, mm, torch))
        try:
            handle.offload_after_inference()
        except BaseException as exc:
            traceback.print_exc()
            _marker(log_handle, "D1-OFFLOAD_FAILURE", exception=type(exc).__name__, message=str(exc))
            return 43
        _marker(log_handle, "D1-OFFLOAD_SUCCEEDED", state=_state_summary(handle, mm, torch))
        _marker(log_handle, "D1-PROCESS_SURVIVED")
        return 0
    except BaseException as exc:
        traceback.print_exc()
        _marker(log_handle, "D1-OTHER_FAILURE", exception=type(exc).__name__, message=str(exc))
        return 40
    finally:
        h3_logger.removeHandler(handler)
        h3_logger.setLevel(old_level)
        sys.stdout = original_stdout
        sys.stderr = original_stderr
        for stream in (log_handle, out_handle, err_handle):
            stream.flush()
            stream.close()


def _parent() -> int:
    runtime, models = _runtime_and_models()
    lock = _support_lock(runtime)
    runtime_lock = _runtime_lock_state()
    memory = _windows_memory()
    preflight = {
        "runtime": str(runtime),
        "models_root": str(models),
        "h3_commit": lock["h3"]["commit"],
        "h3_fingerprint": lock["h3"]["source_tree_fingerprint"],
        "h3_patch_sha256": lock["h3"]["project_patch_sha256"],
        "boundary_patch_sha256": lock["h3"]["strategy_a"]["language_boundary_instrumentation_patch_sha256"],
        "vhs_commit": lock["video_helper_suite"]["commit"],
        "windows_memory": memory,
        "job_running": bool(runtime_lock.get("job_running", False)),
        **_disk_snapshot(models),
        "gpu": _gpu_snapshot(),
        "start_timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    output_dir = ROOT / "userdata/cache/temp/d1_language_boundary"
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    log_path = output_dir / f"d1_language_child_{stamp}.log"
    stdout_path = output_dir / f"d1_language_stdout_{stamp}.log"
    stderr_path = output_dir / f"d1_language_stderr_{stamp}.log"
    result_path = output_dir / f"d1_language_result_{stamp}.json"
    if preflight["job_running"]:
        summary = {"classification": "PRECHECK_BLOCKED", **preflight, "reason": "GPU_JOB_ALREADY_RUNNING"}
        result_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 20
    if memory["free_commit_bytes"] < EXPECTED_PARENT_MIN_FREE_COMMIT:
        summary = {
            "classification": "PARENT_RESOURCE_PRECHECK_BLOCKED",
            **preflight,
            "required_parent_free_commit_bytes": EXPECTED_PARENT_MIN_FREE_COMMIT,
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
    runtime_comfy = runtime / "ComfyUI"
    env["PYTHONPATH"] = os.pathsep.join(
        [str(ROOT), str(runtime_comfy), str(runtime_comfy / "custom_nodes/ComfyUI_RH_MinMaxH3"), env.get("PYTHONPATH", "")]
    ).strip(os.pathsep)
    managed_python = runtime / "python_embeded/python.exe"
    if not managed_python.is_file():
        raise RuntimeError(f"managed embedded Python missing: {managed_python}")
    log_path.write_text(json.dumps({"parent": "D1", **preflight}, ensure_ascii=False) + "\n", encoding="utf-8")
    stdout_handle = stdout_path.open("w", encoding="utf-8", buffering=1)
    stderr_handle = stderr_path.open("w", encoding="utf-8", buffering=1)
    started = time.time()
    child = subprocess.Popen(
        [str(managed_python), str(Path(__file__).resolve()), "--child", "--log", str(log_path), "--stdout", str(stdout_path), "--stderr", str(stderr_path)],
        cwd=str(runtime_comfy),
        env=env,
        stdout=stdout_handle,
        stderr=stderr_handle,
    )
    with log_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"parent": "D1", "pid": child.pid}, ensure_ascii=False) + "\n")
    code = child.wait()
    ended = time.time()
    stdout_handle.close()
    stderr_handle.close()
    raw = log_path.read_text(encoding="utf-8", errors="replace")
    stages = re.findall(r'"stage":\s*"([^"]+)"', raw)
    logger_records: list[dict] = []
    for line in raw.splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if item.get("stage") == "H3_LOG":
            logger_records.append(item)
    boundaries, exceptions = _logger_message_events(logger_records)
    classification = _classify_boundary(boundaries, exceptions, code)
    summary = {
        "classification": classification,
        "pid": child.pid,
        "start_timestamp": preflight["start_timestamp"],
        "end_timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "elapsed_seconds": round(ended - started, 3),
        "exit_code": code,
        "last_stage": stages[-1] if stages else "NONE",
        "stages": stages,
        "boundary_markers": boundaries,
        "exception_events": exceptions,
        "log_path": str(log_path),
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
        "result_path": str(result_path),
        "preflight": preflight,
        "prompt_submitted": False,
        "visual_executed": False,
        "language_forward_entered": False,
        "child_ended": True,
        "job_running_after": bool(_runtime_lock_state().get("job_running", False)),
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
