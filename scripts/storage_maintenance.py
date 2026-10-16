"""Conservative, project-scoped storage inventory and temporary cleanup.

Commands: ``report`` (read-only C/D + project summary), ``scan`` (sanitized
JSON inventory; accepts explicit ``--root LABEL=PATH`` roots),
``preview-cleanup`` (read-only eligibility check), ``clean-safe-temp``
(requires ``--confirm``), and ``verify --before SNAPSHOT`` (compare free-space
and previous cleanup candidates). Use ``--help`` for bounds and options.

Cleanup is limited to old, terminal task directories registered under this
project's ``.codex_tmp`` root. It never targets models, runtimes, user caches,
Jobs, Results, Owner Export, or arbitrary system/application Temp directories.
Scans do not follow symlinks or junctions, and reports omit absolute paths.
"""

from __future__ import annotations

import argparse
import errno
import json
import os
import re
import shutil
import stat
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SCHEMA_VERSION = 1
OWNER_ID = "architect-video-studio-storage-maintenance"
TEMP_ROOT_NAME = ".codex_tmp"
MARKER_NAME = ".avs-owned-temp.json"
TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
LABEL_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
REPARSE_POINT = 0x400


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def _is_reparse_or_link(path: Path, info: os.stat_result | None = None) -> bool:
    try:
        if path.is_symlink():
            return True
        is_junction = getattr(path, "is_junction", None)
        if callable(is_junction) and is_junction():
            return True
    except OSError:
        return True
    if info is not None and getattr(info, "st_file_attributes", 0) & REPARSE_POINT:
        return True
    return False


def _within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _safe_project_temp_root(repo_root: Path, *, create: bool = False) -> Path:
    repo = Path(repo_root).resolve(strict=True)
    root = repo / TEMP_ROOT_NAME
    if create:
        root.mkdir(parents=True, exist_ok=True)
    if root.exists() and _is_reparse_or_link(root):
        raise ValueError("project temporary root cannot be a link or junction")
    resolved = root.resolve(strict=root.exists())
    if not _within(resolved, repo):
        raise ValueError("project temporary root escaped repository")
    return resolved


def _owned_temp_dir(repo_root: Path, temp_dir: Path, *, must_exist: bool = True) -> Path:
    root = _safe_project_temp_root(repo_root)
    candidate = Path(temp_dir)
    if not candidate.is_absolute():
        candidate = Path(repo_root).resolve(strict=True) / candidate
    if must_exist and not candidate.exists():
        raise FileNotFoundError("registered temporary directory does not exist")
    if candidate.exists() and _is_reparse_or_link(candidate):
        raise ValueError("temporary directory cannot be a link or junction")
    resolved = candidate.resolve(strict=must_exist)
    if resolved.parent != root or resolved == root:
        raise ValueError("temporary directory must be one direct child of project .codex_tmp")
    if not resolved.is_dir():
        raise ValueError("temporary target must be a directory")
    return resolved


def _marker_path(temp_dir: Path) -> Path:
    marker = temp_dir / MARKER_NAME
    if marker.exists() and _is_reparse_or_link(marker):
        raise ValueError("ownership marker cannot be a link")
    return marker


def register_owned_temp(
    repo_root: Path,
    temp_dir: Path,
    *,
    task_id: str,
    purpose: str,
    created_at: datetime | None = None,
) -> Path:
    """Register one direct child of ``.codex_tmp`` for future safe cleanup.

    The directory must already exist. Registration never creates an arbitrary
    temporary tree and never overwrites an existing marker.
    """
    if not TASK_ID_RE.fullmatch(task_id):
        raise ValueError("task_id must be a short opaque identifier")
    purpose = str(purpose).strip()
    if not purpose or len(purpose) > 120 or any(ord(character) < 32 for character in purpose):
        raise ValueError("purpose must be 1-120 printable characters")
    target = _owned_temp_dir(repo_root, temp_dir)
    marker = _marker_path(target)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "owner": OWNER_ID,
        "task_id": task_id,
        "purpose": purpose,
        "created_at": (created_at or _utc_now()).astimezone(timezone.utc).isoformat(),
        "state": "ACTIVE",
    }
    with marker.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, ensure_ascii=False, sort_keys=True)
        stream.write("\n")
    return marker


