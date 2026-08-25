"""Project-local storage policy for Architect Video Studio processes.

The policy is deliberately process-scoped: it returns an environment mapping
for a child process and never changes Windows user or system environment
variables.  All installer-controlled transient storage stays under the
repository's D-drive project root.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping, MutableMapping


def cache_root(repo_root: Path) -> Path:
    return Path(repo_root).resolve() / "userdata" / "cache"


def cache_paths(repo_root: Path) -> dict[str, Path]:
    root = cache_root(repo_root)
    return {
        "root": root,
        "runtime": root / "runtime",
        "downloads": root / "downloads",
        "pip": root / "pip",
        "huggingface": root / "huggingface",
        "huggingface_hub": root / "huggingface" / "hub",
        "temp": root / "temp",
        "extract": root / "extract",
    }


def ensure_cache_dirs(repo_root: Path) -> dict[str, Path]:
    paths = cache_paths(repo_root)
    for name in ("runtime", "downloads", "pip", "huggingface",
                 "huggingface_hub", "temp", "extract"):
        paths[name].mkdir(parents=True, exist_ok=True)
    return paths


def process_environment(repo_root: Path,
                        base: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return a child-process environment with project-local cache paths."""
    env = dict(os.environ if base is None else base)
    paths = cache_paths(repo_root)
    env.update({
        "TEMP": str(paths["temp"]),
        "TMP": str(paths["temp"]),
        "PIP_CACHE_DIR": str(paths["pip"]),
        "HF_HOME": str(paths["huggingface"]),
        "HF_HUB_CACHE": str(paths["huggingface_hub"]),
    })
    return env


def apply_process_environment(repo_root: Path) -> dict[str, Path]:
    """Apply the policy to the current Studio process only.

    This is not a persistent Windows environment change.  The returned paths
    are useful to callers that need to display or audit the selected roots.
    """
    paths = ensure_cache_dirs(repo_root)
    os.environ.update(process_environment(repo_root))
    return paths

