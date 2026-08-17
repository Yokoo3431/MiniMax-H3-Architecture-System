"""Path/bootstrap helpers for the prototype (repo root on sys.path)."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
APP_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = APP_ROOT / "frontend"
DEFAULT_DATA_ROOT = APP_ROOT / "data"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def repo_relative(path: Path) -> Path:
    """Resolve a path relative to the repository root."""
    p = Path(path)
    return p if p.is_absolute() else REPO_ROOT / p
