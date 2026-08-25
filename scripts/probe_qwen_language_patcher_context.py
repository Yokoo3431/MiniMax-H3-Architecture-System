"""One supervised C2-G1 language-patcher residual-state probe.

This is a single targeted GPU diagnostic.  It creates the real pinned INT8
Qwen language ModelPatcher through ``load_for_inference()``, offloads it once
through the real production cleanup path, then invokes only the already
validated staged visual helper.  It never submits a prompt, enters the
language forward stage, or loads DiT/VAE/VHS.
"""

from __future__ import annotations

from collections import Counter
import argparse
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
    EXPECTED_H3_COMMIT,
    EXPECTED_H3_FINGERPRINT,
    EXPECTED_H3_PATCH_SHA256,
    EXPECTED_VHS_COMMIT,
    _feature_summary,
    _marker,
    _module_inventory,
    _production_fl2va_preprocess,
    _runtime_and_models,
    _support_lock,
    _windows_memory,
)


def _runtime_lock_state() -> dict:
    path = ROOT / "launcher" / "runtime.lock"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _loaded_model_summary(mm, patcher) -> dict:
    loaded = list(getattr(mm, "current_loaded_models", ()) or ())
    matches = 0
    for item in loaded:
        candidates = [getattr(item, "model", None)]
        model = candidates[0]
        candidates.append(getattr(model, "model", None))
        if any(candidate is patcher for candidate in candidates):
            matches += 1
    return {
        "current_loaded_models_count": len(loaded),
        "language_patcher_records": matches,
    }


def _safe_loaded_size(patcher) -> int | None:
    method = getattr(patcher, "loaded_size", None)
    if not callable(method):
        return None
    try:
        return int(method())
    except BaseException:
        return None


def _language_residency(handle) -> dict:
    """Summarize language/static residency without dumping tensor contents."""

    linears = tuple(getattr(handle, "_streaming_linears", ()) or ())
    linear_devices: Counter[str] = Counter()
    linear_dtypes: Counter[str] = Counter()
    for module in linears:
        for value in list(module.parameters(recurse=False)) + list(module.buffers(recurse=False)):
            linear_devices[str(value.device)] += 1
            linear_dtypes[str(value.dtype)] += 1

    all_devices: Counter[str] = Counter()
    all_dtypes: Counter[str] = Counter()
    movable = getattr(handle, "_movable", lambda: ())()
    for module in movable:
        for value in list(module.parameters()) + list(module.buffers()):
            all_devices[str(value.device)] += 1
            all_dtypes[str(value.dtype)] += 1

    return {
        "streaming_linear_module_count": len(linears),
        "streaming_linear_tensor_device_distribution": dict(linear_devices),
        "streaming_linear_tensor_dtype_distribution": dict(linear_dtypes),
        "movable_language_tensor_device_distribution": dict(all_devices),
        "movable_language_tensor_dtype_distribution": dict(all_dtypes),
        "linear_storage_bytes": int(getattr(handle, "_linear_storage_bytes", 0)),
        "static_storage_bytes": int(getattr(handle, "_static_storage_bytes", 0)),
    }


def _state_summary(handle, mm, *, include_loaded_size: bool = True) -> dict:
    patcher = getattr(handle, "_linear_patcher", None)
    summary = {
        "linear_patcher": {
            "present": patcher is not None,
            "type": type(patcher).__name__ if patcher is not None else None,
            "loaded_size_bytes": _safe_loaded_size(patcher) if include_loaded_size and patcher is not None else None,
        },
        "compute_device": str(getattr(handle, "_compute_device", None))
        if getattr(handle, "_compute_device", None) is not None else None,
        "inference_active": bool(getattr(handle, "_inference_active", False)),
        "language_residency": _language_residency(handle),
        "visual": _module_inventory(handle.model.visual),
    }
    summary["comfy_model_management"] = _loaded_model_summary(mm, patcher)
    return summary


