"""Append-only logging for the production launcher (PATCH2.8-B)."""

from __future__ import annotations

import time
from pathlib import Path


class LauncherLogger:
    def __init__(self, logs_dir: Path, name: str = "launcher") -> None:
        self.logs_dir = Path(logs_dir)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.logs_dir / f"{name}.log"

    def log(self, level: str, message: str) -> None:
        ts = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        with open(self.path, "a", encoding="utf-8") as fh:  # append-only
            fh.write(f"[{ts}] [{level}] {message}\n")

    def info(self, message: str) -> None:
        self.log("INFO", message)

    def warning(self, message: str) -> None:
        self.log("WARNING", message)

    def error(self, message: str) -> None:
        self.log("ERROR", message)
