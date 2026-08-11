"""MiniMax H3 Orchestrator (V0.5 Agent Runtime Main Engine)
Orchestrates TaskPlanner -> WorkflowSelector -> PromptComposer -> HardwareAdapter -> ComfyExecutor.
"""

import os
import sys
import json
import argparse
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from runtime.task_planner import TaskPlanner
from runtime.workflow_selector import WorkflowSelector
from runtime.prompt_composer import PromptComposer
from runtime.hardware_adapter import HardwareAdapter
from runtime.comfy_executor import ComfyExecutor

class H3Orchestrator:
    """Main Agent Orchestrator for MiniMax H3 Architecture System."""

    def __init__(self, comfy_url: str = "http://127.0.0.1:8188", profile_override: str = None):
        self.system_root = SYSTEM_ROOT
        self.planner = TaskPlanner()
        self.selector = WorkflowSelector(self.system_root / "configs" / "workflow_registry.json")
        self.composer = PromptComposer(self.system_root / "prompts" / "architectural_animation_prompts.json")
        self.adapter = HardwareAdapter(profile_override=profile_override)
        self.executor = ComfyExecutor(comfy_url=comfy_url)
        self.output_dir = self.system_root / "userdata" / "outputs"
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def process_agent_request(
        self,
        image_path: str,
        task_description: str = "Architectural villa animation",
        workflow_override: str = None,
        duration_override: float = None,
        seed: int = 123456
    ) -> dict:
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"Input rendering image not found: {image_path}")

        # 1. Intent Task Planning
        plan = self.planner.plan_task(task_description)

        # 2. Workflow Selection
        wf_spec, wf_filename = self.selector.select_workflow(plan)
        if workflow_override:
            wf_filename = workflow_override

        # 3. Prompt Composition
        prompt_key = wf_spec.get("prompt_template_key", "1_image_to_video")
        pos_prompt, neg_prompt = self.composer.compose_prompt(task_description, prompt_key)

        # 4. Hardware Adaptation
        hw_params = self.adapter.adapt_parameters(duration_override=duration_override)

        print(f"[H3 Orchestrator V0.5] Processing Task : '{task_description}'", flush=True)
        print(f"[H3 Orchestrator V0.5] Selected WF   : {wf_filename}", flush=True)
        print(f"[H3 Orchestrator V0.5] HAL Profile   : {hw_params['profile_key']} ({hw_params['width']}x{hw_params['height']})", flush=True)

        # 5. Payload Construction
        input_filename = os.path.basename(image_path)
        payload = {
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
                    "aspect_ratio": "16:9" if hw_params["width"] > hw_params["height"] else "1:1",
                    "duration_seconds": float(hw_params["duration_seconds"]),
                    "width": hw_params["width"],
                    "height": hw_params["height"]
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
                    "sigma_points": hw_params["steps"],
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
                    "frame_rate": hw_params["fps"],
                    "loop_count": 0,
                    "filename_prefix": f"H3_V0.5_{hw_params['profile_key']}_Video",
                    "format": "video/h264-mp4",
                    "pingpong": False,
                    "save_output": True
                }
            }
        }

        # 6. ComfyUI Execution Backend
        res = self.executor.execute_payload(payload, self.system_root.parent / "ComfyUI" / "output")
        res["task_description"] = task_description
        res["workflow_selected"] = wf_filename
        res["hardware_profile"] = hw_params["profile_key"]
        return res

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MiniMax H3 Orchestrator CLI V0.5")
    parser.add_argument("--image", required=True, help="Input rendering image path")
    parser.add_argument("--task", default="Massing evolution diagram animation", help="Task description")
    parser.add_argument("--profile", choices=["H3_LOW", "H3_STANDARD", "H3_PRO"], default=None, help="Hardware profile override")

    args = parser.parse_args()
    orchestrator = H3Orchestrator(profile_override=args.profile)
    res = orchestrator.process_agent_request(image_path=args.image, task_description=args.task)
    print("\n[H3 Orchestrator V0.5 Result]:")
    print(json.dumps(res, indent=2, ensure_ascii=False))
