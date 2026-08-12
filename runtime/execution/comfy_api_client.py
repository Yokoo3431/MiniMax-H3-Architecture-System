"""ComfyUI API Client Engine (V0.7.4).
Communicates via HTTP/REST with ComfyUI server (/prompt, /history, /system_stats).
"""

import json
import urllib.request
import urllib.error

class ComfyAPIClient:
    """REST API Client for ComfyUI 0.27.0 backend."""

    def __init__(self, comfy_url: str = "http://127.0.0.1:8188"):
        self.comfy_url = comfy_url.rstrip("/")

    def check_health(self) -> bool:
        try:
            req = urllib.request.Request(f"{self.comfy_url}/system_stats")
            with urllib.request.urlopen(req, timeout=3) as resp:
                return resp.status == 200
        except Exception:
            return False

    def post_prompt(self, payload: dict) -> dict:
        data = json.dumps({"prompt": payload}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.comfy_url}/prompt",
            data=data,
            headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            err_text = e.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"ComfyUI HTTP {e.code}: {err_text}")
        except Exception as e:
            raise RuntimeError(f"ComfyUI connection failed: {e}")

    def get_history(self, prompt_id: str) -> dict:
        req = urllib.request.Request(f"{self.comfy_url}/history/{prompt_id}")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            return {}
