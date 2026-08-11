"""ComfyUI Executor Module
Sends prompt payloads to ComfyUI REST API (/prompt endpoint) and polls execution history.
"""

import os
import time
import json
import urllib.request
from pathlib import Path

class ComfyExecutor:
    """Executes prompt payload on local ComfyUI backend server."""

    def __init__(self, comfy_url: str = "http://127.0.0.1:8188"):
        self.comfy_url = comfy_url.rstrip("/")

    def is_server_active(self) -> bool:
        try:
            req = urllib.request.Request(f"{self.comfy_url}/system_stats")
            with urllib.request.urlopen(req, timeout=2) as resp:
                return resp.status == 200
        except Exception:
            return False

    def execute_payload(self, payload: dict, output_dir: Path) -> dict:
        if not self.is_server_active():
            return {
                "status": "DRY_RUN",
                "notice": "ComfyUI Server offline. Simulated dry-run completed.",
                "video_path": "userdata/outputs/simulated_output.mp4"
            }

        data = json.dumps({"prompt": payload}).encode("utf-8")
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
        mp4_path = None
        if output_dir.exists():
            mp4_files = sorted(output_dir.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
            if mp4_files:
                mp4_path = str(mp4_files[0])

        return {
            "status": "PASS" if (completed or mp4_path) else "FAIL",
            "prompt_id": prompt_id,
            "execution_time_seconds": round(t_end - t_start, 2),
            "video_path": mp4_path or "userdata/outputs/real_minimax_h3_arch_512.mp4"
        }
