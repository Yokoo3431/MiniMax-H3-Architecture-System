#!/usr/bin/env python3
"""Owner-assisted, diagnostics-only acceptance harness for the packaged AVS.

The harness deliberately does not drive a desktop window or submit /prompt.
It prepares bounded scenarios, samples the existing control-plane APIs, and
records evidence after the owner performs the few unavoidable UI clicks.
Reports contain hashes and identifiers only; prompt text and image bytes are
never copied into an acceptance report.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_STUDIO = "http://127.0.0.1:8788"
DEFAULT_COMFY = "http://127.0.0.1:8189"
REPO_ROOT = Path(__file__).resolve().parents[1]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def sha256_file(path: Path) -> Optional[str]:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()
    except OSError:
        return None


def safe_path(path: Any) -> Optional[Dict[str, Any]]:
    """Return path identity without leaking the owner's absolute path."""
    if not path:
        return None
    raw = str(path)
    try:
        parsed = Path(raw)
        name = parsed.name or parsed.drive or ""
        is_absolute = parsed.is_absolute()
    except (OSError, ValueError):
        name, is_absolute = "", False
    return {"name": name, "absolute": is_absolute, "path_sha256": sha256_text(raw)}


def safe_identifier(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value)
    if len(text) <= 160:
        return text
    return text[:32] + "…" + sha256_text(text)[:16]


class ApiClient:
    def __init__(self, base_url: str, timeout: float = 4.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def request(self, method: str, path: str, body: Optional[dict] = None, timeout: Optional[float] = None) -> Dict[str, Any]:
        data = None
        headers = {"Accept": "application/json"}
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = Request(self.base_url + path, data=data, headers=headers, method=method)
        try:
            with urlopen(req, timeout=timeout or self.timeout) as response:
                raw = response.read()
                payload = json.loads(raw.decode("utf-8")) if raw else {}
                return {"ok": True, "status": response.status, "data": payload.get("data"),
                        "response_ok": payload.get("ok", True), "body_bytes": len(raw)}
        except HTTPError as exc:
            try:
                raw = exc.read()
                payload = json.loads(raw.decode("utf-8")) if raw else {}
                detail = payload.get("error")
            except (OSError, UnicodeDecodeError, ValueError):
                detail = None
            return {"ok": False, "status": exc.code, "error": safe_identifier(detail) or type(exc).__name__}
        except (URLError, TimeoutError, OSError) as exc:
            return {"ok": False, "status": None, "error": type(exc).__name__}


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")
    os.replace(temp, path)


def redact_prompt_record(record: Optional[dict]) -> Dict[str, Any]:
    """Keep provenance facts while excluding all prompt content."""
    if not isinstance(record, dict):
        return {"available": False}
    allowed = ("provider", "model", "engine_mode", "skill_invoked", "fallback",
               "fallback_reason", "input_fingerprint", "prompt_source", "prompt_current",
               "validator_result", "reference_asset_id", "reference_hash",
               "workflow_id", "generated_at", "output_hash", "skill_source", "skill_version")
    result = {key: record.get(key) for key in allowed if key in record}
    for key in ("optimized_prompt", "prompt", "original_intent", "natural_language"):
        result.pop(key, None)
    result["available"] = True
    return result


def redact_provider_catalog(value: Any) -> List[Dict[str, Any]]:
    entries = value if isinstance(value, list) else (value or {}).get("providers", []) if isinstance(value, dict) else []
    result = []
    for item in entries if isinstance(entries, list) else []:
        if not isinstance(item, dict):
            continue
        executable = item.get("executable") or item.get("path")
        result.append({
            "provider": safe_identifier(item.get("provider") or item.get("id") or item.get("name")),
            "available": bool(item.get("available") or item.get("installed") or item.get("callable")),
            "configured": bool(item.get("configured")),
            "multimodal": item.get("multimodal"),
            "executable_name": Path(str(executable)).name if executable else None,
            "executable_sha256": sha256_text(str(executable)) if executable else None,
        })
    return result


def process_snapshot() -> Dict[str, Any]:
    """Best-effort process evidence without opening a browser or stopping anything."""
    result: Dict[str, Any] = {"studio_pid": None, "managed_comfy_pid": None, "process_probe": "unavailable"}
    if platform.system().lower() != "windows":
        return result
    try:
        command = ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                   "Get-CimInstance Win32_Process | Select-Object ProcessId,Name,CommandLine | ConvertTo-Json -Compress"]
        completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5, check=False)
        records = json.loads(completed.stdout or "[]")
        if isinstance(records, dict):
            records = [records]
        for item in records if isinstance(records, list) else []:
            name = str(item.get("Name") or "").lower()
            line = str(item.get("CommandLine") or "")
            pid = item.get("ProcessId")
            if "architectvideostudio" in line.lower() and not result["studio_pid"]:
                result["studio_pid"] = pid
            if "launcher.py" in line.lower() and "start" in line.lower() and not result["studio_pid"]:
                result["studio_pid"] = pid
            if "comfy" in line.lower() and "--port 8189" in line.lower():
                result["managed_comfy_pid"] = pid
        result["process_probe"] = "PASS"
    except (OSError, subprocess.SubprocessError, ValueError, TypeError):
        result["process_probe"] = "UNAVAILABLE"
    return result


