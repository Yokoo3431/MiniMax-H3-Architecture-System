"""Fail-closed local registry for the isolated A5 ComfyUI deployment.

The registry file is machine-local and intentionally lives with Studio data,
not in source control. Public projections contain opaque fingerprints only.
"""

from __future__ import annotations

import base64
import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any, Mapping
from urllib.parse import urlsplit


REGISTRY_FILENAME = "experimental_runtime_registry.local.json"
EXPECTED_RUNTIME_ID = "experimental-h3-8190"
EXPECTED_RUNTIME_ROLE = "experimental"
EXPECTED_VERSION = "0.36.0"
EXPECTED_GIT_SHA = "ee71d5c4993f29086b27fde1629a945ae48425bf"
EXPECTED_PACKAGES = {"comfy-aimdo": "0.5.3", "comfy-kitchen": "0.2.34"}
REQUIRED_DIRECTORIES = ("input_root", "output_root", "temp_root", "user_root", "models_root")


def _path_fingerprint(value: str | Path) -> str:
    normalized = str(Path(value).expanduser().resolve()).casefold()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _overlap(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def _canonical_path(value: str | Path, *, relative_to: Path | None = None) -> str:
    path = Path(value).expanduser()
    if not path.is_absolute() and relative_to is not None:
        path = relative_to / path
    return os.path.normcase(str(path.resolve()))


def _read_git_head(source_root: Path) -> str | None:
    """Read the checked-out commit from Git metadata without requiring git.exe.

    The desktop shell may launch Studio with a deliberately small PATH.  The
    pinned runtime identity can still be verified from the local Git metadata,
    including detached HEADs, packed refs, and linked worktrees.
    """
    marker = source_root / ".git"
    try:
        if marker.is_dir():
            git_dir = marker.resolve()
        elif marker.is_file():
            marker_text = marker.read_text(encoding="utf-8").strip()
            if not marker_text.startswith("gitdir:"):
                return None
            raw_git_dir = marker_text[len("gitdir:"):].strip()
            if not raw_git_dir:
                return None
            git_dir_path = Path(raw_git_dir)
            if not git_dir_path.is_absolute():
                git_dir_path = source_root / git_dir_path
            git_dir = git_dir_path.resolve()
        else:
            return None

        common_dir = git_dir
        common_dir_file = git_dir / "commondir"
        if common_dir_file.is_file():
            raw_common_dir = common_dir_file.read_text(encoding="utf-8").strip()
            if raw_common_dir:
                common_dir_path = Path(raw_common_dir)
                if not common_dir_path.is_absolute():
                    common_dir_path = git_dir / common_dir_path
                common_dir = common_dir_path.resolve()

        head = (git_dir / "HEAD").read_text(encoding="ascii").strip()
        if re.fullmatch(r"[0-9a-fA-F]{40}", head):
            return head.lower()
        if not head.startswith("ref: "):
            return None

        ref = head[5:].strip()
        ref_path = PurePosixPath(ref)
        if (not ref or ref_path.is_absolute()
                or any(part in {"", ".", ".."} for part in ref.split("/"))
                or "\\" in ref):
            return None

        relative_ref = Path(*ref_path.parts)
        for ref_root in (git_dir, common_dir):
            try:
                value = (ref_root / relative_ref).read_text(encoding="ascii").strip()
            except OSError:
                continue
            if re.fullmatch(r"[0-9a-fA-F]{40}", value):
                return value.lower()

        for ref_root in dict.fromkeys((git_dir, common_dir)):
            packed_refs = ref_root / "packed-refs"
            try:
                lines = packed_refs.read_text(encoding="ascii").splitlines()
            except OSError:
                continue
            for line in lines:
                if not line or line.startswith(("#", "^")):
                    continue
                fields = line.split()
                if (len(fields) == 2 and fields[1] == ref
                        and re.fullmatch(r"[0-9a-fA-F]{40}", fields[0])):
                    return fields[0].lower()
    except (OSError, RuntimeError, UnicodeError, ValueError):
        return None
    return None


def live_runtime_process_matches(argv: Any, config: Mapping[str, Any]) -> bool:
    """Bind the live loopback process to the pinned source and isolated I/O roots."""
    if not isinstance(argv, (list, tuple)) or not argv:
        return False
    args = [str(item) for item in argv]
    source_root = Path(str(config.get("source_root") or "")).expanduser().resolve()
    if _canonical_path(args[0], relative_to=source_root) != _canonical_path(
            source_root / "main.py"):
        return False
    required = {
        "--port": "8190",
        "--input-directory": str(config.get("input_root") or ""),
        "--output-directory": str(config.get("output_root") or ""),
        "--temp-directory": str(config.get("temp_root") or ""),
        "--user-directory": str(config.get("user_root") or ""),
        "--extra-model-paths-config": str(config.get("extra_model_paths_config") or ""),
    }
    values: dict[str, str] = {}
    for index, token in enumerate(args[:-1]):
        if token in required:
            if token in values:
                return False
            values[token] = args[index + 1]
    if set(values) != set(required):
        return False
    for flag, expected in required.items():
        if flag == "--port":
            if values[flag] != expected:
                return False
        elif _canonical_path(values[flag], relative_to=source_root) != _canonical_path(
                expected, relative_to=source_root):
            return False
    return True


def live_runtime_executable_matches(expected_executable: str | Path) -> bool:
    """Require the 8190 listener's process tree to originate from pinned venv Python."""
    if os.name != "nt":
        return False
    expected = _canonical_path(expected_executable)
    if not Path(expected).is_file():
        return False
    powershell = os.path.join(
        os.environ.get("WINDIR", r"C:\Windows"),
        "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    if not os.path.isfile(powershell):
        powershell = shutil.which("powershell.exe") or ""
    if not powershell:
        return False
    expected_literal = str(expected).replace("'", "''")
    script = (
        "$ErrorActionPreference = 'Stop'; "
        f"$expected = '{expected_literal}'; "
        "$row = Get-NetTCPConnection -LocalPort 8190 -State Listen "
        "-ErrorAction SilentlyContinue | Where-Object { $_.LocalAddress -eq '127.0.0.1' } "
        "| Select-Object -First 1; "
        "if (-not $row) { [Console]::Out.Write('NO_LISTENER'); exit 2 }; "
        "$p = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $row.OwningProcess); "
        "$matched = $false; "
        "for ($i = 0; $i -lt 5 -and $p; $i++) { "
        "$line = [string]$p.CommandLine; $exe = [string]$p.ExecutablePath; "
        "if ($exe -and $exe.Equals($expected, [StringComparison]::OrdinalIgnoreCase) "
        "-and $line.Contains('main.py') "
        "-and ($line.Contains('--port 8190') -or $line.Contains('--port=8190'))) "
        "{ $matched = $true; break }; "
        "$parentId = [int]$p.ParentProcessId; "
        "if (-not $parentId) { break }; "
        "$p = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $parentId) "
        "-ErrorAction SilentlyContinue }; "
        "if ($matched) { [Console]::Out.Write('MATCH'); exit 0 }; "
        "[Console]::Out.Write('NO_MATCH'); exit 1"
    )
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    try:
        result = subprocess.run(
            [powershell, "-NoLogo", "-NoProfile", "-NonInteractive",
             "-EncodedCommand", encoded],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and result.stdout.strip() == "MATCH"


def _invalid(reason: str) -> dict[str, Any]:
    return {"valid": False, "enabled": False, "reason": reason,
            "public": {"runtime_id": EXPECTED_RUNTIME_ID,
                       "runtime_role": EXPECTED_RUNTIME_ROLE,
                       "backend": "comfyui", "endpoint_identity": "loopback:8190",
                       "health": "UNAVAILABLE", "route_enabled": False}}


def inspect_experimental_runtime_registry(
        data_root: str | Path, *, production_input: str | Path | None = None,
        production_output: str | Path | None = None,
        registry_path: str | Path | None = None) -> dict[str, Any]:
    """Validate the local deployment manifest without importing/loading H3."""
    file_path = Path(registry_path) if registry_path else Path(data_root) / REGISTRY_FILENAME
    try:
        config = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _invalid("EXPERIMENTAL_RUNTIME_REGISTRY_MISSING_OR_INVALID")
    if not isinstance(config, Mapping) or config.get("schema_version") != 1:
        return _invalid("EXPERIMENTAL_RUNTIME_REGISTRY_SCHEMA_MISMATCH")
    if config.get("enabled") is not True:
        return _invalid("EXPERIMENTAL_RUNTIME_ROUTE_DISABLED")
    if (config.get("runtime_id") != EXPECTED_RUNTIME_ID
            or config.get("runtime_role") != EXPECTED_RUNTIME_ROLE
            or config.get("backend") != "comfyui"
            or config.get("comfyui_version") != EXPECTED_VERSION
            or str(config.get("comfyui_git_sha") or "").lower() != EXPECTED_GIT_SHA):
        return _invalid("EXPERIMENTAL_RUNTIME_IDENTITY_MISMATCH")

    base_url = str(config.get("endpoint") or "").rstrip("/")
    try:
        endpoint = urlsplit(base_url)
        if (endpoint.scheme != "http" or endpoint.hostname not in {"127.0.0.1", "localhost"}
                or endpoint.port != 8190 or endpoint.username or endpoint.password
                or endpoint.path or endpoint.query or endpoint.fragment):
            return _invalid("EXPERIMENTAL_RUNTIME_ENDPOINT_MISMATCH")
    except ValueError:
        return _invalid("EXPERIMENTAL_RUNTIME_ENDPOINT_MISMATCH")

    try:
        source_root = Path(str(config.get("source_root") or "")).expanduser().resolve()
        python_executable = Path(str(config.get("python_executable") or "")).expanduser().resolve()
        roots = {name: Path(str(config.get(name) or "")).expanduser().resolve()
                 for name in REQUIRED_DIRECTORIES}
    except (OSError, RuntimeError, TypeError, ValueError):
        return _invalid("EXPERIMENTAL_RUNTIME_PATH_CONFIGURATION_INVALID")
    if (not (source_root / "main.py").is_file()
            or not python_executable.is_file()
            or not all(path.is_dir() for path in roots.values())):
        return _invalid("EXPERIMENTAL_RUNTIME_LAYOUT_INCOMPLETE")
    extra_model_config = Path(str(
        config.get("extra_model_paths_config") or "")).expanduser().resolve()
    try:
        extra_model_config_sha256 = hashlib.sha256(
            extra_model_config.read_bytes()).hexdigest()
    except OSError:
        return _invalid("EXPERIMENTAL_RUNTIME_MODEL_CONFIG_MISSING")

    for index, first in enumerate(REQUIRED_DIRECTORIES):
        for second in REQUIRED_DIRECTORIES[index + 1:]:
            if _overlap(roots[first], roots[second]):
                return _invalid("EXPERIMENTAL_RUNTIME_DIRECTORY_ISOLATION_FAILED")
    for experimental_io in (roots["input_root"], roots["output_root"],
                            roots["temp_root"], roots["user_root"]):
        for production_io in (production_input, production_output):
            if production_io:
                try:
                    if _overlap(experimental_io, Path(production_io).resolve()):
                        return _invalid("EXPERIMENTAL_RUNTIME_PRODUCTION_OVERLAP")
                except (OSError, RuntimeError, TypeError, ValueError):
                    return _invalid("EXPERIMENTAL_RUNTIME_PRODUCTION_OVERLAP")

    version_file = source_root / "comfyui_version.py"
    try:
        source = version_file.read_text(encoding="utf-8")
    except OSError:
        return _invalid("EXPERIMENTAL_RUNTIME_VERSION_SOURCE_MISSING")
    match = re.search(r"^__version__\s*=\s*['\"]([^'\"]+)", source, re.MULTILINE)
    if not match or match.group(1) != EXPECTED_VERSION:
        return _invalid("EXPERIMENTAL_RUNTIME_VERSION_MISMATCH")
    try:
        node_source = (source_root / "comfy_extras" /
                       "nodes_minimax_h3.py").read_text(
                           encoding="utf-8", errors="replace")
    except OSError:
        node_source = ""
    if "class MiniMaxH3AddGuide" not in node_source:
        return _invalid("EXPERIMENTAL_ADDGUIDE_SOURCE_MISSING")

    git_head = _read_git_head(source_root)
    if git_head is None:
        return _invalid("EXPERIMENTAL_RUNTIME_GIT_IDENTITY_UNAVAILABLE")
    if git_head != EXPECTED_GIT_SHA:
        return _invalid("EXPERIMENTAL_RUNTIME_GIT_SHA_MISMATCH")

    venv_root = python_executable.parent.parent
    try:
        pyvenv = (venv_root / "pyvenv.cfg").read_text(encoding="utf-8")
    except OSError:
        return _invalid("EXPERIMENTAL_RUNTIME_VENV_MISSING")
    python_match = re.search(r"^version\s*=\s*([^\r\n]+)", pyvenv, re.MULTILINE)
    if not python_match or python_match.group(1).strip() != "3.12.10":
        return _invalid("EXPERIMENTAL_RUNTIME_PYTHON_VERSION_MISMATCH")
    site_packages = venv_root / "Lib" / "site-packages"
    if not site_packages.is_dir():
        return _invalid("EXPERIMENTAL_RUNTIME_PACKAGES_MISSING")
    installed = {}
    try:
        for distribution in importlib.metadata.distributions(path=[str(site_packages)]):
            name = str(distribution.metadata.get("Name") or "").lower().replace("_", "-")
            if name:
                installed[name] = distribution.version
    except (OSError, ValueError):
        return _invalid("EXPERIMENTAL_RUNTIME_PACKAGES_MISSING")
    for package, expected_version in EXPECTED_PACKAGES.items():
        installed_version = installed.get(package)
        if installed_version is None:
            return _invalid("EXPERIMENTAL_RUNTIME_DEPENDENCY_MISSING")
        if installed_version != expected_version:
            return _invalid("EXPERIMENTAL_RUNTIME_DEPENDENCY_MISMATCH")

    fingerprints = {name.removesuffix("_root"): _path_fingerprint(path)
                    for name, path in roots.items()}
    identity_payload = {
        "runtime_id": EXPECTED_RUNTIME_ID,
        "runtime_role": EXPECTED_RUNTIME_ROLE,
        "backend": "comfyui",
        "endpoint_identity": "loopback:8190",
        "comfyui_version": EXPECTED_VERSION,
        "comfyui_git_sha": EXPECTED_GIT_SHA,
        "python_version": "3.12.10",
        "packages": EXPECTED_PACKAGES,
        "root_fingerprints": fingerprints,
        "extra_model_paths_config_sha256": extra_model_config_sha256,
    }
    config_fingerprint = hashlib.sha256(json.dumps(
        identity_payload, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()
    public = {
        **identity_payload,
        "output_root_fingerprint": fingerprints["output"][:24],
        "config_fingerprint": config_fingerprint,
        "capabilities": ["MiniMaxH3AddGuide"],
        "health": "NOT_CHECKED",
        "route_enabled": True,
    }
    return {"valid": True, "enabled": True, "reason": "",
            "config": {**dict(config), **{key: str(value) for key, value in roots.items()},
                       "source_root": str(source_root),
                       "python_executable": str(python_executable),
                       "extra_model_paths_config": str(extra_model_config)},
            "public": public}
