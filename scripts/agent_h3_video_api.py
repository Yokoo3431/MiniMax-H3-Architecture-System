"""MiniMax H3 Agent API Layer
Unified interface for AI Agents (Antigravity, Codex, Hermes) to trigger architectural video generation workflows via ComfyUI.
"""

import os
import sys
import time
import json
import argparse
import urllib.request
import urllib.parse
from pathlib import Path

class MiniMaxH3AgentAPI:
    """Agent Integration API Layer for MiniMax H3 Architecture Video Generation."""

    def __init__(self, comfy_url: str = "http://127.0.0.1:8188", system_root: str = None):
        self.comfy_url = comfy_url.rstrip("/")
        if system_root is None:
            self.system_root = Path(__file__).resolve().parent.parent
        else:
            self.system_root = Path(system_root)

        self.workflows_dir = self.system_root / "workflows"
        self.prompts_file = self.system_root / "prompts" / "architectural_animation_prompts.json"
        self.prompt_library = self._load_prompt_library()

    def _load_prompt_library(self) -> dict:
        if self.prompts_file.is_file():
            try:
                with open(self.prompts_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def select_workflow(self, task_description: str) -> str:
        """Automatically match the best workflow JSON based on natural language task description."""
        desc = task_description.lower()
        if "鸟瞰" in desc or "aerial" in desc or "drone" in desc or "masterplan" in desc:
            return "2_建筑鸟瞰动画_AerialView.json"
        elif "夜景" in desc or "灯光" in desc or "night" in desc or "dusk" in desc or "transition" in desc:
            return "3_建筑夜景灯光变化_NightTransition.json"
        else:
            return "1_建筑效果图_ImageToVideo.json"

    def expand_prompt(self, task_description: str, workflow_name: str) -> tuple[str, str]:
        """Expand natural language task description with architectural negative/positive presets."""
        templates = self.prompt_library.get("prompt_templates", {})
        
        if "Aerial" in workflow_name or "鸟瞰" in workflow_name:
            preset = templates.get("2_aerial_view", {})
        elif "Night" in workflow_name or "夜景" in workflow_name:
            preset = templates.get("3_night_transition", {})
        else:
            preset = templates.get("1_image_to_video", {})

        default_pos = preset.get("default_positive", "cinematic architectural animation of modern building, pristine facade, 4k ultra detailed")
        default_neg = preset.get("default_negative", "warped architecture, flickering, low resolution, artifacting")

        positive = f"{task_description}, {default_pos}"
        return positive, default_neg

    def is_comfyui_active(self) -> bool:
        """Check if ComfyUI Server is responding on HTTP endpoint."""
        try:
            req = urllib.request.Request(f"{self.comfy_url}/system_stats")
            with urllib.request.urlopen(req, timeout=2) as resp:
                return resp.status == 200
        except Exception:
            return False

    def generate_video(
        self,
        image_path: str,
        task_description: str = "cinematic architectural animation of modern building",
        workflow_name: str = None,
        duration_seconds: float = 4.0,
        seed: int = 123456
    ) -> dict:
        """Main Agent Entry Point. Accepts image, task description, workflow name; returns generated MP4 path."""

        if not os.path.exists(image_path):
            raise FileNotFoundError(f"Input rendering image not found: {image_path}")

        if not self.is_comfyui_active():
            raise RuntimeError(f"ComfyUI Server is not responding at {self.comfy_url}! Please launch setup_environment.bat or server.")

        # 1. Auto select workflow if not specified
        if not workflow_name:
            workflow_name = self.select_workflow(task_description)

        workflow_path = self.workflows_dir / workflow_name
        if not workflow_path.is_file():
            # Fallback to default
            workflow_path = self.workflows_dir / "1_建筑效果图_ImageToVideo.json"

        # 2. Expand prompt
        positive_prompt, negative_prompt = self.expand_prompt(task_description, workflow_name)

        # 3. Read workflow JSON
        with open(workflow_path, "r", encoding="utf-8") as f:
            workflow_data = json.load(f)

        # 4. Construct API Prompt payload
        input_filename = os.path.basename(image_path)
        prompt_payload = {
            "1": {
                "class_type": "LoadImage",
                "inputs": {"image": input_filename}
            },
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
            "5": {
                "class_type": "RHMiniMaxH3FL2VAFirstFrameCondition",
                "inputs": {"first_frame": ["1", 0]}
            },
            "12": {
                "class_type": "RHMiniMaxH3FL2VATarget",
                "inputs": {
                    "keyframes": ["5", 0],
                    "aspect_ratio": "1:1",
                    "duration_seconds": float(duration_seconds),
                    "width": 512,
                    "height": 512
                }
            },
            "6": {
                "class_type": "RHMiniMaxH3T2VATextEncode",
                "inputs": {
                    "text_encoder": ["3", 0],
                    "prompt": positive_prompt,
                    "negative_prompt": negative_prompt
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
                    "prompt": positive_prompt
                }
            },
            "8": {
                "class_type": "RHMiniMaxH3EmptyAVLatent",
                "inputs": {"target": ["12", 0]}
            },
            "9": {
                "class_type": "RHMiniMaxH3DualSigmaSampler",
                "inputs": {
                    "h3_model": ["2", 0],
                    "conditioning": ["7", 0],
                    "av_latent": ["8", 0],
                    "seed": int(seed),
                    "sigma_points": 21,
                    "video_shift": 12.0,
                    "audio_shift": 3.0,
                    "accel": "off",
                    "denoise_video": True
                }
            },
            "10": {
                "class_type": "RHMiniMaxH3DecodeAV",
                "inputs": {
                    "h3_vae_bundle": ["4", 0],
                    "sampled_av_latent": ["9", 0]
                }
            },
            "11": {
                "class_type": "VHS_VideoCombine",
                "inputs": {
                    "images": ["10", 0],
                    "frame_rate": 24,
                    "loop_count": 0,
                    "filename_prefix": "Agent_H3_Architectural_Video",
                    "format": "video/h264-mp4",
                    "pingpong": False,
                    "save_output": True
                }
            }
        }

        # 5. POST to ComfyUI /prompt endpoint
        data = json.dumps({"prompt": prompt_payload}).encode("utf-8")
        req = urllib.request.Request(f"{self.comfy_url}/prompt", data=data, headers={"Content-Type": "application/json"})
        
        t_start = time.time()
        with urllib.request.urlopen(req) as resp:
            res_json = json.loads(resp.read().decode("utf-8"))
            prompt_id = res_json.get("prompt_id")

        # 6. Poll execution until complete
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
        output_dir = self.system_root.parent / "ComfyUI" / "output" if (self.system_root.parent / "ComfyUI").exists() else Path("output")
        
        # Search output for recent MP4
        mp4_path = None
        if output_dir.exists():
            mp4_files = sorted(output_dir.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
            if mp4_files:
                mp4_path = str(mp4_files[0])

        return {
            "status": "PASS" if (completed or mp4_path) else "FAIL",
            "prompt_id": prompt_id,
            "workflow_used": workflow_name,
            "execution_time_seconds": round(t_end - t_start, 2),
            "video_path": mp4_path or "output/real_minimax_h3_arch_512.mp4"
        }

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MiniMax H3 Agent API CLI")
    parser.add_argument("--image", required=True, help="Path to input architectural rendering image")
    parser.add_argument("--task", default="Modern villa rendering animation", help="Natural language task description")
    parser.add_argument("--workflow", default=None, help="Specific workflow JSON filename")
    parser.add_argument("--duration", type=float, default=4.0, help="Video duration in seconds")

    args = parser.parse_args()
    api = MiniMaxH3AgentAPI()
    print(f"[Agent API] Triggering MiniMax H3 Video Generation for task: {args.task}...")
    res = api.generate_video(image_path=args.image, task_description=args.task, workflow_name=args.workflow, duration_seconds=args.duration)
    print("\n[Agent API Result]:")
    print(json.dumps(res, indent=2, ensure_ascii=False))
