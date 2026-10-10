"""Create a path-safe, identity-complete companion Owner Export manifest.

This utility never changes media or the source manifest. It validates every
manifest-listed artifact, resolves A9 shot Results from the live Studio API,
and writes a new manifest path chosen by the caller.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
from typing import Any, Mapping
from urllib.error import URLError
from urllib.parse import quote, urlparse, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


SHA256_RE = re.compile(r"^[a-f0-9]{64}$", re.IGNORECASE)
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,160}$")
WINDOWS_PATH_RE = re.compile(r"(?i)(?<![A-Za-z0-9])[A-Z]:[\\/][^\s\"'<>|]+")
UNC_PATH_RE = re.compile(r"(?<![A-Za-z0-9])\\\\[^\s\"'<>|]+")
POSIX_PATH_RE = re.compile(r"(?<![A-Za-z0-9:/])/(?!api/)[^\s\"'<>|]+")
SECRET_QUERY_RE = re.compile(r"(?i)([?&](?:access_?token|token|secret|password|api_key)=)[^&#\s]+")
MAX_LIVE_API_BYTES = 2 * 1024 * 1024
ARTIFACT_FIELDS = (
    "stage", "kind", "job_or_assembly_id", "project_id", "study_id",
    "result_id", "delivery_id", "queue_id", "sequence_id", "shot_count",
    "workflow_sha256", "runtime_id", "guide_frame_indexes", "created_at",
    "started_at_utc", "finished_at_utc", "delivery_created_at",
)
MEDIA_FIELDS = (
    "size_bytes", "sha256", "width", "height", "fps", "duration_seconds",
    "frame_count", "video_codec", "audio_stream", "processing_method",
    "source_media_endpoint",
)
PRIVATE_KEYS = {
    "studio_path", "absolute_path", "file_path", "output_path", "runtime_path",
    "package_root", "output_root", "input_root", "temp_root", "user_root",
    "prompt", "prompt_text", "optimized_prompt", "original_intent",
    "token", "access_token", "credential", "password", "secret",
}


class ManifestReconciliationError(ValueError):
    """A safe, path-free manifest validation error."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_id(value: Any) -> str:
    result = str(value or "")
    if not ID_RE.fullmatch(result):
        raise ManifestReconciliationError("IDENTITY_FIELD_INVALID")
    return result


def _safe_relative_media(root: Path, value: Any) -> tuple[str, Path]:
    raw = str(value or "").strip()
    windows = PureWindowsPath(raw)
    candidate_path = Path(raw.replace("\\", "/"))
    if (not raw or windows.is_absolute() or candidate_path.is_absolute()
            or windows.drive or any(part in {"", ".", ".."} for part in candidate_path.parts)):
        raise ManifestReconciliationError("MEDIA_PATH_NOT_RELATIVE")
    root_resolved = root.resolve(strict=True)
    candidate = (root_resolved / candidate_path).resolve(strict=True)
    try:
        relative = candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise ManifestReconciliationError("MEDIA_PATH_ESCAPES_EXPORT_ROOT") from exc
    if not candidate.is_file():
        raise ManifestReconciliationError("MEDIA_FILE_MISSING")
    return relative.as_posix(), candidate


def _sanitize(value: Any, key: str = "") -> Any:
    """Recursively remove secrets and local absolute-path disclosures."""
    normalized_key = key.lower()
    if normalized_key in PRIVATE_KEYS or any(
            token in normalized_key for token in ("credential", "password", "secret", "token")):
        return None
    if isinstance(value, Mapping):
        return {
            str(child_key): _sanitize(child, str(child_key))
            for child_key, child in value.items()
            if str(child_key).lower() not in PRIVATE_KEYS
            and not any(token in str(child_key).lower()
                        for token in ("credential", "password", "secret", "token"))
            and "prompt" not in str(child_key).lower()
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize(child, key) for child in value]
    if isinstance(value, str):
        if value.startswith("/api/"):
            return urlsplit(value).path
        sanitized = SECRET_QUERY_RE.sub(r"\1[redacted]", value)
        if any(pattern.search(sanitized)
               for pattern in (WINDOWS_PATH_RE, UNC_PATH_RE, POSIX_PATH_RE)):
            return "[local path omitted]"
        return sanitized
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)


