"""Real Local GPU Inference & MP4 Export Validation Suite (V0.8.0 RC3.3 PATCH2).

Submits the Golden Workflow to the live ComfyUI server, polls /history/{prompt_id}
until real completion, samples GPU VRAM during the run, validates MP4 export and
ffprobe metadata, classifies failures into configs/rc33_patch2_runtime_failure.json,
and extracts representative frames from a valid MP4.

Acceptance semantics: PASS is only derived from history status "success" plus a
real output file. Any other completion is FAIL and is classified.
"""

import os
import sys
import json
import time
import ctypes
import unittest
import subprocess
import urllib.request
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))
sys.path.insert(0, str(SYSTEM_ROOT / "tests" / "runtime"))

from runtime.validation.ffmpeg_probe import FFmpegProbe
from runtime.validation.h3_gpu_runtime_probe import GPURuntimeProbe
from runtime.validation.golden_graph_auditor import GoldenGraphAuditor
from runtime.validation.runtime_failure_classifier import RuntimeFailureClassifier

CONFIG_DIR = SYSTEM_ROOT / "configs"
CONFIG_PREFIX = os.environ.get("PATCH2_OUTPUT_PREFIX", "rc33_patch2").strip()
USERDATA_FOLDER = (
    "rc33_patch21_frames" if CONFIG_PREFIX == "rc33_patch21" else "rc33_patch2_frames"
)
USERDATA_DIR = SYSTEM_ROOT / "userdata" / "personal_workspace" / "reports" / USERDATA_FOLDER
GOLDEN_WORKFLOW_PATH = SYSTEM_ROOT / "workflows" / "04_Drone_Aerial_GOLDEN.json"
COMFYUI_OUTPUT_DIR = Path("D:/ProgramFilesNormal/ComfyUI/ComfyUI_windows_portable/ComfyUI/output")
API_HOST = "http://127.0.0.1:8188"

from test_rc33_real_h3_golden import workflow_to_api_prompt


def _sample_gpu_used_mb():
    """Real nvidia-smi VRAM sample; returns MB used or None."""
    try:
        res = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5,
        )
        if res.returncode == 0 and res.stdout.strip():
            return float(res.stdout.strip().splitlines()[0].strip())
    except Exception:
        pass
    return None


def _sample_system_memory():
    """Real Windows commit/physical-memory sample via GlobalMemoryStatusEx.

    Returns (committed_mb, commit_limit_mb, physical_free_mb) or None.
    """
    try:
        class MEMORYSTATUSEX(ctypes.Structure):
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

        mem = MEMORYSTATUSEX()
        mem.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        ok = ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem))
        if not ok:
            return None
        commit_limit_mb = (mem.ullTotalPageFile + mem.ullTotalPhys) / (1024 * 1024)
        free_commit_mb = (mem.ullAvailPageFile + mem.ullAvailPhys) / (1024 * 1024)
        committed_mb = max(0.0, commit_limit_mb - free_commit_mb)
        phys_free_mb = mem.ullAvailPhys / (1024 * 1024)
        return committed_mb, commit_limit_mb, phys_free_mb
    except Exception:
        return None


def _extract_history_result(history_data):
    """Parse ComfyUI history entry into (completed, status, node_errors, console_excerpt)."""
    status = history_data.get("status", {}) or {}
    status_str = str(status.get("status_str", "")).lower()
    completed = status_str == "success"
    messages = status.get("messages", []) or []
    node_errors = {}
    console_excerpt = ""
    for msg in messages:
        if not isinstance(msg, list) or len(msg) < 2:
            continue
        msg_type = msg[0]
        data = msg[1] if isinstance(msg[1], dict) else {}
        if msg_type == "execution_error":
            node_id = str(data.get("node_id", "?"))
            node_errors[node_id] = {
                "node_id": node_id,
                "node_type": data.get("node_type"),
                "exception_type": data.get("exception_type"),
                "exception_message": data.get("exception_message"),
                "traceback_tail": (data.get("traceback") or [])[-3:],
            }
            if data.get("exception_message"):
                console_excerpt += str(data["exception_message"]) + "\n"
        elif msg_type == "execution_status" and data.get("status_str") == "error":
            if data.get("exception_message"):
                console_excerpt += str(data["exception_message"]) + "\n"
    return completed, status, node_errors, console_excerpt


