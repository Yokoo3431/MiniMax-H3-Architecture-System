"""One supervised, baseline-only Qwen visual device-cycle probe.

The parent starts a child with the managed embedded Python.  The child loads
only the pinned H3 Qwen component, performs one real image visual forward and
the current whole-module CPU return.  It never calls Studio, ComfyUI, /prompt,
the language stage, DiT, either VAE, a sampler, or VHS.
"""

from __future__ import annotations

import argparse
from collections import Counter
import ctypes
import ctypes.wintypes as wintypes
import json
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
EXPECTED_H3_COMMIT = "d6c5f7b0d4e03936ac4a9834be63ecc6b5637dad"
EXPECTED_H3_FINGERPRINT = "abd60d555fc6197a9b6e283f9e83379ac7143fb42469a20b6ef74bff6a0d737b"
EXPECTED_H3_PATCH_SHA256 = "488ab271e68d226a690f3c1dc322a9fc15a0eba7273045e890a871de2c0196bd"
EXPECTED_VHS_COMMIT = "4ee72c065db22c9d96c2427954dc69e7b908444b"
ACCESS_VIOLATION_CODES = {-1073741819, 3221225477}


def _state() -> dict:
    return json.loads((ROOT / "userdata" / "system" / "setup_state.json").read_text(encoding="utf-8"))


def _runtime_and_models() -> tuple[Path, Path]:
    state = _state()
    runtime = Path((ROOT / "native_env.path").read_text(encoding="utf-8").strip()).expanduser().resolve()
    configured_runtime = Path(str(state.get("native_root") or "")).expanduser().resolve()
    models = Path(str(state.get("models_root") or "")).expanduser().resolve()
    if runtime.name != "ArchitectVideoStudio_Runtime":
        raise RuntimeError(f"active runtime identity mismatch: {runtime}")
    if configured_runtime != runtime:
        raise RuntimeError("active runtime state mismatch: native_env.path vs setup_state.json")
    if not runtime.is_dir() or not models.is_dir():
        raise RuntimeError("configured managed runtime or models root is missing")
    return runtime, models


def _support_lock(runtime: Path) -> dict:
    path = runtime / "ComfyUI" / "custom_nodes" / "support_layer.lock.json"
    lock = json.loads(path.read_text(encoding="utf-8"))
    h3 = lock.get("h3", {})
    vhs = lock.get("video_helper_suite", {})
    if h3.get("commit") != EXPECTED_H3_COMMIT:
        raise RuntimeError("H3 support lock commit mismatch")
    if h3.get("source_tree_fingerprint") != EXPECTED_H3_FINGERPRINT:
        raise RuntimeError("H3 support lock fingerprint mismatch")
    if h3.get("project_patch_sha256") != EXPECTED_H3_PATCH_SHA256:
        raise RuntimeError("H3 support lock project patch mismatch")
    if vhs.get("commit") != EXPECTED_VHS_COMMIT:
        raise RuntimeError("VHS support lock commit mismatch")
    if lock.get("pread", {}).get("environment") != "H3_WINDOWS_SAFE_LOAD=pread":
        raise RuntimeError("PREAD support lock mismatch")
    return lock


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


def _windows_memory() -> dict[str, int]:
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