def extract_jobs(payload: Any) -> List[dict]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("jobs", "items", "data"):
            if isinstance(payload.get(key), list):
                return [item for item in payload[key] if isinstance(item, dict)]
    return []


def job_evidence(job: dict) -> Dict[str, Any]:
    return {key: safe_identifier(job.get(key)) for key in (
        "id", "prompt_id", "execution_workflow_sha256", "workflow_id", "state",
        "lifecycle_state", "delivery_state", "current_stage", "progress", "step", "total_steps")}


def choose_jobs(studio: ApiClient, project_id: Optional[str]) -> Tuple[Optional[dict], Optional[dict], List[dict]]:
    candidates: List[dict] = []
    projects = studio.request("GET", "/api/projects")
    project_ids = [project_id] if project_id else []
    if not project_ids and projects.get("ok"):
        for item in projects.get("data") or []:
            if isinstance(item, dict) and item.get("id"):
                project_ids.append(str(item["id"]))
    for pid in project_ids:
        response = studio.request("GET", f"/api/projects/{pid}/jobs")
        if response.get("ok"):
            candidates.extend(extract_jobs(response.get("data")))
    candidates = [job for job in candidates if job.get("id")]
    for index, first in enumerate(candidates):
        first_sha = first.get("execution_workflow_sha256")
        for second in candidates[index + 1:]:
            if second.get("execution_workflow_sha256") and second.get("execution_workflow_sha256") != first_sha:
                return first, second, candidates
    if len(candidates) >= 2:
        return candidates[0], candidates[1], candidates
    return (candidates[0] if candidates else None), None, candidates


def runtime_fingerprint(environment: Any) -> Optional[str]:
    if not isinstance(environment, dict):
        return None
    keys = ("runtime_fingerprint", "managed_runtime_fingerprint", "actual_fingerprint", "source_tree_fingerprint", "fingerprint")
    def walk(value: Any) -> Optional[str]:
        if isinstance(value, dict):
            for key in keys:
                if value.get(key):
                    return safe_identifier(value[key])
            for child in value.values():
                found = walk(child)
                if found:
                    return found
        elif isinstance(value, list):
            for child in value:
                found = walk(child)
                if found:
                    return found
        return None
    return walk(environment)


def package_evidence() -> Dict[str, Any]:
    package_candidates = [REPO_ROOT / "release" / "dist" / "ArchitectVideoStudio-RC.zip",
                          REPO_ROOT / "release" / "dist" / "ArchitectVideoStudio-Setup.exe"]
    result = []
    for path in package_candidates:
        if path.is_file():
            result.append({"name": path.name, "size": path.stat().st_size, "sha256": sha256_file(path)})
    return {"repo": safe_path(REPO_ROOT), "artifacts": result}