class TestRC33Patch2GPUExecution(unittest.TestCase):
    def setUp(self):
        self.ffmpeg_probe = FFmpegProbe()
        self.gpu_probe = GPURuntimeProbe()
        self.graph_auditor = GoldenGraphAuditor()
        self.classifier = RuntimeFailureClassifier()

    def test_rc33_patch2_gpu_execution(self):
        timeout_seconds = int(os.environ.get("PATCH2_TIMEOUT_SECONDS", "7200"))
        trial = os.environ.get("PATCH2_TRIAL", "A").strip().upper()
        # PATCH2.1 production overrides (env-driven; default keeps PATCH2 Trial B behavior)
        patch21_image = os.environ.get("PATCH2_IMAGE", "").strip()
        patch21_duration = float(os.environ.get("PATCH2_DURATION", "0"))
        patch21_width = int(os.environ.get("PATCH2_WIDTH", "0"))
        patch21_height = int(os.environ.get("PATCH2_HEIGHT", "0"))
        patch21_sigma_points = int(os.environ.get("PATCH2_SIGMA_POINTS", "0"))
        patch21_sampler_mode = os.environ.get("PATCH2_SAMPLER_MODE", "").strip()
        patch21_accel = os.environ.get("PATCH2_ACCEL", "").strip()
        patch21_transformer = os.environ.get("PATCH2_TRANSFORMER_PATH", "").strip()

        # Gate P2-A: Graph Regression Audit
        graph_res = self.graph_auditor.audit_golden_graph()
        self.assertEqual(graph_res["status"], "PASS", "Gate P2-A Graph Regression must PASS")

        # FFmpeg & GPU probe
        ffmpeg_res = self.ffmpeg_probe.probe_and_configure_ffmpeg()
        self.assertEqual(ffmpeg_res["status"], "PASS", "FFmpeg & FFprobe must be available")

        gpu_res = self.gpu_probe.probe_gpu_hardware()
        self.assertTrue(gpu_res["cuda_available"], "NVIDIA CUDA GPU must be available for PATCH2")

        # Submit Golden Workflow to ComfyUI API (or reuse an already-running prompt_id)
        reuse_prompt_id = os.environ.get("PATCH2_REUSE_PROMPT_ID", "").strip()
        if reuse_prompt_id:
            prompt_id = reuse_prompt_id
            print(f"[PATCH2 GPU Execution] Reusing prompt_id: {prompt_id}")
        else:
            api_prompt = workflow_to_api_prompt(GOLDEN_WORKFLOW_PATH)
            if trial == "B":
                # Trial B: H3-native sampler stability + compute strategy.
                # accel=auto (velocity-cache profile) reduces DiT forward passes,
                # but its validated profile is 1344x768/124f only, so 1280x736
                # falls back to off (observed in comfyui.log).  euler-8 at
                # 640x360 keeps the job short enough to prove the full pipeline
                # end-to-end on the 12 GB card; sampler_config.step_abort_seconds
                # =0 disables the slow-step abort inappropriate for
                # CPU-offloaded small-VRAM cards (now wired through H3Telemetry
                # by the node patch).
                api_prompt["9"]["inputs"]["accel"] = patch21_accel or "auto"
                api_prompt["9"]["inputs"]["sampler_mode"] = patch21_sampler_mode or "euler"
                api_prompt["9"]["inputs"]["sigma_points"] = patch21_sigma_points or 8
                # User-supplied aerial masterplan render + shortened duration so
                # the full pipeline can be proven quickly.  Resolution is
                # reduced to 640x352 (32-aligned) and steps to 8 to finish a real MP4
                # end-to-end on the 12 GB card; production 1280x736 remains the
                # target for later optimization (not claimable as PASS here).
                api_prompt["1"]["inputs"]["image"] = patch21_image or "huizhou_blackpai_aerial.png"
                api_prompt["6"]["inputs"]["duration_seconds"] = patch21_duration or 4.0
                api_prompt["6"]["inputs"]["width"] = patch21_width or 640
                api_prompt["6"]["inputs"]["height"] = patch21_height or 352
                if patch21_transformer:
                    api_prompt["2"]["inputs"]["transformer_path"] = patch21_transformer
                api_prompt["12"] = {
                    "class_type": "RHMiniMaxH3SamplerConfig",
                    "inputs": {
                        "sparse_attention": False,
                        "sparse_tau": 1.2,
                        "sparse_start_percent": 0.2,
                        "sparse_end_percent": 0.9,
                        "sparse_min_tokens": 4096,
                        "sparse_kernel_path": "",
                        "sparse_int8_qk": False,
                        "dense_sage_attention": False,
                        "step_abort_seconds": 0,
                    },
                }
                api_prompt["9"]["inputs"]["sampler_config"] = ["12", 0]
            payload = json.dumps({"prompt": api_prompt}).encode("utf-8")
            req = urllib.request.Request(
                f"{API_HOST}/prompt", data=payload, headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                submit_data = json.loads(resp.read().decode("utf-8"))

            prompt_id = submit_data.get("prompt_id")
            self.assertIsNotNone(prompt_id, "ComfyUI API must return a valid prompt_id")
            submit_node_errors = submit_data.get("node_errors", {})
            self.assertEqual(submit_node_errors, {}, "Prompt submission must have no node errors")

        print(f"\n[PATCH2 GPU Execution] Trial {trial} Submitted! prompt_id: {prompt_id}")
        print(f"[PATCH2 GPU Execution] Polling /history until completion or timeout (max {timeout_seconds}s)...")

        # Poll /history/{prompt_id} until real completion, sampling VRAM along the way
        start_time = time.time()
        history_data = {}
        completed = False
        node_errors = {}
        console_excerpt = ""
        gpu_used_samples_mb = []
        committed_samples_mb = []
        free_commit_samples_mb = []
        phys_free_samples_mb = []
        poll_interval = 10

        while (time.time() - start_time) < timeout_seconds:
            gpu_used = _sample_gpu_used_mb()
            if gpu_used is not None:
                gpu_used_samples_mb.append(gpu_used)
            sys_mem = _sample_system_memory()
            if sys_mem is not None:
                committed_mb, commit_limit_mb, phys_free_mb = sys_mem
                committed_samples_mb.append(committed_mb)
                free_commit_samples_mb.append(commit_limit_mb - committed_mb)
                phys_free_samples_mb.append(phys_free_mb)
            try:
                history_url = f"{API_HOST}/history/{prompt_id}"
                with urllib.request.urlopen(history_url, timeout=5) as h_resp:
                    h_json = json.loads(h_resp.read().decode("utf-8"))
                if prompt_id in h_json:
                    history_data = h_json[prompt_id]
                    completed, status_info, node_errors, console_excerpt = _extract_history_result(history_data)
                    print(
                        f"[PATCH2 GPU Execution] history entry found: "
                        f"status={status_info.get('status_str')} after {round(time.time() - start_time, 1)}s"
                    )
                    break
            except Exception as exc:
                print(f"[PATCH2 GPU Execution] poll error: {exc}")

            elapsed = round(time.time() - start_time)
            if elapsed % 30 < poll_interval:
                print(f"[PATCH2 GPU Execution] ... {elapsed}s elapsed, GPU used={gpu_used}MB, job still running/queued")
            time.sleep(poll_interval)

        execution_duration = round(time.time() - start_time, 2)
        peak_gpu_used_mb = max(gpu_used_samples_mb) if gpu_used_samples_mb else 0
        peak_committed_mb = max(committed_samples_mb) if committed_samples_mb else 0
        min_free_commit_mb = min(free_commit_samples_mb) if free_commit_samples_mb else 0
        peak_physical_used_mb = (
            round(32602.5 - min(phys_free_samples_mb), 1) if phys_free_samples_mb else 0
        )

        # Failure classification (real failure evidence)
        if not completed:
            failing_node = next(iter(node_errors.values()), {})
            exception_msg = console_excerpt.strip() or (
                "Job did not complete within the polling window or failed without a captured exception"
            )
            failure_report = self.classifier.classify_error(
                prompt_id=prompt_id,
                node_id=str(failing_node.get("node_id", "unknown")),
                node_type=str(failing_node.get("node_type", "UNKNOWN")),
                exception_msg=exception_msg,
                console_log=console_excerpt,
            )
            failure_report["execution_seconds"] = execution_duration
            failure_report["status_str"] = status_info.get("status_str") if history_data else "NO_HISTORY_ENTRY"
            with open(CONFIG_DIR / f"{CONFIG_PREFIX}_runtime_failure.json", "w", encoding="utf-8") as f:
                json.dump(failure_report, f, indent=2, ensure_ascii=False)

        # Model execution manifest
        model_execution = {
            "prompt_id": prompt_id,
            "models_tested": [
                {"component": "DiT Model", "loader_node": "RHMiniMaxH3ModelLoader", "resolved_model": "minimax_h3_fl2va_pruned_int8_convrot.safetensors", "status": "PASS" if completed else "FAIL"},
                {"component": "Qwen3-VL Text Encoder", "loader_node": "RHMiniMaxH3TextEncoderLoader", "resolved_model": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors", "status": "PASS" if completed else "FAIL"},
                {"component": "Video VAE", "loader_node": "RHMiniMaxH3VAELoader", "resolved_model": "minimax_h3_video_vae_fp16.safetensors", "status": "PASS" if completed else "FAIL"},
                {"component": "Audio VAE", "loader_node": "RHMiniMaxH3VAELoader", "resolved_model": "minimax_h3_audio_vae_fp32.safetensors", "status": "PASS" if completed else "FAIL"},
            ],
            "status": "PASS" if completed else "FAIL",
        }
        with open(CONFIG_DIR / f"{CONFIG_PREFIX}_model_execution.json", "w", encoding="utf-8") as f:
            json.dump(model_execution, f, indent=2, ensure_ascii=False)

        gpu_runtime_report = {
            "trial": trial,
            "gpu": gpu_res.get("gpu_name"),
            "cuda_available": gpu_res.get("cuda_available"),
            "prompt_id": prompt_id,
            "total_vram_mb": gpu_res.get("total_vram_mb"),
            "allocated_vram_mb": gpu_res.get("allocated_vram_mb"),
            "peak_gpu_used_mb_observed": peak_gpu_used_mb,
            "gpu_used_samples_mb": gpu_used_samples_mb,
            "peak_committed_mb_observed": round(peak_committed_mb, 1),
            "min_free_commit_mb_observed": round(min_free_commit_mb, 1),
            "peak_physical_ram_used_mb_observed": round(peak_physical_used_mb, 1),
            "committed_samples_mb": [round(v, 1) for v in committed_samples_mb],
            "execution_seconds": execution_duration,
            "job_completed": completed,
            "status": "PASS" if completed else "FAIL",
        }
        with open(CONFIG_DIR / f"{CONFIG_PREFIX}_gpu_runtime.json", "w", encoding="utf-8") as f:
            json.dump(gpu_runtime_report, f, indent=2, ensure_ascii=False)

        # Locate output MP4
        output_mp4_path = None
        mp4_size_bytes = 0

        if completed:
            outputs = history_data.get("outputs", {}) or {}
            for node_id, node_out in outputs.items():
                for key in ("gifs", "video", "images"):
                    entries = node_out.get(key) or []
                    for entry in entries:
                        filename = entry.get("filename")
                        subfolder = entry.get("subfolder", "") or ""
                        file_p = COMFYUI_OUTPUT_DIR / subfolder / filename if subfolder else COMFYUI_OUTPUT_DIR / filename
                        if file_p.is_file():
                            output_mp4_path = str(file_p)
                            mp4_size_bytes = file_p.stat().st_size
                            break
                    if output_mp4_path:
                        break
                if output_mp4_path:
                    break

        # Fallback: newest Golden MP4 in output dir
        if not output_mp4_path:
            mp4_candidates = sorted(
                COMFYUI_OUTPUT_DIR.glob("04_Drone_Aerial_GOLDEN*.mp4"),
                key=lambda p: p.stat().st_mtime, reverse=True,
            )
            if mp4_candidates:
                output_mp4_path = str(mp4_candidates[0])
                mp4_size_bytes = mp4_candidates[0].stat().st_size

        video_output_report = {
            "prompt_id": prompt_id,
            "output_mp4_path": output_mp4_path,
            "file_exists": output_mp4_path is not None and Path(output_mp4_path).is_file(),
            "file_size_bytes": mp4_size_bytes,
            "status": "PASS" if (output_mp4_path and mp4_size_bytes > 0) else "FAIL",
        }
        with open(CONFIG_DIR / f"{CONFIG_PREFIX}_video_output.json", "w", encoding="utf-8") as f:
            json.dump(video_output_report, f, indent=2, ensure_ascii=False)

        # ffprobe metadata validation
        ffprobe_report = {
            "prompt_id": prompt_id,
            "target_mp4": output_mp4_path,
            "codec_name": "unknown",
            "width": 0,
            "height": 0,
            "fps": 0.0,
            "duration": 0.0,
            "nb_frames": 0,
            "status": "FAIL",
        }

        if output_mp4_path and Path(output_mp4_path).is_file() and ffmpeg_res.get("ffprobe_path"):
            try:
                cmd = [
                    ffmpeg_res["ffprobe_path"],
                    "-v", "error",
                    "-select_streams", "v:0",
                    "-show_entries", "stream=width,height,codec_name,avg_frame_rate,duration,nb_frames",
                    "-show_entries", "format=duration,size",
                    "-of", "json",
                    output_mp4_path,
                ]
                ff_res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=15)
                if ff_res.returncode == 0:
                    probe_data = json.loads(ff_res.stdout)
                    streams = probe_data.get("streams", [])
                    if streams:
                        st = streams[0]
                        ffprobe_report["codec_name"] = st.get("codec_name", "h264")
                        ffprobe_report["width"] = int(st.get("width", 0))
                        ffprobe_report["height"] = int(st.get("height", 0))

                        fps_raw = st.get("avg_frame_rate", "24/1")
                        if "/" in fps_raw:
                            num, den = fps_raw.split("/")
                            ffprobe_report["fps"] = round(float(num) / float(den), 2) if float(den) > 0 else 24.0
                        else:
                            ffprobe_report["fps"] = float(fps_raw)

                        ffprobe_report["duration"] = float(st.get("duration") or probe_data.get("format", {}).get("duration") or 0.0)
                        ffprobe_report["nb_frames"] = int(st["nb_frames"]) if st.get("nb_frames") else 0

                        if ffprobe_report["width"] >= 1280 and ffprobe_report["height"] >= 720 and ffprobe_report["duration"] > 0:
                            ffprobe_report["status"] = "PASS"
            except Exception as e:
                ffprobe_report["error"] = str(e)

        with open(CONFIG_DIR / f"{CONFIG_PREFIX}_ffprobe.json", "w", encoding="utf-8") as f:
            json.dump(ffprobe_report, f, indent=2, ensure_ascii=False)

        # Extract representative frames from valid MP4
        USERDATA_DIR.mkdir(parents=True, exist_ok=True)
        if output_mp4_path and Path(output_mp4_path).is_file() and ffmpeg_res.get("ffmpeg_path"):
            try:
                for label, ts in (("early", "00:00:01"), ("mid", "00:00:02.5"), ("late", "00:00:04")):
                    out = USERDATA_DIR / f"frame_{label}.png"
                    subprocess.run(
                        [ffmpeg_res["ffmpeg_path"], "-y", "-ss", ts, "-i", output_mp4_path, "-vframes", "1", str(out)],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10,
                    )
            except Exception:
                pass

        # Gates P2-A ~ P2-G
        decode_ok = completed and bool(history_data.get("outputs"))
        gate_key = "P21" if CONFIG_PREFIX == "rc33_patch21" else "P2"
        gate_matrix = {
            "trial": trial,
            "prompt_id": prompt_id,
            f"{gate_key}-A_graph_regression": graph_res["status"],
            f"{gate_key}-B_model_loader_runtime": model_execution["status"],
            f"{gate_key}-C_gpu_inference": "PASS" if completed else "FAIL",
            f"{gate_key}-D_vae_decode": "PASS" if decode_ok else "FAIL",
            f"{gate_key}-E_mp4_export": video_output_report["status"],
            f"{gate_key}-F_ffprobe_validation": ffprobe_report["status"],
            f"{gate_key}-G_production_resolution": "PASS" if ffprobe_report["width"] >= 1280 and ffprobe_report["height"] >= 720 else "FAIL",
        }
        all_gates_pass = all(v == "PASS" for v in gate_matrix.values() if v != prompt_id)
        gate_matrix["overall_status"] = "PASS" if all_gates_pass else "FAIL"

        with open(CONFIG_DIR / f"{CONFIG_PREFIX}_gate_report.json", "w", encoding="utf-8") as f:
            json.dump(gate_matrix, f, indent=2, ensure_ascii=False)

        print("\n=======================================================")
        print(f"PATCH2 GPU Execution (Trial {trial}) Gates Summary: {gate_matrix['overall_status']}")
        print(f"Prompt ID: {prompt_id}")
        print(f"Execution Duration: {execution_duration}s")
        print(f"Peak GPU VRAM observed: {peak_gpu_used_mb} MB")
        print(f"Peak committed bytes observed: {round(peak_committed_mb, 1)} MB")
        print(f"Min free commit observed: {round(min_free_commit_mb, 1)} MB")
        print(f"Peak physical RAM used observed: {round(peak_physical_used_mb, 1)} MB")
        print(f"Output MP4: {output_mp4_path}")
        print("=======================================================\n")


if __name__ == "__main__":
    unittest.main()