def complete_owned_temp(
    repo_root: Path,
    temp_dir: Path,
    *,
    completed_at: datetime | None = None,
) -> Path:
    """Mark a registered task directory complete without changing its files."""
    target = _owned_temp_dir(repo_root, temp_dir)
    marker = _marker_path(target)
    if not marker.is_file():
        raise ValueError("temporary directory is not registered")
    payload = _read_marker(marker)
    payload.pop("_created", None)
    payload.pop("_terminal_time", None)
    payload["state"] = "COMPLETE"
    payload["completed_at"] = (completed_at or _utc_now()).astimezone(timezone.utc).isoformat()
    temporary = target / f"{MARKER_NAME}.{os.getpid()}.tmp"
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, sort_keys=True)
            stream.write("\n")
        os.replace(temporary, marker)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
    return marker


def _read_marker(marker: Path) -> dict[str, Any]:
    if _is_reparse_or_link(marker):
        raise ValueError("ownership marker cannot be a link")
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("ownership marker is unreadable") from exc
    if not isinstance(payload, dict):
        raise ValueError("ownership marker has invalid shape")
    if payload.get("schema_version") != SCHEMA_VERSION or payload.get("owner") != OWNER_ID:
        raise ValueError("ownership marker is not recognized")
    if not TASK_ID_RE.fullmatch(str(payload.get("task_id", ""))):
        raise ValueError("ownership marker task id is invalid")
    if payload.get("state") not in {"ACTIVE", "COMPLETE", "FAILED"}:
        raise ValueError("ownership marker state is invalid")
    payload["_created"] = _parse_time(str(payload.get("created_at", "")))
    if payload["state"] == "ACTIVE":
        payload["_terminal_time"] = None
    else:
        terminal = payload.get("completed_at")
        if not terminal:
            raise ValueError("terminal ownership marker is missing completion time")
        payload["_terminal_time"] = _parse_time(str(terminal))
    return payload


def _tree_size_no_links(root: Path) -> tuple[int, int]:
    """Return bytes/files; reject linked content rather than following it."""
    total = files = 0
    stack = [root]
    while stack:
        current = stack.pop()
        with os.scandir(current) as entries:
            for entry in entries:
                path = Path(entry.path)
                info = entry.stat(follow_symlinks=False)
                if _is_reparse_or_link(path, info):
                    raise ValueError("temporary tree contains a link or reparse point")
                if stat.S_ISDIR(info.st_mode):
                    stack.append(path)
                elif stat.S_ISREG(info.st_mode):
                    total += info.st_size
                    files += 1
    return total, files


