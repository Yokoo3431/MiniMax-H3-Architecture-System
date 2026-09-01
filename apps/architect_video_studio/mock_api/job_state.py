"""Single canonical Job state contract shared by Study and deletion paths."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

TERMINAL_JOB_STATES = frozenset({
    "COMPLETED", "FAILED", "GPU_FAILED", "CANCELLED", "SUBMISSION_LOST",
})
ACTIVE_JOB_STATES = frozenset({
    "SUBMITTING", "SUBMISSION_UNKNOWN", "QUEUED", "RUNNING",
    "PREPARING", "LOADING_MODEL", "LOADING_MODELS", "ENCODING",
    "SAMPLING", "DECODING", "FINALIZING", "EXPORTING", "RECONCILING",
})
RECONCILIATION_GRACE_SECONDS = 15 * 60


def job_state(job: Dict[str, Any]) -> str:
    return str(job.get("state") or job.get("lifecycle_state") or "").upper()


def is_job_terminal(job: Dict[str, Any]) -> bool:
    return job_state(job) in TERMINAL_JOB_STATES


def _epoch(raw: Any) -> Optional[float]:
    if isinstance(raw, (int, float)):
        return float(raw)
    if not raw:
        return None
    try:
        value = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).timestamp()
    except (TypeError, ValueError, OverflowError):
        return None


def job_age_seconds(job: Dict[str, Any], now: Optional[float] = None) -> float:
    created = _epoch(job.get("created_at") or job.get("submitted_at"))
    if created is None:
        return 0.0
    current = float(now if now is not None else datetime.now(timezone.utc).timestamp())
    return max(0.0, current - created)


def is_job_recoverable(job: Dict[str, Any], now: Optional[float] = None) -> bool:
    state = job_state(job)
    if state in TERMINAL_JOB_STATES or state not in ACTIVE_JOB_STATES:
        return False
    if state != "RECONCILING":
        return True
    if job.get("reconciliation_terminal_reason"):
        return False
    # A prompt_id or explicit durable acknowledgement is recoverable even
    # after the grace window; a no-identity reconciliation expires safely.
    if job.get("prompt_id") or job.get("durable_accepted_submission"):
        return True
    return job_age_seconds(job, now) < RECONCILIATION_GRACE_SECONDS


def is_job_active(job: Dict[str, Any], now: Optional[float] = None) -> bool:
    return is_job_recoverable(job, now)


def terminal_elapsed_seconds(job: Dict[str, Any]) -> float:
    existing = job.get("elapsed")
    try:
        if existing is not None:
            return max(0.0, float(existing))
    except (TypeError, ValueError):
        pass
    started = _epoch(job.get("started_at") or job.get("created_at"))
    finished = _epoch(job.get("finished_at"))
    if started is not None and finished is not None:
        return max(0.0, finished - started)
    return 0.0


def normalize_terminal_record(job: Dict[str, Any], timestamp: str) -> bool:
    """Fill terminal invariants without changing a Job's terminal state."""
    if not is_job_terminal(job):
        return False
    changed = False
    if not job.get("finished_at"):
        job["finished_at"] = timestamp
        changed = True
    state = job_state(job)
    if state == "COMPLETED":
        expected = {
            "progress": 100.0,
            "lifecycle_state": "SUCCEEDED",
            "user_message": "已完成",
        }
        if job.get("delivery_state") == "OUTPUT_DELIVERY_FAILED":
            expected["user_message"] = "视频已生成，但复制到指定目录失败"
        for key, value in expected.items():
            if job.get(key) != value:
                job[key] = value
                changed = True
    elif state == "CANCELLED":
        for key, value in (("lifecycle_state", "CANCELLED"),
                           ("submission_state", "CANCELLED"),
                           ("user_message", "已取消")):
            if job.get(key) != value:
                job[key] = value
                changed = True
    elif state == "SUBMISSION_LOST":
        for key, value in (("lifecycle_state", "SUBMISSION_LOST"),
                           ("submission_state", "SUBMISSION_LOST")):
            if job.get(key) != value:
                job[key] = value
                changed = True
        if not job.get("user_message"):
            job["user_message"] = "任务提交未被 ComfyUI 确认，可重新生成"
            changed = True
    elif not job.get("user_message"):
        job["user_message"] = "任务执行失败"
        changed = True
    frozen = terminal_elapsed_seconds(job)
    try:
        current = float(job.get("elapsed"))
    except (TypeError, ValueError):
        current = None
    if current is None or current < 0:
        job["elapsed"] = round(frozen, 3)
        changed = True
    job["active"] = False
    job["is_active"] = False
    job["terminal_normalized_at"] = job.get("terminal_normalized_at") or timestamp
    return changed