def _child(log_path: Path) -> int:
    with log_path.open("w", encoding="utf-8", buffering=1) as stream:
        original_stdout = sys.stdout
        original_stderr = sys.stderr
        trace_messages: list[str] = []

        class Tee:
            def write(self, value):
                sys.__stdout__.write(value)
                stream.write(value)
                stream.flush()

            def flush(self):
                sys.__stdout__.flush()
                stream.flush()

        class TraceHandler(logging.Handler):
            def emit(self, record):
                trace_messages.append(record.getMessage())

        trace_handler = TraceHandler()
        h3_logger = logging.getLogger("minimax_h3_nodes")
        original_logger_level = h3_logger.level
        h3_logger.addHandler(trace_handler)
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
                "C2G1-PRECHECK",
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
                _marker(stream, "C2G1-PRECHECK_BLOCKED", reason="FREE_COMMIT_BELOW_30_GIB", **memory)
                return 20
            if bool(runtime_lock.get("job_running", False)):
                _marker(stream, "C2G1-PRECHECK_BLOCKED", reason="GPU_JOB_ALREADY_RUNNING")
                return 20

            comfy_root = runtime / "ComfyUI"
            h3_root = comfy_root / "custom_nodes" / "ComfyUI_RH_MinMaxH3"
            os.chdir(comfy_root)
            sys.path.insert(0, str(comfy_root))
            sys.path.insert(0, str(h3_root))

            import torch
            from PIL import Image
            from minimax_h3_nodes.api import _shared
            from minimax_h3_nodes.runtime.qwen_encoder.loading import load_h3_text_encoder

            if not torch.cuda.is_available():
                _marker(stream, "C2G1-PRECHECK_BLOCKED", reason="CUDA_UNAVAILABLE")
                return 20
            gpu_free, gpu_total = torch.cuda.mem_get_info()

            root_name = "MiniMax-H3"
            selector = _shared._default_te_model_name()
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
            import comfy.model_management as mm

            visual = handle.model.visual
            initial = _state_summary(handle, mm)
            if (
                initial["linear_patcher"]["present"]
                or initial["compute_device"] is not None
                or initial["inference_active"]
                or initial["visual"]["device_distribution"] != {"cpu": 352}
            ):
                _marker(stream, "C2G1-OTHER_FAILURE", reason="FRESH_STATE_CONTRACT_FAILED", state=initial)
                return 30
            _marker(
                stream,
                "C2G1-01",
                label="FRESH_QWEN_READY",
                component=str(selected_component),
                weights=str(selected_weights) if selected_weights else None,
                tokenizer_component=str(getattr(handle, "tokenizer_component_path", "")),
                processor_component=str(getattr(handle, "processor_component_path", "")),
                torch=str(torch.__version__),
                cuda=torch.version.cuda,
                gpu_free_gib=round(gpu_free / 2**30, 3),
                gpu_total_gib=round(gpu_total / 2**30, 3),
                state=initial,
            )

            image = Image.open(ROOT / "samples" / "01_Exterior_Hero.png").convert("RGB")
            prepared = _production_fl2va_preprocess(handle, image)
            if prepared["image_grid_thw"].tolist() != [[1, 48, 84]] or prepared["image_token_counts"] != [1008]:
                _marker(
                    stream,
                    "C2G1-OTHER_FAILURE",
                    reason="PRODUCTION_PREPROCESSING_REFERENCE_MISMATCH",
                    grid=prepared["image_grid_thw"].tolist(),
                    image_token_counts=prepared["image_token_counts"],
                )
                return 30

            handle.load_for_inference()
            loaded_state = _state_summary(handle, mm)
            if not loaded_state["linear_patcher"]["present"] or not loaded_state["inference_active"]:
                _marker(stream, "C2G1-LANGUAGE_LOAD_FAILURE", reason="REAL_PATCHER_STATE_NOT_CREATED", state=loaded_state)
                return 31
            if loaded_state["visual"]["device_distribution"] != {"cpu": 352}:
                _marker(stream, "C2G1-LANGUAGE_LOAD_FAILURE", reason="VISUAL_LEFT_CPU_INVARIANT", state=loaded_state)
                return 31
            _marker(stream, "C2G1-02", label="LANGUAGE_PATCHER_CREATED", state=loaded_state)

            handle.offload_after_inference()
            offloaded_state = _state_summary(handle, mm)
            physical_unloaded = (
                offloaded_state["linear_patcher"]["loaded_size_bytes"] == 0
                and not offloaded_state["inference_active"]
                and offloaded_state["compute_device"] is None
            )
            if not physical_unloaded:
                _marker(stream, "C2G1-LANGUAGE_OFFLOAD_FAILURE", reason="PHYSICAL_PATCHER_REMAINS_LOADED", state=offloaded_state)
                return 32
            _marker(
                stream,
                "C2G1-03",
                label="LANGUAGE_PATCHER_OFFLOADED",
                physical_unloaded=physical_unloaded,
                state=offloaded_state,
            )
            _marker(
                stream,
                "C2G1-04",
                label="SINGLE_FACTOR_PRECALL_CAPTURED",
                state=offloaded_state,
                gpu_free_gib=round(torch.cuda.mem_get_info()[0] / 2**30, 3),
                gpu_total_gib=round(torch.cuda.mem_get_info()[1] / 2**30, 3),
                **_windows_memory(),
            )

            _marker(stream, "C2G1-05", label="BEFORE_STAGED_VISUAL_HELPER")
            image_features, video_features = handle._encode_visual_features_staged(
                pixel_values=prepared["pixel_values"],
                image_grid_thw=prepared["image_grid_thw"],
                pixel_values_videos=None,
                video_grid_thw=None,
            )
            _marker(
                stream,
                "C2G1-06",
                label="AFTER_STAGED_VISUAL_HELPER",
                video_features_present=video_features is not None,
                trace_messages=trace_messages[-30:],
            )
            if image_features is None:
                _marker(stream, "C2G1-OTHER_FAILURE", reason="IMAGE_FEATURES_MISSING")
                return 30
            _marker(stream, "C2G1-07", label="FEATURES_RETURNED_CPU", features=_feature_summary(image_features))
            post = _module_inventory(visual)
            cuda_count = sum(value for key, value in post["device_distribution"].items() if key.startswith("cuda"))
            _marker(
                stream,
                "C2G1-08",
                label="VISUAL_CPU_CONFIRMED",
                cpu_tensor_count=post["device_distribution"].get("cpu", 0),
                cuda_tensor_count=cuda_count,
                inventory=post,
            )
            if post["device_distribution"] != {"cpu": 352}:
                _marker(stream, "C2G1-OTHER_FAILURE", reason="VISUAL_POSTCONDITION_FAILED", inventory=post)
                return 30
            _marker(
                stream,
                "C2G1-09",
                label="PROCESS_SURVIVED",
                gpu_free_gib=round(torch.cuda.mem_get_info()[0] / 2**30, 3),
                gpu_total_gib=round(torch.cuda.mem_get_info()[1] / 2**30, 3),
            )
            return 0
        except BaseException as exc:
            _marker(stream, "C2G1-OTHER_FAILURE", exception=type(exc).__name__, message=str(exc))
            traceback.print_exc()
            return 30
        finally:
            h3_logger.removeHandler(trace_handler)
            h3_logger.setLevel(original_logger_level)
            sys.stdout = original_stdout
            sys.stderr = original_stderr