def preview_cleanup(
    repo_root: Path,
    *,
    older_than_days: int = 30,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Preview eligible marked temporary directories; no filesystem changes."""
    if older_than_days < 1:
        raise ValueError("retention must be at least one day")
    root = _safe_project_temp_root(repo_root)
    current = (now or _utc_now()).astimezone(timezone.utc)
    result: list[dict[str, Any]] = []
    skipped = {"unmarked": 0, "active": 0, "recent": 0, "invalid": 0, "linked": 0}
    if not root.exists():
        return {
            "status": "PASS", "root": TEMP_ROOT_NAME, "older_than_days": older_than_days,
            "candidates": result, "candidate_bytes": 0, "skipped": skipped,
        }
    for child in sorted(root.iterdir(), key=lambda item: item.name.casefold()):
        try:
            if _is_reparse_or_link(child):
                skipped["linked"] += 1
                continue
            if not child.is_dir():
                skipped["unmarked"] += 1
                continue
            marker = _marker_path(child)
            if not marker.is_file():
                skipped["unmarked"] += 1
                continue
            payload = _read_marker(marker)
            if payload["state"] not in {"COMPLETE", "FAILED"}:
                skipped["active"] += 1
                continue
            age = current - payload["_terminal_time"]
            if age < timedelta(days=older_than_days):
                skipped["recent"] += 1
                continue
            size, count = _tree_size_no_links(child)
            result.append({
                "task_id": payload["task_id"],
                "relative_path": f"{TEMP_ROOT_NAME}/{child.name}",
                "file_count": count,
                "logical_bytes": size,
                "age_days": max(0, int(age.total_seconds() // 86400)),
                "state": payload["state"],
            })
        except (OSError, ValueError):
            skipped["invalid"] += 1
    return {
        "status": "PASS", "root": TEMP_ROOT_NAME, "older_than_days": older_than_days,
        "candidates": result,
        "candidate_bytes": sum(item["logical_bytes"] for item in result),
        "skipped": skipped,
    }


def clean_safe_temp(
    repo_root: Path,
    *,
    older_than_days: int = 7,
    confirmed: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Delete only fresh-preview eligible task directories after confirmation."""
    if not confirmed:
        raise PermissionError("cleanup requires explicit --confirm")
    preview = preview_cleanup(repo_root, older_than_days=older_than_days, now=now)
    root = _safe_project_temp_root(repo_root)
    removed: list[dict[str, Any]] = []
    for item in preview["candidates"]:
        child = root / Path(item["relative_path"]).name
        # Repeat the complete safety check immediately before removal.
        target = _owned_temp_dir(repo_root, child)
        payload = _read_marker(_marker_path(target))
        if payload["state"] not in {"COMPLETE", "FAILED"}:
            raise ValueError("temporary directory is no longer terminal")
        if (now or _utc_now()).astimezone(timezone.utc) - payload["_terminal_time"] < timedelta(days=older_than_days):
            raise ValueError("temporary directory no longer meets retention")
        actual_bytes, actual_files = _tree_size_no_links(target)
        if actual_bytes != item["logical_bytes"] or actual_files != item["file_count"]:
            raise ValueError("temporary directory changed after preview")
        shutil.rmtree(target)
        if target.exists():
            raise OSError("temporary directory removal could not be verified")
        removed.append({**item, "removed": True})
    return {
        "status": "PASS", "root": TEMP_ROOT_NAME, "removed": removed,
        "freed_logical_bytes": sum(item["logical_bytes"] for item in removed),
        "skipped": preview["skipped"],
    }


def _root_identity(
    path: Path,
    info: os.stat_result | None = None,
    *,
    inode: int | None = None,
) -> tuple[int, int] | tuple[str, str]:
    # Reuse scandir's no-follow metadata. A second path-based stat can fail on
    # Windows once a deeply nested filename crosses MAX_PATH, even when the
    # DirEntry stat already succeeded.
    if info is None:
        info = path.stat(follow_symlinks=False)
    inode = inode or getattr(info, "st_ino", 0)
    if not inode and os.name == "nt":
        raw_path = os.path.abspath(os.fspath(path))
        if raw_path.startswith("\\\\?\\"):
            extended_path = raw_path
        elif raw_path.startswith("\\\\"):
            extended_path = "\\\\?\\UNC\\" + raw_path[2:]
        else:
            extended_path = "\\\\?\\" + raw_path
        # Windows DirEntry.stat/inode may omit IDs for paths near MAX_PATH.
        # The extended-length prefix lets stat retrieve the stable file ID.
        info = os.stat(extended_path, follow_symlinks=False)
        inode = getattr(info, "st_ino", 0)
    if inode:
        return int(info.st_dev), int(inode)
    return "path", os.path.normcase(str(path.absolute()))


def scan_directory(
    label: str,
    path: Path,
    *,
    max_entries: int = 200_000,
    max_depth: int = 32,
) -> dict[str, Any]:
    """Bounded, no-follow inventory. Output contains no filesystem paths."""
    if not LABEL_RE.fullmatch(label):
        raise ValueError("root label must be a short lowercase identifier")
    if max_entries < 1 or max_depth < 0:
        raise ValueError("scan limits must be positive (depth may be zero)")
    root = Path(path)
    if not root.exists():
        return {"label": label, "status": "MISSING", "file_count": 0, "logical_bytes": 0,
                "unique_file_bytes": 0, "hardlink_alias_bytes": 0, "allocated_bytes": None,
                "skipped_links": 0, "scan_errors": 0, "scan_error_codes": {}}
    if _is_reparse_or_link(root):
        return {"label": label, "status": "REJECTED_LINK", "file_count": 0, "logical_bytes": 0,
                "unique_file_bytes": 0, "hardlink_alias_bytes": 0, "allocated_bytes": None,
                "skipped_links": 1, "scan_errors": 0, "scan_error_codes": {}}
    try:
        root = root.resolve(strict=True)
    except OSError:
        return {"label": label, "status": "ERROR", "file_count": 0, "logical_bytes": 0,
                "unique_file_bytes": 0, "hardlink_alias_bytes": 0, "allocated_bytes": None,
                "skipped_links": 0, "scan_errors": 1, "scan_error_codes": {"RESOLVE_ERROR": 1}}
    if not root.is_dir():
        return {"label": label, "status": "NOT_DIRECTORY", "file_count": 0, "logical_bytes": 0,
                "unique_file_bytes": 0, "hardlink_alias_bytes": 0, "allocated_bytes": None,
                "skipped_links": 0, "scan_errors": 0, "scan_error_codes": {}}

    total = unique = alias = file_count = entries_seen = skipped_links = scan_errors = 0
    scan_error_codes: dict[str, int] = {}
    allocated = 0
    allocated_known = True
    identities: set[tuple[int, int] | tuple[str, str]] = set()
    stack: list[tuple[Path, int]] = [(root, 0)]
    truncated = False

    def record_scan_error(error: OSError) -> None:
        nonlocal scan_errors
        scan_errors += 1
        winerror = getattr(error, "winerror", None)
        code = f"WINERROR_{winerror}" if isinstance(winerror, int) else errno.errorcode.get(error.errno, "OS_ERROR")
        scan_error_codes[code] = scan_error_codes.get(code, 0) + 1

    while stack:
        current, depth = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    entries_seen += 1
                    if entries_seen > max_entries:
                        truncated = True
                        stack.clear()
                        break
                    entry_path = Path(entry.path)
                    try:
                        info = entry.stat(follow_symlinks=False)
                        if _is_reparse_or_link(entry_path, info):
                            skipped_links += 1
                            continue
                        if stat.S_ISDIR(info.st_mode):
                            if depth < max_depth:
                                stack.append((entry_path, depth + 1))
                            else:
                                truncated = True
                            continue
                        if not stat.S_ISREG(info.st_mode):
                            continue
                        size = int(info.st_size)
                        file_count += 1
                        total += size
                        # On Windows, DirEntry.stat() can report st_ino=0;
                        # DirEntry.inode() supplies the file ID without a
                        # second MAX_PATH-sensitive lookup.
                        try:
                            entry_inode = entry.inode()
                        except OSError:
                            entry_inode = 0
                        identity = _root_identity(entry_path, info, inode=entry_inode)
                        if identity in identities:
                            alias += size
                        else:
                            identities.add(identity)
                            unique += size
                        blocks = getattr(info, "st_blocks", None)
                        if blocks is None:
                            allocated_known = False
                        else:
                            allocated += int(blocks) * 512
                    except OSError as exc:
                        record_scan_error(exc)
        except OSError as exc:
            record_scan_error(exc)
    return {
        "label": label,
        "status": "PARTIAL" if truncated or scan_errors else "PASS",
        "file_count": file_count,
        "logical_bytes": total,
        "unique_file_bytes": unique,
        "hardlink_alias_bytes": alias,
        "allocated_bytes": allocated if allocated_known else None,
        "skipped_links": skipped_links,
        "scan_errors": scan_errors,
        "scan_error_codes": scan_error_codes,
        "truncated": truncated,
    }


def _volume_report(drives: Sequence[str] = ("C", "D")) -> list[dict[str, Any]]:
    result = []
    for raw in drives:
        drive = raw.strip().rstrip("\\/:").upper()
        if not re.fullmatch(r"[A-Z]", drive):
            result.append({"label": drive[:8] or "unknown", "status": "INVALID"})
            continue
        root = Path(f"{drive}:\\") if os.name == "nt" else Path("/")
        try:
            usage = shutil.disk_usage(root)
            result.append({"label": drive, "status": "PASS", "total_bytes": usage.total,
                           "used_bytes": usage.used, "free_bytes": usage.free})
        except OSError:
            result.append({"label": drive, "status": "UNAVAILABLE"})
    return result


def _parse_root_spec(value: str) -> tuple[str, Path]:
    label, separator, raw_path = value.partition("=")
    if not separator or not LABEL_RE.fullmatch(label) or not raw_path:
        raise argparse.ArgumentTypeError("root must be LABEL=PATH using a lowercase label")
    return label, Path(raw_path)


def make_report(
    repo_root: Path,
    root_specs: Iterable[tuple[str, Path]] = (),
    *,
    max_entries: int = 200_000,
    max_depth: int = 32,
) -> dict[str, Any]:
    roots = list(root_specs) or [("project", Path(repo_root))]
    labels = [label for label, _ in roots]
    if len(labels) != len(set(labels)):
        raise ValueError("root labels must be unique")
    scans = [scan_directory(label, path, max_entries=max_entries, max_depth=max_depth)
             for label, path in roots]
    cleanup = preview_cleanup(Path(repo_root), older_than_days=30)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utc_now().isoformat(),
        "drives": _volume_report(),
        "roots": scans,
        "safe_temp_preview": cleanup,
        "privacy": "absolute paths are not included",
    }