def _a9_queue_from_live_data(manifest: Mapping[str, Any],
                             live_data: Mapping[str, Any]) -> Mapping[str, Any]:
    lineage = manifest.get("A9_sequence_lineage")
    if not isinstance(lineage, Mapping):
        raise ManifestReconciliationError("A9_LINEAGE_MISSING")
    project_id = _safe_id(lineage.get("project_id"))
    queue_id = _safe_id(lineage.get("queue_id"))
    assembly_id = _safe_id(lineage.get("assembly_id"))
    sequences = live_data.get("queues") if isinstance(live_data, Mapping) else None
    if not isinstance(sequences, list):
        sequences = [live_data] if isinstance(live_data, Mapping) else []
    matches = [item for item in sequences
               if isinstance(item, Mapping) and item.get("queue_id") == queue_id]
    if len(matches) != 1:
        raise ManifestReconciliationError("A9_QUEUE_NOT_UNIQUE")
    queue = matches[0]
    assembly = queue.get("assembly") or {}
    if (queue.get("project_id") != project_id
            or (queue.get("director_sequence_id") or queue.get("sequence_id"))
            != lineage.get("sequence_id")
            or assembly.get("assembly_id") != assembly_id
            or str(assembly.get("status") or "").upper() != "READY"
            or str(queue.get("status") or "").upper() != "READY"):
        raise ManifestReconciliationError("A9_IDENTITY_MISMATCH")
    return queue


