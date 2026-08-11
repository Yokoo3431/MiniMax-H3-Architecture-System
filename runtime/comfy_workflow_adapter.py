"""ComfyUI Workflow Parameter Adapter Engine (V0.7.2).
Injects generated positive/negative prompts, image inputs, and hardware profiles into ComfyUI payload.
"""

import os
import json
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent

class ComfyWorkflowAdapter:
    """Adapts ComfyUI JSON payload with generated prompts, inputs, and HAL hardware profiles."""

    def prepare_execution_payload(
        self,
        image_path: str,
        positive_prompt: str,
        negative_prompt: str,
        hw_params: dict,
        seed: int = 123456
    ) -> dict:
        input_filename = os.path.basename(image_path)
        return {
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
                    "aspect_ratio": "16:9" if hw_params.get("width", 1280) > hw_params.get("height", 720) else "1:1",
                    "duration_seconds": float(hw_params.get("duration_seconds", 5.0)),
                    "width": hw_params.get("width", 1280),
                    "height": hw_params.get("height", 720)
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
            "8": {"class_type": "RHMiniMaxH3EmptyAVLatent", "inputs": {"target": ["12", 0]}},
            "9": {
                "class_type": "RHMiniMaxH3DualSigmaSampler",
                "inputs": {
                    "h3_model": ["2", 0],
                    "conditioning": ["7", 0],
                    "av_latent": ["8", 0],
                    "seed": int(seed),
                    "sigma_points": hw_params.get("steps", 25),
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
                    "frame_rate": hw_params.get("fps", 24),
                    "loop_count": 0,
                    "filename_prefix": f"H3_V0.7.2_{hw_params.get('profile_key', 'H3_STANDARD')}_Video",
                    "format": "video/h264-mp4",
                    "pingpong": False,
                    "save_output": True
                }
            }
        }