def verify_snapshot(repo_root: Path, before: Mapping[str, Any], root_specs: Iterable[tuple[str, Path]] = ()) -> dict[str, Any]:
    if before.get("schema_version") != SCHEMA_VERSION or not isinstance(before.get("drives"), list):
        raise ValueError("baseline snapshot schema is not supported")
    previous_cleanup = before.get("safe_temp_preview", {})
    if not isinstance(previous_cleanup, dict):
        raise ValueError("baseline cleanup section has invalid shape")
    after = make_report(repo_root, root_specs)
    before_free = {str(item.get("label")): item.get("free_bytes") for item in before["drives"]
                   if isinstance(item, dict) and item.get("status") == "PASS"}
    after_free = {str(item.get("label")): item.get("free_bytes") for item in after["drives"]
                  if isinstance(item, dict) and item.get("status") == "PASS"}
    deltas = {label: after_free[label] - value for label, value in before_free.items()
              if label in after_free and isinstance(value, int) and isinstance(after_free[label], int)}
    old_candidates = previous_cleanup.get("candidates", [])
    remaining = []
    safe_root = _safe_project_temp_root(repo_root)
    for candidate in old_candidates if isinstance(old_candidates, list) else []:
        if not isinstance(candidate, dict):
            continue
        relative = candidate.get("relative_path")
        if not isinstance(relative, str) or not relative.startswith(TEMP_ROOT_NAME + "/"):
            continue
        if (safe_root / Path(relative).name).exists():
            remaining.append(candidate.get("task_id", "unknown"))
    return {
        "status": "PASS" if not remaining else "PARTIAL",
        "drive_free_byte_delta": deltas,
        "previous_cleanup_candidates_remaining": remaining,
        "after": after,
    }