def build_reconciled_manifest(
        manifest: Mapping[str, Any], export_root: Path, live_data: Mapping[str, Any],
        *, parent_sha256: str, reconciled_at_utc: str | None = None) -> dict[str, Any]:
    """Validate export files and return a sanitized v2 companion manifest."""
    if not SHA256_RE.fullmatch(parent_sha256):
        raise ManifestReconciliationError("PARENT_MANIFEST_SHA_INVALID")
    root = export_root.resolve(strict=True)
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ManifestReconciliationError("ARTIFACT_LIST_INVALID")

    output_artifacts: list[dict[str, Any]] = []
    total_bytes = 0
    assembly_artifact: Mapping[str, Any] | None = None
    for item in artifacts:
        if not isinstance(item, Mapping) or not isinstance(item.get("media"), Mapping):
            raise ManifestReconciliationError("ARTIFACT_RECORD_INVALID")
        media = item["media"]
        relative_path, path = _safe_relative_media(root, media.get("relative_path"))
        actual_sha = _sha256_file(path)
        expected_sha = str(media.get("sha256") or "").lower()
        actual_size = path.stat().st_size
        if not SHA256_RE.fullmatch(expected_sha) or actual_sha != expected_sha:
            raise ManifestReconciliationError("MEDIA_SHA_MISMATCH")
        if int(media.get("size_bytes") or -1) != actual_size:
            raise ManifestReconciliationError("MEDIA_SIZE_MISMATCH")
        clean_item = {key: _sanitize(item[key], key)
                      for key in ARTIFACT_FIELDS if key in item}
        clean_item["media"] = {
            "relative_path": relative_path,
            "size_bytes": actual_size,
            "sha256": actual_sha,
            **{key: _sanitize(media[key], key) for key in MEDIA_FIELDS if key in media},
        }
        output_artifacts.append(clean_item)
        total_bytes += actual_size
        if item.get("kind") == "assembly":
            if assembly_artifact is not None:
                raise ManifestReconciliationError("A9_ASSEMBLY_NOT_UNIQUE")
            assembly_artifact = item
    if total_bytes != int(manifest.get("total_bytes") or -1):
        raise ManifestReconciliationError("MANIFEST_TOTAL_SIZE_MISMATCH")
    if assembly_artifact is None:
        raise ManifestReconciliationError("A9_ASSEMBLY_MISSING")

    queue = _a9_queue_from_live_data(manifest, live_data)
    lineage = manifest["A9_sequence_lineage"]
    shots = queue.get("shots")
    expected_count = int(lineage.get("shot_count") or 0)
    if not isinstance(shots, list) or len(shots) != expected_count:
        raise ManifestReconciliationError("A9_SHOT_COUNT_MISMATCH")
    legacy_shots = lineage.get("shot_jobs") or []
    legacy_by_id = {str(item.get("shot_id") or ""): item
                    for item in legacy_shots if isinstance(item, Mapping)}
    if len(legacy_by_id) != len(shots):
        raise ManifestReconciliationError("A9_LEGACY_SHOT_INDEX_INVALID")

    reconciled_shots: list[dict[str, Any]] = []
    seen_jobs: set[str] = set()
    seen_ordinals: set[int] = set()
    for shot in shots:
        if not isinstance(shot, Mapping):
            raise ManifestReconciliationError("A9_SHOT_RECORD_INVALID")
        shot_id = _safe_id(shot.get("shot_id"))
        ordinal = shot.get("ordinal")
        if (not isinstance(ordinal, int) or isinstance(ordinal, bool)
                or ordinal < 0 or ordinal in seen_ordinals):
            raise ManifestReconciliationError("A9_SHOT_ORDINAL_INVALID")
        seen_ordinals.add(ordinal)
        prior = legacy_by_id.get(shot_id)
        job_identity = shot.get("job_identity") or {}
        result_identity = shot.get("result_identity") or {}
        job_id = _safe_id(job_identity.get("job_id"))
        if (not prior or prior.get("job_id") != job_id or job_id in seen_jobs
                or str(shot.get("state") or "").upper() != "RESULT_READY"
                or not ID_RE.fullmatch(str(job_identity.get("prompt_id") or ""))
                or not ID_RE.fullmatch(str(job_identity.get("runtime_id") or ""))
                or not SHA256_RE.fullmatch(
                    str(job_identity.get("workflow_sha256") or "").lower())
                or result_identity.get("result_id") != f"result:{job_id}"
                or not SHA256_RE.fullmatch(
                    str(result_identity.get("media_sha256") or "").lower())):
            raise ManifestReconciliationError("A9_SHOT_RESULT_IDENTITY_INCOMPLETE")
        seen_jobs.add(job_id)
        reconciled_shots.append({
            "shot_id": shot_id,
            "ordinal": ordinal,
            "job_id": job_id,
            "job_state": "RESULT_READY",
            "result_id": result_identity["result_id"],
            "prompt_id": str(job_identity["prompt_id"]),
            "workflow_sha256": str(job_identity["workflow_sha256"]).lower(),
            "runtime_id": str(job_identity["runtime_id"]),
            "media_sha256": str(result_identity["media_sha256"]).lower(),
            "media": {
                key: _sanitize(result_identity[key], key)
                for key in ("width", "height", "fps", "duration_seconds",
                            "audio_stream") if key in result_identity
            },
        })
    reconciled_shots.sort(key=lambda item: item["ordinal"])

    exported_native_by_job = {
        str(item.get("job_or_assembly_id")): item
        for item in output_artifacts
        if item.get("kind") == "native" and item.get("job_or_assembly_id")
    }
    for shot in reconciled_shots:
        exported = exported_native_by_job.get(shot["job_id"])
        if exported is None:
            continue
        exported_media = exported.get("media") or {}
        if (exported.get("result_id") not in {None, shot["result_id"]}
                or str(exported_media.get("sha256") or "").lower()
                != shot["media_sha256"]):
            raise ManifestReconciliationError("A9_EXPORTED_SHOT_MEDIA_MISMATCH")

    assembly_media = assembly_artifact["media"]
    live_assembly = queue.get("assembly") or {}
    if (str(live_assembly.get("output_sha256") or "").lower()
            != str(assembly_media.get("sha256") or "").lower()
            or int(live_assembly.get("size_bytes") or -1)
            != int(assembly_media.get("size_bytes") or -2)):
        raise ManifestReconciliationError("A9_ASSEMBLY_MEDIA_MISMATCH")
    reconciled_at = reconciled_at_utc or datetime.now(timezone.utc).isoformat(
        timespec="seconds").replace("+00:00", "Z")
    output: dict[str, Any] = {
        "schema": "avs-owner-export-manifest/v2",
        "parent_manifest_sha256": parent_sha256,
        "export_created_at": _sanitize(manifest.get("export_created_at")),
        "manifest_reconciled_at_utc": reconciled_at,
        "artifact_count": len(output_artifacts),
        "total_bytes": total_bytes,
        "artifacts": output_artifacts,
        "acceptance_summary": _sanitize(manifest.get("acceptance_summary") or {}),
        "A9_sequence_lineage": {
            "project_id": str(queue["project_id"]),
            "study_id": str(lineage.get("study_id") or queue["project_id"]),
            "queue_id": str(queue["queue_id"]),
            "sequence_id": str(queue.get("director_sequence_id")
                                or queue.get("sequence_id") or ""),
            "assembly_id": str(live_assembly["assembly_id"]),
            "status": "READY",
            "shot_count": len(reconciled_shots),
            "shot_jobs": reconciled_shots,
        },
    }
    if "A8_2K_quality_diagnostics" in manifest:
        output["A8_2K_quality_diagnostics"] = _sanitize(
            manifest["A8_2K_quality_diagnostics"])
    canonical = json.dumps(output, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":")).encode("utf-8")
    output["manifest_sha256"] = hashlib.sha256(canonical).hexdigest()
    return output