def _parent() -> int:
    runtime, models = _runtime_and_models()
    lock = _support_lock(runtime)
    from runtime.h3_model_root import h3_process_environment

    output_dir = ROOT / "userdata" / "cache" / "temp" / "f3_c2_g1"
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    log_path = output_dir / f"language_patcher_child_{stamp}.log"
    result_path = output_dir / f"language_patcher_result_{stamp}.json"
    env = os.environ.copy()
    env.update(h3_process_environment(str(models)))
    env["H3_WINDOWS_SAFE_LOAD"] = "pread"
    env["PYTHONUNBUFFERED"] = "1"
    comfy_root = runtime / "ComfyUI"
    env["PYTHONPATH"] = os.pathsep.join(
        [str(ROOT), str(comfy_root), str(comfy_root / "custom_nodes" / "ComfyUI_RH_MinMaxH3"), env.get("PYTHONPATH", "")]
    ).strip(os.pathsep)
    started = time.time()
    started_iso = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    log_path.write_text(
        json.dumps(
            {
                "parent": "C2G1",
                "runtime": str(runtime),
                "models_root": str(models),
                "start_timestamp": started_iso,
                "started": started,
                "h3_commit": lock["h3"]["commit"],
                "h3_fingerprint": lock["h3"]["source_tree_fingerprint"],
                "h3_patch_sha256": lock["h3"]["project_patch_sha256"],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    managed_python = runtime / "python_embeded" / "python.exe"
    if not managed_python.is_file():
        raise RuntimeError(f"managed embedded Python missing: {managed_python}")
    child = subprocess.Popen(
        [str(managed_python), str(Path(__file__).resolve()), "--child", "--log", str(log_path)],
        cwd=str(comfy_root),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    pid = child.pid
    with log_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"parent": "C2G1", "pid": pid}, ensure_ascii=False) + "\n")
    code = child.wait()
    ended = time.time()
    ended_iso = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    text = log_path.read_text(encoding="utf-8", errors="replace")
    stages = re.findall(r'"stage":\s*"([^"]+)"', text)
    last_stage = stages[-1] if stages else "NONE"
    if code == 0 and "C2G1-09" in stages:
        classification = "PATCHER_RESIDUAL_CONTEXT_PASS"
    elif code in ACCESS_VIOLATION_CODES:
        classification = "PATCHER_RESIDUAL_CONTEXT_ACCESS_VIOLATION_REPRODUCED"
    elif last_stage in {"C2G1-05", "C2G1-06", "C2G1-07", "C2G1-08"} and code != 0:
        classification = "PATCHER_RESIDUAL_CONTEXT_ACCESS_VIOLATION_REPRODUCED"
    elif "C2G1-LANGUAGE_LOAD_FAILURE" in stages:
        classification = "LANGUAGE_LOAD_FAILURE"
    elif "C2G1-LANGUAGE_OFFLOAD_FAILURE" in stages:
        classification = "LANGUAGE_OFFLOAD_FAILURE"
    elif "C2G1-PRECHECK_BLOCKED" in stages:
        classification = "PRECHECK_BLOCKED"
    else:
        classification = "OTHER_TARGETED_FAILURE"
    summary = {
        "classification": classification,
        "pid": pid,
        "start_timestamp": started_iso,
        "end_timestamp": ended_iso,
        "exit_code": code,
        "last_stage": last_stage,
        "stages": stages,
        "elapsed_seconds": round(ended - started, 3),
        "runtime": str(runtime),
        "models_root": str(models),
        "log_path": str(log_path),
        "result_path": str(result_path),
        "prompt_submitted": False,
        "studio_job_created": False,
        "encode_ids_called": False,
        "language_forward_entered": False,
        "dit_loaded": False,
        "vae_loaded": False,
        "vhs_loaded": False,
    }
    result_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--log", type=Path)
    args = parser.parse_args()
    if args.child:
        if args.log is None:
            raise SystemExit("--child requires --log")
        return _child(args.log)
    return _parent()


if __name__ == "__main__":
    raise SystemExit(main())