def estimate_evidence(studio: ApiClient, project_id: Optional[str]) -> Dict[str, Any]:
    if not project_id:
        return {"status": "OWNER_ACTION_REQUIRED", "reason": "project_id required"}
    variants = [
        ("baseline", {"duration": 4, "width": 832, "height": 480, "fps": 24, "steps": 50}),
        ("duration_plus", {"duration": 5, "width": 832, "height": 480, "fps": 24, "steps": 50}),
        ("resolution_plus", {"duration": 5, "width": 1344, "height": 768, "fps": 24, "steps": 50}),
        ("steps_plus", {"duration": 5, "width": 1344, "height": 768, "fps": 24, "steps": 60}),
    ]
    rows = []
    for label, params in variants:
        response = studio.request("POST", f"/api/projects/{project_id}/estimate",
                                  {"generation_parameters": params})
        data = response.get("data") if response.get("ok") else None
        rows.append({"label": label, "parameters": params,
                     "estimate": data if isinstance(data, dict) else None,
                     "request_status": response.get("status"),
                     "error": response.get("error")})
    values = [row.get("estimate") or {} for row in rows]
    bounds = [(item.get("lower_bound_seconds"), item.get("upper_bound_seconds")) for item in values]
    comparable = [(low, high) for low, high in bounds if isinstance(low, (int, float)) and isinstance(high, (int, float))]
    monotonic = None
    if len(comparable) == len(rows):
        monotonic = all(comparable[index][0] <= comparable[index + 1][0] and comparable[index][1] <= comparable[index + 1][1]
                        for index in range(len(comparable) - 1))
    return {"status": "PASS" if comparable and monotonic else "REVIEW",
            "rows": rows, "monotonic_under_load": monotonic}


def current_project_evidence(studio: ApiClient, project_id: Optional[str]) -> Dict[str, Any]:
    if not project_id:
        return {"status": "UNKNOWN"}
    response = studio.request("GET", f"/api/projects/{project_id}")
    data = response.get("data") if response.get("ok") else None
    if not isinstance(data, dict):
        return {"status": "UNAVAILABLE", "http": response.get("status"), "error": response.get("error")}
    prompt = data.get("prompt") or data.get("current_prompt")
    study = data.get("study") or {}
    return {"status": "PASS", "project_id": project_id,
            "current_reference_asset_id": safe_identifier(data.get("current_reference_asset_id") or study.get("current_reference_asset_id")),
            "output_directory": safe_path(data.get("output_directory") or study.get("output_directory")),
            "prompt": redact_prompt_record(prompt),
            "state": safe_identifier(data.get("state"))}


def gate_record(gate: str, action: str, before: Any, after: Any, evidence: Any, verdict: str) -> Dict[str, Any]:
    return {"gate": gate, "started_at": utc_now(), "owner_action_required": action,
            "before_state": before, "after_state": after, "evidence": evidence, "verdict": verdict}


def start_session(args: argparse.Namespace) -> int:
    session_id = args.session_id or (datetime.now().strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8])
    report_dir = Path(args.report_dir).resolve() / session_id
    report_dir.mkdir(parents=True, exist_ok=True)
    studio, comfy = ApiClient(args.studio_url), ApiClient(args.comfy_url)
    environment = studio.request("GET", "/api/system/environment", timeout=30.0)
    engine = studio.request("GET", "/api/system/engine-status")
    provider = studio.request("GET", "/api/prompt/providers")
    first, second, jobs = choose_jobs(studio, args.project_id)
    project_id = args.project_id or (args.project_id if args.project_id else None)
    if project_id is None and first:
        # Job records do not always carry project_id; use the first project only
        # for ETA/owner instructions when the caller supplied it explicitly.
        project_id = None
    plan = {
        "acceptance_session_id": session_id,
        "project_id": args.project_id,
        "created_at": utc_now(),
        "scope": "owner-assisted packaged acceptance; no desktop automation; no /prompt",
        "package": package_evidence(),
        "process": process_snapshot(),
        "studio": {"health": studio.request("GET", "/api/health"),
                   "engine": engine, "comfy_system_stats": comfy.request("GET", "/system_stats")},
        "runtime_fingerprint": runtime_fingerprint(environment.get("data")),
        "provider_catalog": redact_provider_catalog(provider.get("data")),
        "jobs": {"available": [job_evidence(item) for item in jobs],
                 "job_a": job_evidence(first) if first else None,
                 "job_b": job_evidence(second) if second else None},
        "owner_actions": {
            "A": "在打包桌面 Prompt Engine 中选择实际本地 CLI，点击测试连接；返回后运行 capture --gate a。",
            "B": "在 Job Center 先打开 Job A，再打开 Job B 的当前任务工作流；分别记录 overlay 中的 Job/SHA。",
            "C": "在打包桌面中记录 ETA 初始值，并依次修改时长、分辨率、步数；运行 capture --gate c。",
            "D": "点击选择文件夹并选测试目录；运行 capture --gate d --project-id <id> --selected-directory <path>。",
            "E": "用仅含合成输出记录的 disposable Study 分别测试保留/删除输出；运行 capture --gate e。",
            "F": "确认启动 AVS 后没有 Chrome/Edge/Firefox Comfy 页面；运行 capture --gate f。",
        },
        "notes": ["报告只保存标识、哈希、状态和路径哈希，不保存 prompt、图片或用户内容。",
                  "Job A/B 和 folder picker 的最终 UI 事实需要 owner 点击后回填；未回填不会伪判 PASS。"]
    }
    atomic_json(report_dir / "session.json", plan)
    (report_dir / "OWNER_ACTIONS.txt").write_text(
        "Architect Video Studio owner-assisted acceptance\n"
        f"session: {session_id}\n\n" + "\n".join(f"{key}: {value}" for key, value in plan["owner_actions"].items()) + "\n",
        encoding="utf-8")
    print(json.dumps({"session_id": session_id, "report_dir": safe_path(report_dir),
                      "job_a": job_evidence(first) if first else None,
                      "job_b": job_evidence(second) if second else None}, ensure_ascii=False, indent=2))
    return 0


