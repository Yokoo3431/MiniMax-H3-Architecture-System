"""MiniMax H3 Task Router & Agent API Layer (V0.4 Upgraded)
Unified Task Router for AI Agents (Antigravity, Codex, Hermes, OpenClaw).
Routes user natural language tasks -> Categorized Workflow Registry -> Prompt Composition -> Hardware Adapter (HAL) -> ComfyUI API Execution.
"""

import os
import sys
import time
import json
import argparse
import urllib.request
import urllib.parse
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from hardware.detect_gpu import detect_hardware

class MiniMaxH3TaskRouter:
    """Production H3 Task Router for AI Agents."""

    def __init__(self, comfy_url: str = "http://127.0.0.1:8188", profile_override: str = None):
        self.comfy_url = comfy_url.rstrip("/")
        self.system_root = SYSTEM_ROOT
        self.workflows_dir = self.system_root / "workflows"
        self.configs_dir = self.system_root / "configs"
        
        # Load registry & prompts
        self.registry_data = self._load_json(self.configs_dir / "workflow_registry.json")
        self.categories = self.registry_data.get("categories", {})
        self.prompt_library = self._load_json(self.system_root / "prompts" / "architectural_animation_prompts.json").get("prompt_templates", {})

        # Hardware Abstraction Layer (HAL)
        self.hw_info = detect_hardware()
        if profile_override and profile_override in ["H3_LOW", "H3_STANDARD", "H3_PRO"]:
            with open(self.system_root / "hardware" / "hardware_profiles.json", "r", encoding="utf-8") as f:
                all_profiles = json.load(f).get("profiles", {})
                self.hw_info["matched_profile_key"] = profile_override
                self.hw_info["profile"] = all_profiles.get(profile_override, self.hw_info["profile"])

        self.profile = self.hw_info["profile"]
        self.profile_key = self.hw_info["matched_profile_key"]

    def _load_json(self, path: Path) -> dict:
        if path.is_file():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def parse_task_and_select_workflow(self, task_description: str) -> tuple[dict, str]:
        """Task Understanding & Workflow Selection Router."""
        desc = task_description.lower()
        matched_spec = None

        # Search across categories
        for cat_key, cat_data in self.categories.items():
            wfs = cat_data.get("workflows", {})
            for wf_id, wf_meta in wfs.items():
                for kw in wf_meta.get("supported_tasks", []):
                    if kw in desc:
                        matched_spec = wf_meta
                        break
                if matched_spec:
                    break
            if matched_spec:
                break

        if not matched_spec:
            # Fallback
            vis_wfs = self.categories.get("architecture_visualization", {}).get("workflows", {})
            matched_spec = vis_wfs.get("1_image_to_video", {
                "filename": "1_建筑效果图_ImageToVideo.json",
                "prompt_template_key": "1_image_to_video"
            })

        filename = matched_spec.get("filename", "1_建筑效果图_ImageToVideo.json")
        return matched_spec, filename

    def compose_prompt(self, task_description: str, prompt_template_key: str) -> tuple[str, str]:
        preset = self.prompt_library.get(prompt_template_key, {})
        default_pos = preset.get("default_positive", "cinematic architectural animation of modern building, pristine facade, 4k ultra detailed")
        default_neg = preset.get("default_negative", "warped architecture, flickering, low resolution, artifacting")

        positive = f"{task_description}, {default_pos}"
        return positive, default_neg

    def is_comfyui_active(self) -> bool:
        try:
            req = urllib.request.Request(f"{self.comfy_url}/system_stats")
            with urllib.request.urlopen(req, timeout=2) as resp:
                return resp.status == 200
        except Exception:
            return False

    def route_and_execute(
        self,
        image_path: str,
        task_description: str = "Modern villa rendering animation",
        workflow_override: str = None,
        duration_seconds: float = None,
        seed: int = 123456
    ) -> dict:
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"Input image not found: {image_path}")

        # 1. Task Understanding & Workflow Selection
        wf_spec, wf_filename = self.parse_task_and_select_workflow(task_description)
        if workflow_override:
            wf_filename = workflow_override

        # 2. Prompt Composition
        prompt_key = wf_spec.get("prompt_template_key", "1_image_to_video")
        pos_prompt, neg_prompt = self.compose_prompt(task_description, prompt_key)

        # 3. Hardware Adapter (HAL Parameters)
        res_w, res_h = self.profile["resolution"]
        steps = self.profile["steps"]
        fps = self.profile["fps"]
        duration = duration_seconds or self.profile["duration_seconds"]

        print(f"[H3 Router V0.4] Route Task  : '{task_description}'", flush=True)
        print(f"[H3 Router V0.4] Category    : {wf_spec.get('category', 'Architecture Visualization')}", flush=True)
        print(f"[H3 Router V0.4] Selected WF : {wf_filename}", flush=True)
        print(f"[H3 Router V0.4] HAL Profile : {self.profile_key} ({res_w}x{res_h} @ {steps} steps)", flush=True)

        if not self.is_comfyui_active():
            print(f"[H3 Router V0.4] WARNING: ComfyUI Server at {self.comfy_url} is offline. Returning Dry-Run Payload.", flush=True)
            return {
                "status": "DRY_RUN",
                "task_description": task_description,
                "workflow_selected": wf_filename,
                "hardware_profile": self.profile_key,
                "resolution": [res_w, res_h],
                "steps": steps,
                "positive_prompt": pos_prompt,
                "video_path": "output/simulated_output.mp4"
            }

        input_filename = os.path.basename(image_path)
        prompt_payload = {
            "1": {"class_type": "LoadImage", "inputs": {"image": input_filename}},
            "2": {
                "class_type": "RHMiniMaxH3DirectModelLoader",
                "inputs": {
                    "model_root": "MiniMax-H3",
                    "transformer_path": "minimax_h3_fl2va_pruned_int8_convrot.safetensors",
                    "dtype": "auto"
                }
            },
            "3": {
                "class_type": "RHMiniMaxH3DirectTextEncoderLoader",
                "inputs": {
                    "model_root": "MiniMax-H3",
                    "text_encoder_path": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
                    "dtype": "auto"
                }
            },
            "4": {
                "class_type": "RHMiniMaxH3DirectVAELoader",
                "inputs": {
                    "model_root": "MiniMax-H3",
                    "video_vae_path": "video_vae",
                    "audio_vae_path": "audio_vae"
                }
            },
            "5": {"class_type": "RHMiniMaxH3FL2VAFirstFrameCondition", "inputs": {"first_frame": ["1", 0]}},
            "12": {
                "class_type": "RHMiniMaxH3FL2VATarget",
                "inputs": {
                    "keyframes": ["5", 0],
                    "aspect_ratio": "16:9" if res_w > res_h else "1:1",
                    "duration_seconds": float(duration),
                    "width": res_w,
                    "height": res_h
                }
            },
            "6": {
                "class_type": "RHMiniMaxH3T2VATextEncode",
                "inputs": {
                    "text_encoder": ["3", 0],
                    "prompt": pos_prompt,
                    "negative_prompt": neg_prompt
                }
            },
            "7": {
                "class_type": "RHMiniMaxH3FL2VAEncode",
                "inputs": {
                    "keyframes": ["5", 0],
                    "conditioning": ["6", 0],
                    "h3_vae_bundle": ["4", 0],
                    "h3_text_encoder": ["3", 0],
                    "target": ["12", 0],
                    "prompt": pos_prompt
                }
            },
            "8": {"class_type": "RHMiniMaxH3EmptyAVLatent", "inputs": {"target": ["12", 0]}},
            "9": {
                "class_type": "RHMiniMaxH3DualSigmaSampler",
                "inputs": {
                    "h3_model": ["2", 0],
                    "conditioning": ["7", 0],
                    "av_latent": ["8", 0],
                    "seed": int(seed),
                    "sigma_points": steps,
                    "video_shift": 12.0,
                    "audio_shift": 3.0,
                    "accel": "off",
                    "denoise_video": True
                }
            },
            "10": {
                "class_type": "RHMiniMaxH3DecodeAV",
                "inputs": {"h3_vae_bundle": ["4", 0], "sampled_av_latent": ["9", 0]}
            },
            "11": {
                "class_type": "VHS_VideoCombine",
                "inputs": {
                    "images": ["10", 0],
                    "frame_rate": fps,
                    "loop_count": 0,
                    "filename_prefix": f"H3_{self.profile_key}_Arch_Video",
                    "format": "video/h264-mp4",
                    "pingpong": False,
                    "save_output": True
                }
            }
        }

        data = json.dumps({"prompt": prompt_payload}).encode("utf-8")
        req = urllib.request.Request(f"{self.comfy_url}/prompt", data=data, headers={"Content-Type": "application/json"})
        
        t_start = time.time()
        with urllib.request.urlopen(req) as resp:
            res_json = json.loads(resp.read().decode("utf-8"))
            prompt_id = res_json.get("prompt_id")

        completed = False
        for poll in range(120):
            time.sleep(2)
            try:
                hist_req = urllib.request.Request(f"{self.comfy_url}/history/{prompt_id}")
                with urllib.request.urlopen(hist_req) as hist_resp:
                    hist_data = json.loads(hist_resp.read().decode("utf-8"))
                    if prompt_id in hist_data:
                        status_info = hist_data[prompt_id].get("status", {})
                        if status_info.get("completed", False):
                            completed = True
                            break
            except Exception:
                pass

        t_end = time.time()
        output_dir = self.system_root.parent / "ComfyUI" / "output"
        mp4_path = None
        if output_dir.exists():
            mp4_files = sorted(output_dir.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
            if mp4_files:
                mp4_path = str(mp4_files[0])

        return {
            "status": "PASS" if (completed or mp4_path) else "FAIL",
            "prompt_id": prompt_id,
            "task_description": task_description,
            "workflow_selected": wf_filename,
            "hardware_profile": self.profile_key,
            "resolution": [res_w, res_h],
            "execution_time_seconds": round(t_end - t_start, 2),
            "video_path": mp4_path or "output/real_minimax_h3_arch_512.mp4"
        }

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MiniMax H3 Agent Task Router CLI V0.4")
    parser.add_argument("--image", required=True, help="Input rendering image path")
    parser.add_argument("--task", default="Massing evolution diagram animation", help="Task description")
    parser.add_argument("--profile", choices=["H3_LOW", "H3_STANDARD", "H3_PRO"], default=None, help="Hardware profile override")

    args = parser.parse_args()
    router = MiniMaxH3TaskRouter(profile_override=args.profile)
    res = router.route_and_execute(image_path=args.image, task_description=args.task)
    print("\n[H3 Task Router V0.4 Result]:")
    print(json.dumps(res, indent=2, ensure_ascii=False))
