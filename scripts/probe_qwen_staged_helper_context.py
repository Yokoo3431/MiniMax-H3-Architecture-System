"""One supervised C1-G1 probe of the pinned staged visual helper.

This script adds exactly one condition to the successful G1-R3 baseline: the
real ``MiniMaxH3TextEncoder._encode_visual_features_staged`` seam with real
Comfy model-management imports. It never enters ``encode_ids`` or the language
stage and never submits a Studio/ComfyUI job.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import os
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
    _feature_summary,
    _marker,
    _module_inventory,
    _production_fl2va_preprocess,
    _runtime_and_models,
    _support_lock,
    _windows_memory,
)


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
            _marker(
                stream,
                "C1G1-PRECHECK",
                runtime=str(runtime),
                models_root=str(models),
                h3_commit=lock["h3"]["commit"],
                h3_fingerprint=lock["h3"]["source_tree_fingerprint"],
                torch_env=os.environ.get("H3_WINDOWS_SAFE_LOAD"),
                **memory,
                d_free_gib=round(disk.free / 2**30, 3),
            )
            if memory["free_commit_bytes"] < 30 * 2**30:
                _marker(stream, "C1G1-PRECHECK_BLOCKED", reason="FREE_COMMIT_BELOW_30_GIB", **memory)
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
            from transformers import AutoProcessor, AutoTokenizer

            if not torch.cuda.is_available():
                _marker(stream, "C1G1-PRECHECK_BLOCKED", reason="CUDA_UNAVAILABLE")
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
            tokenizer = AutoTokenizer.from_pretrained(
                str(selected_component),
                use_fast=True,
                local_files_only=True,
                trust_remote_code=False,
            )
            _marker(
                stream,
                "C1G1-01",
                label="TOKENIZER_READY",
                tokenizer_class=tokenizer.__class__.__name__,
                tokenizer_fast=bool(getattr(tokenizer, "is_fast", False)),
            )
            processor = AutoProcessor.from_pretrained(
                str(selected_component),
                local_files_only=True,
                trust_remote_code=False,
            )
            _marker(
                stream,
                "C1G1-02",
                label="PROCESSOR_READY",
                processor_class=processor.__class__.__name__,
                image_processor_class=processor.image_processor.__class__.__name__,
            )
            image = Image.open(ROOT / "samples" / "01_Exterior_Hero.png").convert("RGB")
            prepared = _production_fl2va_preprocess(
                None, image, tokenizer=tokenizer, processor=processor
            )
            pixel_values = prepared["pixel_values"]
            image_grid_thw = prepared["image_grid_thw"]
            _marker(
                stream,
                "C1G1-03",
                label="PREPROCESSING_READY",
                pixel_shape=list(pixel_values.shape),
                pixel_dtype=str(pixel_values.dtype),
                grid_shape=list(image_grid_thw.shape),
                grid=image_grid_thw.tolist(),
                merge_size=prepared["merge_size"],
                image_token_counts=prepared["image_token_counts"],
                input_ids_count=int(prepared["input_ids"].numel()),
                image_placeholders=int(prepared["image_token_counts"][0]),
                token_tags_count=int(prepared["token_tags"].numel()),
            )
            del tokenizer, processor

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
            _marker(
                stream,
                "C1G1-04",
                label="QWEN_COMPONENT_READY",
                component=str(selected_component),
                weights=str(selected_weights) if selected_weights else None,
                torch=str(torch.__version__),
                cuda=torch.version.cuda,
                gpu_free_gib=round(gpu_free / 2**30, 3),
                gpu_total_gib=round(gpu_total / 2**30, 3),
            )

            import comfy.model_management as mm

            lock_state = {}
            lock_path = ROOT / "launcher" / "runtime.lock"
            if lock_path.is_file():
                try:
                    lock_state = json.loads(lock_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    lock_state = {}
            job_running = bool(lock_state.get("job_running", False))
            _marker(
                stream,
                "C1G1-05",
                label="COMFY_MODEL_MANAGEMENT_READY",
                module=mm.__name__,
                cuda_available=bool(torch.cuda.is_available()),
                job_running=job_running,
            )
            if job_running:
                _marker(stream, "C1G1-PRECHECK_BLOCKED", reason="GPU_JOB_ALREADY_RUNNING")
                return 20
            visual = handle.model.visual
            inventory = _module_inventory(visual)
            patcher = getattr(handle, "_linear_patcher", None)
            compute_device = getattr(handle, "_compute_device", None)
            inference_active = bool(getattr(handle, "_inference_active", False))
            _marker(
                stream,
                "C1G1-06",
                label="STAGED_PRECALL_STATE_CAPTURED",
                linear_patcher="present" if patcher is not None else "absent",
                compute_device=str(compute_device) if compute_device is not None else None,
                inference_active=inference_active,
                offload_entry_physical_work=(patcher is not None or inference_active),
                visual=inventory,
            )
            if inventory["device_distribution"] != {"cpu": 352}:
                _marker(stream, "C1G1-OTHER_FAILURE", reason="VISUAL_NOT_CPU_PRECALL", inventory=inventory)
                return 30

            _marker(stream, "C1G1-07", label="BEFORE_STAGED_VISUAL_HELPER")
            image_features, video_features = handle._encode_visual_features_staged(
                pixel_values=pixel_values,
                image_grid_thw=image_grid_thw,
                pixel_values_videos=None,
                video_grid_thw=None,
            )
            _marker(
                stream,
                "C1G1-08",
                label="AFTER_STAGED_VISUAL_HELPER",
                video_features_present=video_features is not None,
                visual_trace_messages=trace_messages[-20:],
            )
            if image_features is None:
                _marker(stream, "C1G1-OTHER_FAILURE", reason="IMAGE_FEATURES_MISSING")
                return 30
            _marker(stream, "C1G1-09", label="FEATURES_RETURNED_CPU", features=_feature_summary(image_features))
            post_inventory = _module_inventory(visual)
            _marker(
                stream,
                "C1G1-10",
                label="VISUAL_CPU_CONFIRMED",
                cpu_tensor_count=post_inventory["device_distribution"].get("cpu", 0),
                cuda_tensor_count=sum(
                    value for key, value in post_inventory["device_distribution"].items()
                    if key.startswith("cuda")
                ),
                inventory=post_inventory,
            )
            if post_inventory["device_distribution"] != {"cpu": 352}:
                _marker(stream, "C1G1-OTHER_FAILURE", reason="VISUAL_POSTCONDITION_FAILED", inventory=post_inventory)
                return 30
            del image_features, video_features, pixel_values, image_grid_thw, prepared, image, handle, visual
            gpu_free, gpu_total = torch.cuda.mem_get_info()
            _marker(
                stream,
                "C1G1-11",
                label="PROCESS_SURVIVED",
                gpu_free_gib=round(gpu_free / 2**30, 3),
                gpu_total_gib=round(gpu_total / 2**30, 3),
            )
            return 0
        except BaseException as exc:
            _marker(stream, "C1G1-OTHER_FAILURE", exception=type(exc).__name__, message=str(exc))
            traceback.print_exc()
            return 30
        finally:
            h3_logger.removeHandler(trace_handler)
            h3_logger.setLevel(original_logger_level)
            sys.stdout = original_stdout
            sys.stderr = original_stderr


def _parent() -> int:
    runtime, models = _runtime_and_models()
    _support_lock(runtime)
    from runtime.h3_model_root import h3_process_environment

    output_dir = ROOT / "userdata" / "cache" / "temp" / "f3_c1_g1"
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    log_path = output_dir / f"staged_helper_child_{stamp}.log"
    result_path = output_dir / f"staged_helper_result_{stamp}.json"
    env = os.environ.copy()
    env.update(h3_process_environment(str(models)))
    env["H3_WINDOWS_SAFE_LOAD"] = "pread"
    env["PYTHONUNBUFFERED"] = "1"
    comfy_root = runtime / "ComfyUI"
    env["PYTHONPATH"] = os.pathsep.join(
        [str(comfy_root), str(comfy_root / "custom_nodes" / "ComfyUI_RH_MinMaxH3"), env.get("PYTHONPATH", "")]
    ).strip(os.pathsep)
    started = time.time()
    started_iso = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    with log_path.open("w", encoding="utf-8") as stream:
        stream.write(json.dumps({"parent": "C1G1", "runtime": str(runtime), "models_root": str(models), "start_timestamp": started_iso, "started": started}, ensure_ascii=False) + "\n")
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
        stream.write(json.dumps({"parent": "C1G1", "pid": pid}, ensure_ascii=False) + "\n")
    code = child.wait()
    ended = time.time()
    ended_iso = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    text = log_path.read_text(encoding="utf-8", errors="replace")
    stages = re.findall(r'"stage":\s*"([^"]+)"', text)
    last_stage = stages[-1] if stages else "NONE"
    if code == 0 and "C1G1-11" in stages:
        classification = "STAGED_CONTEXT_PASS"
    elif code in ACCESS_VIOLATION_CODES:
        classification = "STAGED_CONTEXT_ACCESS_VIOLATION_REPRODUCED"
    elif last_stage in {"C1G1-07", "C1G1-08", "C1G1-09"} and code != 0:
        classification = "STAGED_CONTEXT_ACCESS_VIOLATION_REPRODUCED"
    elif last_stage == "C1G1-PRECHECK_BLOCKED":
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
        "language_stage_entered": False,
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
