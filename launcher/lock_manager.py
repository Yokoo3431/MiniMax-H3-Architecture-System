"""runtime.lock management (PATCH2.8-B).

Protects against duplicate launcher instances and blocks shutdown/cleanup/update
while a GPU job is running.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path


class LockManager:
    def __init__(self, lock_path: Path, clock=None) -> None:
        self.lock_path = Path(lock_path)
        self.clock = clock or time.time

    def _pid_alive(self, pid: int) -> bool:
        if pid <= 0:
            return False
        if os.name == "nt":
            import ctypes
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
            if not handle:
                return False
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def read_lock(self) -> dict | None:
        if not self.lock_path.is_file():
            return None
        try:
            data = json.loads(self.lock_path.read_text(encoding="utf-8"))
            if not data.get("pid") or not self._pid_alive(int(data["pid"])):
                return None  # stale lock (dead process)
            return data
        except Exception:
            return None

    def acquire(self, pid: int | None = None) -> dict:
        existing = self.read_lock()
        if existing is not None:
            raise RuntimeError(
                f"another launcher is running (pid={existing.get('pid')}, "
                f"started_at={existing.get('started_at')})")
        lock = {
            "pid": pid or os.getpid(),
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "heartbeat": self.clock(),
            "job_running": False,
        }
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_path.write_text(
            json.dumps(lock, indent=2), encoding="utf-8")
        return lock

    def heartbeat(self) -> dict:
        lock = self.read_lock()
        if lock is None:
            raise RuntimeError("lock missing or stale; cannot update heartbeat")
        lock["heartbeat"] = self.clock()
        self._write(lock)
        return lock

    def set_job_running(self, running: bool) -> dict:
        lock = self.read_lock()
        if lock is None:
            raise RuntimeError("lock missing or stale")
        lock["job_running"] = bool(running)
        self._write(lock)
        return lock

    def release(self) -> None:
        if self.lock_path.is_file():
            try:
                self.lock_path.unlink()
            except OSError:
                pass

    # safety gates
    def assert_safe_shutdown(self) -> None:
        lock = self.read_lock()
        if lock and lock.get("job_running"):
            raise RuntimeError(
                "GPU job is running: shutdown/cleanup/update are blocked. "
                "Wait for completion or cancel the job first.")

    def assert_safe_cleanup(self) -> None:
        self.assert_safe_shutdown()

    def assert_safe_update(self) -> None:
        self.assert_safe_shutdown()

    def _write(self, lock: dict) -> None:
        self.lock_path.write_text(
            json.dumps(lock, indent=2), encoding="utf-8")