def _format_report(report: Mapping[str, Any]) -> str:
    lines = ["Storage inventory (read-only)", "Drives:"]
    for drive in report.get("drives", []):
        if drive.get("status") == "PASS":
            lines.append(
                f"  {drive['label']}: free {drive['free_bytes'] / (1024**3):.2f} GiB / "
                f"total {drive['total_bytes'] / (1024**3):.2f} GiB"
            )
        else:
            lines.append(f"  {drive.get('label', 'unknown')}: {drive.get('status', 'UNKNOWN')}")
    lines.append("Roots (per-root totals; roots may overlap):")
    for root in report.get("roots", []):
        lines.append(
            f"  {root['label']}: {root['status']}; files={root['file_count']}; "
            f"logical={root['logical_bytes'] / (1024**3):.2f} GiB; "
            f"unique={root['unique_file_bytes'] / (1024**3):.2f} GiB; "
            f"hardlink aliases={root['hardlink_alias_bytes'] / (1024**3):.2f} GiB"
        )
        if root.get("status") == "PARTIAL":
            lines.append(
                f"    bounded/incomplete scan: errors={root.get('scan_errors', 0)}, "
                f"codes={root.get('scan_error_codes', {})}, "
                f"truncated={bool(root.get('truncated', False))}"
            )
    preview = report.get("safe_temp_preview", {})
    lines.append(
        f"Safe temp preview (>={preview.get('older_than_days', 30)} days, registered and terminal only): "
        f"{len(preview.get('candidates', []))} candidates, "
        f"{preview.get('candidate_bytes', 0) / (1024**3):.2f} GiB"
    )
    lines.append(str(report.get("privacy", "")))
    return "\n".join(lines)