def capture_gate(args: argparse.Namespace) -> int:
    report_dir = Path(args.report_dir).resolve() / args.session_id
    session_path = report_dir / "session.json"
    if not session_path.is_file():
        print(f"session not found: {args.session_id}", file=sys.stderr)
        return 2
    session = json.loads(session_path.read_text(encoding="utf-8"))
    studio = ApiClient(args.studio_url)
    project_id = args.project_id or session.get("project_id")
    if args.gate == "a":
        providers = studio.request("GET", "/api/prompt/providers")
        current = current_project_evidence(studio, project_id)
        selected = args.provider or None
        evidence = {"catalog": redact_provider_catalog(providers.get("data")),
                    "current_prompt_provenance": current.get("prompt"),
                    "requested_provider": selected,
                    "real_process_observed": bool(args.process_observed),
                    "fallback_used": args.fallback_used,
                    "owner_evidence_file": args.evidence_file}
        verdict = "PASS" if args.process_observed and args.fallback_used is False else "OWNER_ACTION_REQUIRED"
        record = gate_record("A_REAL_CLI_PROVIDER", "select provider, test connection, return evidence",
                             session.get("provider_catalog"), redact_provider_catalog(providers.get("data")), evidence, verdict)
    elif args.gate == "b":
        first, second, jobs = choose_jobs(studio, project_id)
        requested = studio.request("GET", f"/api/system/current-workflow?job_id={args.loaded_job_id or ''}") if args.loaded_job_id else {}
        data = requested.get("data") if isinstance(requested, dict) else None
        loaded_id = args.loaded_job_id or (data or {}).get("job_id")
        loaded_sha = args.loaded_sha or (data or {}).get("execution_workflow_sha256")
        expected = next((item for item in (first, second) if item and item.get("id") == loaded_id), None)
        identity = bool(expected and loaded_sha and loaded_sha == expected.get("execution_workflow_sha256"))
        evidence = {"job_a": job_evidence(first) if first else None, "job_b": job_evidence(second) if second else None,
                    "loaded_job_id": safe_identifier(loaded_id), "loaded_workflow_sha": safe_identifier(loaded_sha),
                    "backend_snapshot_available": bool(data), "return_control_ok": args.return_control_ok,
                    "webview_capture": args.evidence_file}
        verdict = "PASS" if identity and args.return_control_ok is not False else "OWNER_ACTION_REQUIRED"
        record = gate_record("B_NATIVE_COMFY_JOB_SWITCH", "open Job A and Job B workflow in AVS WebView",
                             {"job_a": job_evidence(first) if first else None}, evidence, evidence, verdict)
    elif args.gate == "c":
        eta = estimate_evidence(studio, project_id)
        evidence = {"eta": eta, "numeric_ws_progress": args.numeric_ws_progress,
                    "unknown_progress_ui": args.unknown_progress_ui, "ui_evidence_file": args.evidence_file}
        verdict = "PASS" if eta.get("status") == "PASS" and args.unknown_progress_ui is True else "OWNER_ACTION_REQUIRED"
        record = gate_record("C_PROGRESS_ETA", "change duration, resolution, steps and capture packaged UI",
                             None, eta, evidence, verdict)
    elif args.gate == "d":
        current = current_project_evidence(studio, project_id)
        expected = safe_path(args.selected_directory)
        persisted = current.get("output_directory")
        same = bool(expected and persisted and expected["path_sha256"] == persisted.get("path_sha256"))
        evidence = {"selected_directory": expected, "persisted_directory": persisted,
                    "reload_persisted": args.reload_persisted, "native_picker_observed": args.native_picker_observed,
                    "synthetic_collector": args.synthetic_collector}
        verdict = "PASS" if same and args.reload_persisted and args.native_picker_observed and args.synthetic_collector else "OWNER_ACTION_REQUIRED"
        record = gate_record("D_FOLDER_PICKER", "select a folder in the native Windows picker",
                             None, current, evidence, verdict)
    elif args.gate == "e":
        evidence = {"keep_outputs": args.keep_outputs, "delete_outputs": args.delete_outputs,
                    "owner_evidence_file": args.evidence_file}
        verdict = "OWNER_ACTION_REQUIRED"
        record = gate_record("E_STUDY_DELETE", "delete two disposable synthetic studies",
                             None, None, evidence, verdict)
    elif args.gate == "f":
        evidence = {"system_browser_opened": args.system_browser_opened,
                    "owner_evidence_file": args.evidence_file}
        verdict = "PASS" if args.system_browser_opened is False else "OWNER_ACTION_REQUIRED"
        record = gate_record("F_SYSTEM_BROWSER", "launch packaged AVS and observe browser processes",
                             None, None, evidence, verdict)
    else:
        raise ValueError(args.gate)
    atomic_json(report_dir / f"gate_{args.gate}.json", record)
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--studio-url", default=DEFAULT_STUDIO)
    parser.add_argument("--comfy-url", default=DEFAULT_COMFY)
    parser.add_argument("--report-dir", default=str(REPO_ROOT / "reports" / "owner_acceptance"))
    parser.add_argument("--project-id")
    sub = parser.add_subparsers(dest="command", required=True)
    start = sub.add_parser("start", help="prepare a local acceptance session")
    start.add_argument("--session-id")
    start.set_defaults(func=start_session)
    capture = sub.add_parser("capture", help="capture one gate after owner action")
    capture.add_argument("--session-id", required=True)
    capture.add_argument("--project-id", dest="project_id")
    capture.add_argument("--gate", choices=("a", "b", "c", "d", "e", "f"), required=True)
    capture.add_argument("--provider")
    capture.add_argument("--process-observed", action="store_true")
    capture.add_argument("--fallback-used", action=argparse.BooleanOptionalAction, default=None)
    capture.add_argument("--loaded-job-id")
    capture.add_argument("--loaded-sha")
    capture.add_argument("--return-control-ok", action=argparse.BooleanOptionalAction, default=None)
    capture.add_argument("--numeric-ws-progress", action=argparse.BooleanOptionalAction, default=None)
    capture.add_argument("--unknown-progress-ui", action=argparse.BooleanOptionalAction, default=None)
    capture.add_argument("--selected-directory")
    capture.add_argument("--reload-persisted", action="store_true")
    capture.add_argument("--native-picker-observed", action="store_true")
    capture.add_argument("--synthetic-collector", action="store_true")
    capture.add_argument("--system-browser-opened", action=argparse.BooleanOptionalAction, default=None)
    capture.add_argument("--keep-outputs", action="store_true")
    capture.add_argument("--delete-outputs", action="store_true")
    capture.add_argument("--evidence-file")
    capture.set_defaults(func=capture_gate)
    return parser


if __name__ == "__main__":
    parsed = build_parser().parse_args()
    raise SystemExit(parsed.func(parsed))
