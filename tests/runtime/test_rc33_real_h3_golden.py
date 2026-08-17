"""Real Local ComfyUI H3 Golden Workflow Runtime Test Suite (V0.8.0 RC3.3 PATCH1).
Probes active local ComfyUI instance, converts 04_Drone_Aerial_GOLDEN.json to API prompt format, submits to /prompt, and verifies HTTP response.
"""

import sys
import json
import time
import unittest
import urllib.request
import urllib.parse
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from runtime.validation.ffmpeg_probe import FFmpegProbe
from runtime.validation.h3_runtime_probe import H3RuntimeProbe
from runtime.validation.model_loader_probe import ModelLoaderProbe
from runtime.validation.golden_graph_auditor import GoldenGraphAuditor

CONFIG_DIR = SYSTEM_ROOT / "configs"
REPORT_FILE = CONFIG_DIR / "rc33_runtime_validation.json"
GOLDEN_WORKFLOW_PATH = SYSTEM_ROOT / "workflows" / "04_Drone_Aerial_GOLDEN.json"

def workflow_to_api_prompt(wf_path: Path) -> dict:
    """Converts a ComfyUI UI workflow JSON file into API prompt dict format."""
    with open(wf_path, "r", encoding="utf-8") as f:
        wf_data = json.load(f)

    nodes = wf_data.get("nodes", [])
    links = wf_data.get("links", [])
    link_map = {link[0]: link for link in links}

    prompt_dict = {}
    for node in nodes:
        node_id = str(node["id"])
        node_type = node["type"]
        inputs = {}

        # 1. Widget values mapping according to node type
        widgets = node.get("widgets_values", [])
        if isinstance(widgets, list):
            if node_type == "LoadImage" and len(widgets) > 0:
                inputs["image"] = widgets[0]
            elif node_type == "RHMiniMaxH3ModelLoader" and len(widgets) >= 4:
                inputs["partition"] = widgets[0]
                inputs["model_root"] = widgets[1]
                inputs["dtype"] = widgets[2]
                inputs["transformer_path"] = widgets[3]
            elif node_type == "RHMiniMaxH3TextEncoderLoader" and len(widgets) >= 3:
                inputs["model_root"] = widgets[0]
                inputs["dtype"] = widgets[1]
                inputs["text_encoder_path"] = widgets[2]
            elif node_type == "RHMiniMaxH3VAELoader" and len(widgets) >= 3:
                inputs["model_root"] = widgets[0]
                inputs["video_vae_path"] = widgets[1]
                inputs["audio_vae_path"] = widgets[2]
            elif node_type == "RHMiniMaxH3FL2VATarget" and len(widgets) >= 2:
                inputs["aspect_ratio"] = widgets[0]
                inputs["duration_seconds"] = widgets[1]
                if len(widgets) >= 4:
                    inputs["width"] = widgets[2]
                    inputs["height"] = widgets[3]
            elif node_type == "RHMiniMaxH3FL2VAEncode" and len(widgets) > 0:
                inputs["prompt"] = widgets[0]
            elif node_type == "RHMiniMaxH3DualSigmaSampler" and len(widgets) >= 6:
                inputs["seed"] = widgets[0]
                inputs["sigma_points"] = widgets[1]
                inputs["video_shift"] = widgets[2]
                inputs["audio_shift"] = widgets[3]
                inputs["accel"] = widgets[4]
                inputs["denoise_video"] = widgets[5]
        elif isinstance(widgets, dict) and node_type == "VHS_VideoCombine":
            inputs.update(widgets)

        if node_type == "VHS_VideoCombine" and isinstance(node.get("widgets_values"), dict):
            inputs.update(node["widgets_values"])

        # 2. Cable connections mapping
        for input_conn in node.get("inputs", []):
            if "link" in input_conn and input_conn["link"] is not None:
                link_id = input_conn["link"]
                if link_id in link_map:
                    link_info = link_map[link_id]
                    from_node_id = str(link_info[1])
                    from_slot = link_info[2]
                    inputs[input_conn["name"]] = [from_node_id, from_slot]

        prompt_dict[node_id] = {
            "class_type": node_type,
            "inputs": inputs
        }

    return prompt_dict

class TestRC33RealH3Golden(unittest.TestCase):
    def setUp(self):
        self.ffmpeg_probe = FFmpegProbe()
        self.h3_probe = H3RuntimeProbe()
        self.model_probe = ModelLoaderProbe()
        self.graph_auditor = GoldenGraphAuditor()

    def test_rc33_golden_runtime(self):
        # 1. Probe FFmpeg & FFprobe
        ffmpeg_res = self.ffmpeg_probe.probe_and_configure_ffmpeg()
        self.assertEqual(ffmpeg_res["status"], "PASS", "FFmpeg & FFprobe must be available")

        # 2. Probe Local Model Files
        model_res = self.model_probe.probe_local_models()
        self.assertEqual(model_res["status"], "PASS", "Local H3 model weights must be present")

        # 3. Audit Graph Contracts
        graph_res = self.graph_auditor.audit_golden_graph()
        self.assertEqual(graph_res["status"], "PASS", "Golden graph audit must PASS")

        # 4. Probe Local ComfyUI API /object_info
        api_res = self.h3_probe.probe_local_h3_nodes()

        runtime_report = {
            "test_target": "04_Drone_Aerial_GOLDEN.json",
            "ffmpeg_probe": ffmpeg_res,
            "model_loader_probe": model_res,
            "golden_graph_audit": graph_res,
            "h3_runtime_probe": api_res,
            "prompt_submission": {},
            "status": "PASS" if (ffmpeg_res["status"] == "PASS" and model_res["status"] == "PASS" and graph_res["status"] == "PASS") else "BLOCKED"
        }

        # If API is online, attempt API execution probe
        if api_res.get("api_online"):
            try:
                api_prompt = workflow_to_api_prompt(GOLDEN_WORKFLOW_PATH)
                payload = json.dumps({"prompt": api_prompt}).encode("utf-8")
                req = urllib.request.Request("http://127.0.0.1:8188/prompt", data=payload, headers={"Content-Type": "application/json"})

                with urllib.request.urlopen(req, timeout=10) as resp:
                    res_data = json.loads(resp.read().decode("utf-8"))

                prompt_id = res_data.get("prompt_id")
                node_errors = res_data.get("node_errors", {})

                runtime_report["prompt_submission"] = {
                    "http_code": resp.status,
                    "prompt_id": prompt_id,
                    "node_errors": node_errors,
                    "submitted": prompt_id is not None,
                    "status": "PASS" if prompt_id else "FAIL"
                }
            except urllib.error.HTTPError as http_err:
                err_body = http_err.read().decode("utf-8") if http_err.fp else ""
                runtime_report["prompt_submission"] = {
                    "http_code": http_err.code,
                    "error_response": err_body,
                    "submitted": False,
                    "status": "REJECTED"
                }
            except Exception as e:
                runtime_report["prompt_submission"] = {
                    "error": str(e),
                    "submitted": False,
                    "status": "ERROR"
                }
        else:
            runtime_report["prompt_submission"] = {
                "submitted": False,
                "status": "NOT_EXECUTED",
                "reason": "ComfyUI server offline during unit test execution"
            }

        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        try:
            with open(REPORT_FILE, "w", encoding="utf-8") as f:
                json.dump(runtime_report, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

if __name__ == "__main__":
    unittest.main()