def _fetch_live_data(api_base: str, project_id: str) -> Mapping[str, Any]:
    parsed = urlparse(api_base)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ManifestReconciliationError("API_MUST_BE_LOOPBACK_HTTP")
    url = f"{api_base.rstrip('/')}/api/projects/{quote(project_id)}/long-form"
    request = Request(url, headers={"Accept": "application/json"}, method="GET")
    try:
        opener = build_opener(_LoopbackNoRedirect())
        with opener.open(request, timeout=8) as response:
            raw = response.read(MAX_LIVE_API_BYTES + 1)
            if len(raw) > MAX_LIVE_API_BYTES:
                raise ManifestReconciliationError("A9_LIVE_API_RESPONSE_TOO_LARGE")
            payload = json.loads(raw.decode("utf-8"))
    except ManifestReconciliationError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, URLError) as exc:
        raise ManifestReconciliationError("A9_LIVE_API_UNAVAILABLE") from exc
    if not isinstance(payload, Mapping) or payload.get("ok") is not True:
        raise ManifestReconciliationError("A9_LIVE_API_RESPONSE_INVALID")
    data = payload.get("data")
    if not isinstance(data, Mapping):
        raise ManifestReconciliationError("A9_LIVE_API_RESPONSE_INVALID")
    return data


class _LoopbackNoRedirect(HTTPRedirectHandler):
    """Do not allow the loopback identity query to escape to a redirect target."""

    def redirect_request(self, req: Request, fp: Any, code: int, msg: str,
                         headers: Any, newurl: str) -> None:
        return None


def _confined_input(root: Path, candidate: Path) -> Path:
    resolved_root = root.resolve(strict=True)
    resolved = candidate if candidate.is_absolute() else resolved_root / candidate
    resolved = resolved.resolve(strict=True)
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ManifestReconciliationError("INPUT_PATH_OUTSIDE_EXPORT_ROOT") from exc
    if not resolved.is_file():
        raise ManifestReconciliationError("INPUT_MANIFEST_MISSING")
    return resolved


def _new_output(root: Path, candidate: Path) -> Path:
    resolved_root = root.resolve(strict=True)
    resolved = candidate if candidate.is_absolute() else resolved_root / candidate
    parent = resolved.parent.resolve(strict=True)
    try:
        parent.relative_to(resolved_root)
    except ValueError as exc:
        raise ManifestReconciliationError("OUTPUT_PATH_OUTSIDE_EXPORT_ROOT") from exc
    output = parent / resolved.name
    if output.name == "manifest.json":
        raise ManifestReconciliationError("SOURCE_MANIFEST_IMMUTABLE")
    if output.exists():
        raise ManifestReconciliationError("OUTPUT_ALREADY_EXISTS")
    return output


def _write_new_file(path: Path, value: Mapping[str, Any]) -> None:
    content = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    try:
        with path.open("x", encoding="utf-8", newline="\n") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
    except FileExistsError as exc:
        raise ManifestReconciliationError("OUTPUT_ALREADY_EXISTS") from exc
    except OSError as exc:
        raise ManifestReconciliationError("OUTPUT_WRITE_FAILED") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--manifest", default=Path("manifest.json"), type=Path)
    parser.add_argument("--output", required=True, type=Path,
                        help="new filename inside --root; existing files are never overwritten")
    parser.add_argument("--api-base", default="http://127.0.0.1:8788")
    args = parser.parse_args(argv)
    try:
        root = args.root.resolve(strict=True)
        source_path = _confined_input(root, args.manifest)
        output_path = _new_output(root, args.output)
        source_bytes = source_path.read_bytes()
        manifest = json.loads(source_bytes.decode("utf-8"))
        if not isinstance(manifest, Mapping):
            raise ManifestReconciliationError("SOURCE_MANIFEST_INVALID")
        lineage = manifest.get("A9_sequence_lineage")
        if not isinstance(lineage, Mapping):
            raise ManifestReconciliationError("A9_LINEAGE_MISSING")
        live_data = _fetch_live_data(args.api_base, _safe_id(lineage.get("project_id")))
        result = build_reconciled_manifest(
            manifest, root, live_data,
            parent_sha256=hashlib.sha256(source_bytes).hexdigest())
        _write_new_file(output_path, result)
        print(json.dumps({
            "status": "PASS", "artifact_count": result["artifact_count"],
            "verified_bytes": result["total_bytes"],
            "a9_shot_result_count": len(result["A9_sequence_lineage"]["shot_jobs"]),
            "manifest_sha256": result["manifest_sha256"],
            "source_manifest_modified": False,
        }, sort_keys=True))
        return 0
    except (ManifestReconciliationError, OSError, UnicodeDecodeError,
            json.JSONDecodeError) as exc:
        code = str(exc) if isinstance(exc, ManifestReconciliationError) else "MANIFEST_RECONCILIATION_FAILED"
        print(json.dumps({"status": "FAIL", "error": code}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
