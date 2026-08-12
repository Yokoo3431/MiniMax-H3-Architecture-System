"""Execution Logger System (V0.7.4.1).
Records generation requests and execution metrics for debugging, memory learning, and Critic Agent auditing.
"""

import json
import time
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent.parent
LOG_DIR = SYSTEM_ROOT / "runtime" / "logs"
LOG_FILE = LOG_DIR / "execution_history.jsonl"

class ExecutionLogger:
    """Logs generation execution events into runtime/logs/execution_history.jsonl."""

    def __init__(self):
        LOG_DIR.mkdir(parents=True, exist_ok=True)

    def log_execution(
        self,
        input_image: str,
        task: str,
        vision_intent: dict,
        workflow_id: str,
        hardware_profile: str,
        execution_time: float,
        status: str,
        output: str = "",
        error: str = ""
    ) -> dict:
        log_entry = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
            "input_image": input_image,
            "task": task,
            "vision_intent": vision_intent,
            "workflow_id": workflow_id,
            "hardware_profile": hardware_profile,
            "execution_time": round(execution_time, 3),
            "status": status,
            "output": output,
            "error": error
        }

        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
        except Exception:
            pass

        return log_entry