def _marker(log, name: str, **fields) -> None:
    record = {"stage": name, "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **fields}
    print(json.dumps(record, ensure_ascii=False), flush=True)
    if isinstance(log, list):
        log.append(record)


def _module_inventory(module) -> dict:
    parameters = list(module.named_parameters())
    buffers = list(module.named_buffers())
    tensors = [(name, value, "parameter") for name, value in parameters]
    tensors += [(name, value, "buffer") for name, value in buffers]
    return {
        "parameter_count": len(parameters),
        "buffer_count": len(buffers),
        "tensor_count": len(tensors),
        "dtype_distribution": dict(Counter(str(value.dtype) for _, value, _ in tensors)),
        "device_distribution": dict(Counter(str(value.device) for _, value, _ in tensors)),
        "tensor_class_distribution": dict(Counter(type(value).__name__ for _, value, _ in tensors)),
        "parameter_bytes": sum(int(getattr(value, "nbytes", 0)) for _, value, _ in tensors),
    }


def _feature_summary(features: dict) -> dict:
    pooled = features["pooled"]
    deepstack = features["deepstack"]
    tensors = [pooled, *deepstack]
    return {
        "tensor_count": len(tensors),
        "dtype_distribution": dict(Counter(str(value.dtype) for value in tensors)),
        "shapes": [list(value.shape) for value in tensors],
        "bytes": sum(int(value.nbytes) for value in tensors),
        "devices": sorted({str(value.device) for value in tensors}),
    }


def _production_fl2va_preprocess(handle, image, *, tokenizer=None, processor=None):
    """Mirror MiniMaxH3TextEncoder.encode_fl2va_conditioning without encode_ids."""
    import torch
    from minimax_h3_nodes.runtime.presentation import (
        minimax_h3_multi_image_presentation_ids,
        minimax_h3_multi_image_presentation_token_tags,
    )

    prompt = "A modern architectural exterior with clear massing and daylight."
    processor_obj = processor if processor is not None else handle.processor
    tokenizer_obj = tokenizer if tokenizer is not None else handle.tokenizer
    image_processor = getattr(processor_obj, "image_processor", None)
    if not callable(image_processor):
        raise RuntimeError("production processor has no callable image_processor")
    vision = image_processor(images=[image], return_tensors="pt")
    pixel_values = vision.get("pixel_values")
    image_grid_thw = vision.get("image_grid_thw")
    if pixel_values is None or image_grid_thw is None:
        raise RuntimeError("production image_processor must return pixel_values and image_grid_thw")
    if image_grid_thw.ndim != 2 or tuple(image_grid_thw.shape[1:]) != (3,):
        raise RuntimeError(f"image_grid_thw must be [N,3], got {tuple(image_grid_thw.shape)}")
    if int(image_grid_thw.shape[0]) != 1:
        raise RuntimeError(f"expected one image grid, got {int(image_grid_thw.shape[0])}")
    merge_size = int(getattr(image_processor, "merge_size", 0))
    if merge_size <= 0:
        raise RuntimeError("image_processor merge_size must be positive")
    image_token_counts = [int(image_grid_thw[0].prod().item()) // (merge_size ** 2)]
    if image_token_counts[0] <= 0:
        raise RuntimeError("image token count must be positive")
    input_ids = minimax_h3_multi_image_presentation_ids(
        tokenizer_obj, prompt=prompt, image_token_counts=image_token_counts
    )
    token_tags = minimax_h3_multi_image_presentation_token_tags(
        tokenizer_obj, prompt=prompt, image_token_counts=image_token_counts
    )
    if input_ids.ndim != 1 or int(input_ids.numel()) <= 0:
        raise RuntimeError("production presentation input_ids must be non-empty 1-D")
    if token_tags.ndim != 1 or int(token_tags.numel()) != int(input_ids.numel()):
        raise RuntimeError("production presentation token_tags must align with input_ids")
    image_pad_id = int(tokenizer_obj.convert_tokens_to_ids("<|image_pad|>"))
    placeholder_count = int((input_ids == image_pad_id).sum().item())
    if placeholder_count != image_token_counts[0]:
        raise RuntimeError(
            f"image placeholder/token count mismatch: {placeholder_count} != {image_token_counts[0]}"
        )
    return {
        "pixel_values": pixel_values,
        "image_grid_thw": image_grid_thw,
        "image_token_counts": image_token_counts,
        "merge_size": merge_size,
        "input_ids": input_ids.to(device="cpu", dtype=torch.long),
        "token_tags": token_tags.to(device="cpu", dtype=torch.long),
        "prompt": prompt,
    }


def _child(log_path: Path) -> int:
    events: list[dict] = []
    with log_path.open("w", encoding="utf-8", buffering=1) as stream:
        original_stdout = sys.stdout
        original_stderr = sys.stderr

        class Tee:
            def write(self, value):
                sys.__stdout__.write(value)
                stream.write(value)
                stream.flush()

            def flush(self):
                sys.__stdout__.flush()
                stream.flush()

        sys.stdout = Tee()
        sys.stderr = Tee()
        try:
            runtime, models = _runtime_and_models()
            lock = _support_lock(runtime)
            memory = _windows_memory()
            disk = shutil.disk_usage(models.anchor)
            _marker(
                stream,
                "G1-PRECHECK",
                runtime=str(runtime),
                models_root=str(models),
                h3_commit=lock["h3"]["commit"],
                h3_fingerprint=lock["h3"]["source_tree_fingerprint"],
                torch_env=os.environ.get("H3_WINDOWS_SAFE_LOAD"),
                **memory,
                d_free_gib=round(disk.free / 2**30, 3),
            )
            if memory["free_commit_bytes"] < 30 * 2**30:
                _marker(stream, "G1-PRECHECK_BLOCKED", reason="FREE_COMMIT_BELOW_30_GIB", **memory)
                return 20

            comfy_root = runtime / "ComfyUI"
            h3_root = comfy_root / "custom_nodes" / "ComfyUI_RH_MinMaxH3"
            os.chdir(comfy_root)
            sys.path.insert(0, str(comfy_root))
            sys.path.insert(0, str(h3_root))

            import torch
            from PIL import Image
            from minimax_h3_nodes.api import _shared
            from minimax_h3_nodes.runtime import components
            from minimax_h3_nodes.runtime.qwen_encoder.loading import load_h3_text_encoder
            from transformers import AutoProcessor, AutoTokenizer

            if not torch.cuda.is_available():
                _marker(stream, "G1-PRECHECK_BLOCKED", reason="CUDA_UNAVAILABLE")
                return 20
            gpu_free, gpu_total = torch.cuda.mem_get_info()
            root_name = "MiniMax-H3"
            selector = _shared._default_te_model_name()
            partition_root, _info, _sigma = _shared._resolve_t2va_release(
                root_name, required_component=_shared._selector_to_component_dirname(
                    selector, "text_encoder", "fl2va", model_root=root_name
                ), required_files=("config.json",)
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
                str(selected_component), use_fast=True,
                local_files_only=True, trust_remote_code=False,
            )
            processor = AutoProcessor.from_pretrained(
                str(selected_component), local_files_only=True,
                trust_remote_code=False,
            )
            _marker(
                stream, "G1R3-01", label="TOKENIZER_READY",
                tokenizer_class=tokenizer.__class__.__name__,
                tokenizer_fast=bool(getattr(tokenizer, "is_fast", False)),
            )
            _marker(
                stream, "G1R3-02", label="PROCESSOR_READY",
                processor_class=processor.__class__.__name__,
                image_processor_class=processor.image_processor.__class__.__name__,
            )
            sample = ROOT / "samples" / "01_Exterior_Hero.png"
            image = Image.open(sample).convert("RGB")
            prepared = _production_fl2va_preprocess(
                None, image, tokenizer=tokenizer, processor=processor
            )
            pixel_values = prepared["pixel_values"]
            image_grid_thw = prepared["image_grid_thw"]
            _marker(
                stream, "G1R3-03", label="PREPROCESSING_READY",
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
                stream, "G1R3-04", label="QWEN_COMPONENT_READY",
                component=str(selected_component),
                weights=str(selected_weights) if selected_weights else None,
                torch=str(torch.__version__), cuda=torch.version.cuda,
                gpu_free_gib=round(gpu_free / 2**30, 3),
                gpu_total_gib=round(gpu_total / 2**30, 3),
            )
            visual = handle.model.visual
            inventory = _module_inventory(visual)
            _marker(stream, "G1R3-05", label="VISUAL_CPU_CONFIRMED", **inventory)
            if any(device != "cpu" for device in inventory["device_distribution"]):
                _marker(stream, "G1R3-OTHER_FAILURE", reason="VISUAL_NOT_CPU_BEFORE_MIGRATION", inventory=inventory)
                return 30
            if (
                inventory["parameter_count"] != 351
                or inventory["buffer_count"] != 1
                or inventory["tensor_count"] != 352
                or set(inventory["dtype_distribution"]) != {"torch.float32"}
                or any("QuantizedTensor" in key for key in inventory["tensor_class_distribution"])
            ):
                _marker(stream, "G1R3-OTHER_FAILURE", reason="LIVE_VISUAL_CONTRACT_CONTRADICTS_R5", inventory=inventory)
                return 30
            load_device = handle.load_device
            offload_device = handle.offload_device
            _marker(stream, "G1R3-06", label="BEFORE_VISUAL_TO_CUDA", load_device=str(load_device))
            visual.to(load_device)
            gpu_free, gpu_total = torch.cuda.mem_get_info()
            _marker(stream, "G1R3-07", label="AFTER_VISUAL_TO_CUDA", gpu_free_gib=round(gpu_free / 2**30, 3), gpu_total_gib=round(gpu_total / 2**30, 3), inventory=_module_inventory(visual))

            parameter = next(visual.parameters(), None)
            visual_dtype = parameter.dtype if parameter is not None and parameter.is_floating_point() else torch.bfloat16
            _marker(stream, "G1R3-08", label="BEFORE_IMAGE_FORWARD", pixel_shape=list(pixel_values.shape), grid_shape=list(image_grid_thw.shape))
            output = handle._call_vision_feature_getter(
                handle.model.get_image_features,
                pixel_values.to(device=load_device, dtype=visual_dtype),
                image_grid_thw.to(device=load_device, dtype=torch.long),
            )
            _marker(stream, "G1R3-09", label="AFTER_IMAGE_FORWARD")
            features = handle._vision_output_to_cpu(output, context="g1_image")
            del output
            _marker(stream, "G1R3-10", label="FEATURES_COPIED_TO_CPU", features=_feature_summary(features))
            _marker(stream, "G1R3-11", label="BEFORE_VISUAL_TO_CPU", offload_device=str(offload_device))
            visual.to(offload_device)
            _marker(stream, "G1R3-12", label="AFTER_VISUAL_TO_CPU", inventory=_module_inventory(visual))
            if any(device != "cpu" for device in _module_inventory(visual)["device_distribution"]):
                _marker(stream, "G1R3-OTHER_FAILURE", reason="VISUAL_REMAINS_NON_CPU")
                return 30
            del features, pixel_values, image_grid_thw, image, prepared, handle, visual
            torch.cuda.empty_cache()
            gpu_free, gpu_total = torch.cuda.mem_get_info()
            _marker(stream, "G1R3-13", label="PROCESS_SURVIVED", gpu_free_gib=round(gpu_free / 2**30, 3), gpu_total_gib=round(gpu_total / 2**30, 3))
            return 0
        except BaseException as exc:
            _marker(stream, "G1R3-OTHER_FAILURE", exception=type(exc).__name__, message=str(exc))
            traceback.print_exc()
            return 30
        finally:
            # The log stream is scoped by the surrounding ``with`` block.  If
            # the Tee objects remain installed after it closes, Python's
            # interpreter shutdown may flush a closed stream and convert an
            # otherwise successful child into exit code 120.  Restore the
            # original process streams before the log file is closed.
            sys.stdout = original_stdout
            sys.stderr = original_stderr


def _parent() -> int:
    runtime, models = _runtime_and_models()
    _support_lock(runtime)
    from runtime.h3_model_root import h3_process_environment

    output_dir = ROOT / "userdata" / "cache" / "temp" / "f3_g1_r3"
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    log_path = output_dir / f"qwen_visual_child_{stamp}.log"
    result_path = output_dir / f"qwen_visual_result_{stamp}.json"
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
        stream.write(json.dumps({"parent": "G1R3", "runtime": str(runtime), "models_root": str(models), "start_timestamp": started_iso, "started": started}, ensure_ascii=False) + "\n")
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
        stream.write(json.dumps({"parent": "G1R3", "pid": pid}, ensure_ascii=False) + "\n")
    code = child.wait()
    ended = time.time()
    ended_iso = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    elapsed = round(ended - started, 3)
    text = log_path.read_text(encoding="utf-8", errors="replace")
    stages = re.findall(r'"stage":\s*"([^"]+)"', text)
    last_stage = stages[-1] if stages else "NONE"
    if code == 0 and "G1R3-13" in stages:
        classification = "CURRENT_PATH_PASS"
    elif code in ACCESS_VIOLATION_CODES or (last_stage == "G1R3-11" and code != 0):
        classification = "CURRENT_PATH_ACCESS_VIOLATION_REPRODUCED"
    elif last_stage == "G1R3-08" and code != 0:
        classification = "IMAGE_FORWARD_FAILURE"
    elif last_stage == "G1R3-09" and code != 0:
        classification = "FEATURE_COPY_FAILURE"
    elif last_stage == "G1-PRECHECK_BLOCKED":
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
        "elapsed_seconds": elapsed,
        "runtime": str(runtime),
        "models_root": str(models),
        "log_path": str(log_path),
        "result_path": str(result_path),
        "prompt_submitted": False,
        "studio_job_created": False,
        "dit_loaded": False,
        "vae_loaded": False,
        "vhs_loaded": False,
        "language_stage_entered": False,
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
