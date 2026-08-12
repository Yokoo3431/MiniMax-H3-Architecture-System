"""Execution Monitor Engine (V0.7.4).
Monitors job progress and detects node execution errors.
"""

from runtime.execution.comfy_api_client import ComfyAPIClient

class ExecutionMonitor:
    """Monitors ComfyUI prompt execution status."""

    def __init__(self, api_client: ComfyAPIClient):
        self.client = api_client

    def check_execution_status(self, prompt_id: str) -> dict:
        history = self.client.get_history(prompt_id)
        if prompt_id not in history:
            return {"status": "running", "output_file": None}

        data = history[prompt_id]
        status_info = data.get("status", {})

        if status_info.get("completed", False):
            outputs = data.get("outputs", {})
            output_file = None
            for node_id, node_out in outputs.items():
                if "gifs" in node_out:
                    output_file = node_out["gifs"][0].get("filename")
                elif "images" in node_out:
                    output_file = node_out["images"][0].get("filename")
            return {"status": "completed", "output_file": output_file}

        if status_info.get("status_str") == "error":
            return {"status": "error", "error_details": status_info.get("messages", [])}

        return {"status": "running", "output_file": None}