def _emit(value: Mapping[str, Any], *, pretty: bool = True) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2 if pretty else None, sort_keys=True))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("scan", "report", "preview-cleanup", "clean-safe-temp", "verify"))
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--root", action="append", type=_parse_root_spec, default=[], metavar="LABEL=PATH",
                        help="additional inventory root; output includes the label, never the path")
    parser.add_argument("--max-entries", type=int, default=200_000)
    parser.add_argument("--max-depth", type=int, default=32)
    parser.add_argument("--older-than-days", type=int, default=None)
    parser.add_argument("--confirm", action="store_true", help="required for clean-safe-temp")
    parser.add_argument("--before", type=Path, help="baseline JSON snapshot for verify")
    parser.add_argument("--output", type=Path, help="optional sanitized JSON output file")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    repo_root = args.repo_root.resolve()
    try:
        if args.command in {"scan", "report"}:
            report = make_report(repo_root, args.root, max_entries=args.max_entries, max_depth=args.max_depth)
            if args.command == "report":
                print(_format_report(report))
            else:
                _emit(report)
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return 0 if all(item.get("status") in {"PASS", "MISSING"} for item in report["roots"]) else 2
        if args.command == "preview-cleanup":
            days = 30 if args.older_than_days is None else args.older_than_days
            _emit(preview_cleanup(repo_root, older_than_days=days))
            return 0
        if args.command == "clean-safe-temp":
            days = 7 if args.older_than_days is None else args.older_than_days
            result = clean_safe_temp(repo_root, older_than_days=days, confirmed=args.confirm)
            _emit(result)
            return 0
        if not args.before:
            raise ValueError("verify requires --before <scan-snapshot.json>")
        before = json.loads(args.before.read_text(encoding="utf-8"))
        result = verify_snapshot(repo_root, before, args.root)
        _emit(result)
        return 0 if result["status"] == "PASS" else 2
    except (OSError, ValueError, PermissionError) as exc:
        print(f"storage-maintenance: {type(exc).__name__}; details withheld to avoid path disclosure", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
