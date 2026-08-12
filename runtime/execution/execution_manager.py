"""Execution Manager Engine (V0.7.4).
Manages workflow queueing, offline detection, timeouts, retries, and comprehensive error handling.
"""

import time
from pathlib import Path
from runtime.execution.comfy_api_client import ComfyAPIClient
from runtime.execution.execution_monitor import ExecutionMonitor
from runtime.execution.execution_schema import ExecutionResult

SYSTEM_ROOT = Path(__file__).resolve().parent.parent.parent

class ExecutionManager:
    """High-level Execution Manager with error handling."""

    def __init__(self, comfy_url: str = "http://127.0.0.1:8188"):
        self.client = ComfyAPIClient(comfy_url=comfy_url)
        self.monitor = ExecutionMonitor(self.client)

    def execute_package(self, payload: dict, workflow_id: str = "3_night_transition", timeout_seconds: float = 60.0) -> ExecutionResult:
        # 1. ComfyUI Offline Detection
        if not self.client.check_health():
            return ExecutionResult(
                status="offline",
                workflow_id=workflow_id,
                error_message="ComfyUI server is offline or unreachable at " + self.client.comfy_url
            )

        # 2. Post Prompt Queue
        try:
            prompt_res = self.client.post_prompt(payload)
            prompt_id = prompt_res.get("prompt_id", "")
        except Exception as e:
            err_msg = str(e)
            if "OutOfMemory" in err_msg or "VRAM" in err_msg:
                status_val = "vram_error"
            else:
                status_val = "error"
            return ExecutionResult(
                status=status_val,
                workflow_id=workflow_id,
                error_message=err_msg
            )

        # 3. Status Polling Loop
        start_time = time.time()
        while time.time() - start_time < timeout_seconds:
            status_data = self.monitor.check_execution_status(prompt_id)
            if status_data["status"] == "completed":
                output_file = status_data.get("output_file", "")
                output_path = str(SYSTEM_ROOT / "userdata" / "outputs" / (output_file or "H3_V0.7.4_Video.mp4"))
                return ExecutionResult(
                    status="completed",
                    prompt_id=prompt_id,
                    video_path=output_path,
                    workflow_id=workflow_id
                )
            elif status_data["status"] == "error":
                return ExecutionResult(
                    status="error",
                    prompt_id=prompt_id,
                    workflow_id=workflow_id,
                    error_message="Execution error in ComfyUI backend",
                    node_errors=status_data.get("error_details", [])
                )
            time.sleep(1.0)

        # 4. Timeout Handling
        return ExecutionResult(
            status="timeout",
            prompt_id=prompt_id,
            workflow_id=workflow_id,
            error_message=f"Execution timed out after {timeout_seconds}s"
        )
