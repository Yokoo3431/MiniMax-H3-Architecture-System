"""Stdlib HTTP server for the Architect Video Studio prototype.

Serves the static frontend + /api/* JSON contract. Localhost only. No ComfyUI,
GPU, or Native runtime interaction.
"""

from __future__ import annotations

import json
import hashlib
import errno
import re
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from ._paths import FRONTEND_DIR
from .store import StudioStore

_JSON_REQUEST_LIMIT_BYTES = 2 * 1024 * 1024
_REFERENCE_UPLOAD_REQUEST_LIMIT_BYTES = 65 * 1024 * 1024


class StudioServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address) -> None:
        """Avoid traceback storms when a polling client closes early."""
        error = sys.exc_info()[1]
        if isinstance(error, (BrokenPipeError, ConnectionAbortedError,
                              ConnectionResetError)):
            return
        if isinstance(error, OSError) and error.errno in (
                errno.EPIPE, errno.ECONNABORTED, errno.ECONNRESET):
            return
        super().handle_error(request, client_address)

    def __init__(self, addr: Tuple[str, int], store: StudioStore,
                 apis: Dict[str, object], mode: str = "production") -> None:
        super().__init__(addr, _make_handler(store, apis))
        self.store = store
        self.apis = apis
        self.mode = mode


def _paths_overlap(left: str | Path, right: str | Path) -> bool:
    try:
        first = Path(left).resolve()
        second = Path(right).resolve()
    except (OSError, RuntimeError, TypeError, ValueError):
        return True
    return (first == second or first in second.parents or second in first.parents)


def _experimental_io_isolated(experimental_input: str | Path,
                              experimental_output: str | Path,
                              production_input: str | Path | None,
                              production_output: str | Path | None) -> bool:
    """Fail closed unless experimental I/O is disjoint from production I/O."""
    if not all((experimental_input, experimental_output,
                production_input, production_output)):
        return False
    experimental_roots = (experimental_input, experimental_output)
    production_roots = (production_input, production_output)
    if _paths_overlap(*experimental_roots):
        return False
    return not any(_paths_overlap(experimental, production)
                   for experimental in experimental_roots
                   for production in production_roots)


def _make_handler(store: StudioStore, apis: Dict[str, object]):
    class Handler(BaseHTTPRequestHandler):
        server_version = "ArchitectVideoStudio/0.1"

        # ------------------------------------------------------------ #
        def log_message(self, fmt, *args):  # quiet console
            pass

        def _send_json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "http://127.0.0.1:8189")
            self.send_header("Vary", "Origin")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_file(self, path: Path, content_type: str, *, immutable: bool = False) -> None:
            body = path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "public, max-age=31536000, immutable" if immutable else "no-store")
            self.send_header("X-Content-Version", str(path.stat().st_mtime_ns))
            self.end_headers()
            self.wfile.write(body)

        def _send_media(self, path: Path) -> None:
            """Stream one already-authorized Job MP4, with byte ranges."""
            size = path.stat().st_size
            start, end = 0, size - 1
            status = HTTPStatus.OK
            requested = self.headers.get("Range", "").strip()
            if requested:
                match = re.fullmatch(r"bytes=(\d*)-(\d*)", requested)
                if not match or (not match.group(1) and not match.group(2)):
                    self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.end_headers()
                    return
                if match.group(1):
                    start = int(match.group(1))
                    if match.group(2):
                        end = int(match.group(2))
                    else:
                        end = min(size - 1, start + 1024 * 1024 - 1)
                else:
                    suffix_length = int(match.group(2))
                    start = max(0, size - suffix_length)
                    end = size - 1
                if start >= size or start > end:
                    self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.end_headers()
                    return
                end = min(end, size - 1)
                status = HTTPStatus.PARTIAL_CONTENT
            length = end - start + 1
            self.send_response(status)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(length))
            self.send_header("Accept-Ranges", "bytes")
            if status == HTTPStatus.PARTIAL_CONTENT:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            with path.open("rb") as stream:
                stream.seek(start)
                remaining = length
                while remaining:
                    chunk = stream.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)

        def _read_json(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0:
                return {}
            path = urlparse(self.path).path
            upload_route = re.fullmatch(
                r"/api/projects/[^/]+/references(?:/upload-approve)?", path)
            limit = (_REFERENCE_UPLOAD_REQUEST_LIMIT_BYTES if upload_route
                     else _JSON_REQUEST_LIMIT_BYTES)
            if length > limit:
                raise _RequestBodyTooLarge
            raw = self.rfile.read(length)
            return json.loads(raw.decode("utf-8") or "{}")

        def _ok(self, data: object) -> None:
            self._send_json(HTTPStatus.OK, {"ok": True, "data": data})

        def _fail(self, status: int, error: str) -> None:
            self._send_json(status, {"ok": False, "error": error})

        def _dispatch(self, method: str) -> None:
            parsed = urlparse(self.path)
            path = parsed.path
            try:
                if path.startswith("/api/"):
                    self._route_api(
                        method, path,
                        self._read_json() if method in (
                            "POST", "PUT", "PATCH", "DELETE") else {},
                        parsed.query,
                    )
                else:
                    self._route_static(path)
            except _RequestBodyTooLarge:
                self._fail(HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                           "REQUEST_BODY_TOO_LARGE")
            except KeyError as exc:
                self._fail(HTTPStatus.NOT_FOUND, str(exc))
            except ValueError as exc:
                if type(exc).__name__ == "RuntimePathError":
                    self._fail(HTTPStatus.CONFLICT, "运行环境路径无效，请前往环境修复。")
                else:
                    self._fail(HTTPStatus.CONFLICT, str(exc))
            except Exception as exc:  # noqa: BLE001 - prototype server boundary
                self._fail(HTTPStatus.INTERNAL_SERVER_ERROR, f"{type(exc).__name__}: {exc}")

        def do_GET(self) -> None:
            self._dispatch("GET")

        def do_POST(self) -> None:
            self._dispatch("POST")

        def do_PATCH(self) -> None:
            self._dispatch("PATCH")

        def do_PUT(self) -> None:
            self._dispatch("PUT")

        def do_DELETE(self) -> None:
            self._dispatch("DELETE")

        # ------------------------------------------------------------ #
        def _route_static(self, path: str) -> None:
            if path in ("/", "/index.html"):
                self._send_file(FRONTEND_DIR / "index.html", "text/html; charset=utf-8")
                return
            if path.startswith("/files/"):
                self._route_project_file(path)
                return
            rel = path.lstrip("/")
            target = (FRONTEND_DIR / rel).resolve()
            if not str(target).startswith(str(FRONTEND_DIR.resolve())):
                raise ValueError("unsafe static path")
            if not target.is_file():
                raise KeyError(f"static file not found: {path}")
            ctype = {
                ".html": "text/html; charset=utf-8",
                ".css": "text/css; charset=utf-8",
                ".js": "application/javascript; charset=utf-8",
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".webp": "image/webp",
                ".bmp": "image/bmp",
            }.get(target.suffix.lower(), "application/octet-stream")
            self._send_file(target, ctype)

        def _route_project_file(self, path: str) -> None:
            parts = path.split("/")
            # /files/<project_id>/<filename>
            if len(parts) < 4:
                raise KeyError("bad file path")
            project_id, filename = parts[2], "/".join(parts[3:])
            if "/" in filename or "\\" in filename:
                raise ValueError("unsafe filename")
            f = (store.input_dir(project_id) / filename).resolve()
            if not str(f).startswith(str(store.input_dir(project_id).resolve())):
                raise ValueError("unsafe file path")
            if not f.is_file():
                raise KeyError(f"file not found: {filename}")
            ctype = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"} \
                .get(f.suffix.lower(), "application/octet-stream")
            self._send_file(f, ctype)

        # ------------------------------------------------------------ #
        def _route_api(self, method: str, path: str, body: dict, query: str = "") -> None:
            if method == "GET" and path == "/api/health":
                return self._ok({"status": "ok", "mode": self.server.mode})
            if method == "GET" and path == "/api/projects":
                return self._ok(apis["project"].list_projects())
            if method == "POST" and path == "/api/projects":
                return self._ok(apis["project"].create_project(
                    body.get("name", ""),
                    project_type=body.get("project_type", "exterior"),
                    building_stage=body.get("building_stage", "方案"),
                ))
            m = re.fullmatch(r"/api/projects/([^/]+)", path)
            if m and method == "GET":
                return self._ok(apis["project"].get_project_detail(m.group(1)))
            if m and method == "PATCH":
                return self._ok(apis["project"].update_project(m.group(1), body))
            if m and method == "DELETE":
                return self._ok(apis["project"].delete_project(
                    m.group(1), confirm=bool(body.get("confirm")),
                    delete_outputs=bool(body.get("delete_outputs"))))
            m = re.fullmatch(r"/api/projects/([^/]+)/duplicate", path)
            if m and method == "POST":
                return self._ok(apis["project"].duplicate_project(
                    m.group(1), body.get("name")))
            m = re.fullmatch(r"/api/projects/([^/]+)/rename", path)
            if m and method == "POST":
                return self._ok(apis["project"].rename_project(
                    m.group(1), body.get("name", "")))
            m = re.fullmatch(r"/api/projects/([^/]+)/study", path)
            if m and method == "GET":
                return self._ok(apis["study"].get_state(m.group(1)))
            m = re.fullmatch(r"/api/projects/([^/]+)/director", path)
            if m and method == "GET":
                return self._ok(apis["director"].get(m.group(1)))
            if m and method == "POST":
                return self._ok(apis["director"].create(
                    m.group(1), body.get("title", "建筑分镜")))
            if m and method == "PUT":
                return self._ok(apis["director"].save(m.group(1), body))
            m = re.fullmatch(r"/api/projects/([^/]+)/director/compile", path)
            if m and method == "POST":
                return self._ok(apis["director"].compile(m.group(1), body))
            m = re.fullmatch(
                r"/api/projects/([^/]+)/director/shots/([^/]+)/retake", path)
            if m and method == "POST":
                return self._ok(apis["director"].create_retake(
                    m.group(1), m.group(2), body))
            if method == "GET" and path == "/api/capabilities/multiframe-guides":
                return self._ok(apis["guide"].capabilities())
            if method == "GET" and path == "/api/system/runtime-registry":
                return self._ok(apis["guide"].runtime_registry())
            m = re.fullmatch(r"/api/projects/([^/]+)/guide-frames/resolve", path)
            if m and method == "POST":
                params = body.get("generation_parameters") or {}
                return self._ok(apis["guide"].resolve(
                    m.group(1), duration_seconds=params.get("duration", 4.0),
                    workflow_id=body.get("workflow_id")))
            m = re.fullmatch(r"/api/projects/([^/]+)/guide-frames/reorder", path)
            if m and method == "POST":
                return self._ok(apis["guide"].reorder(
                    m.group(1), body.get("guide_ids") or []))
            m = re.fullmatch(r"/api/projects/([^/]+)/guide-frames/([^/]+)", path)
            if m and method == "PATCH":
                return self._ok(apis["guide"].update(
                    m.group(1), m.group(2), body.get("time_seconds"),
                    asset_id=body.get("asset_id")))
            if m and method == "DELETE":
                return self._ok(apis["guide"].remove(m.group(1), m.group(2)))
            m = re.fullmatch(r"/api/projects/([^/]+)/guide-frames", path)
            if m and method == "GET":
                return self._ok(apis["guide"].list(m.group(1)))
            if m and method == "POST":
                return self._ok(apis["guide"].add(
                    m.group(1), body.get("asset_id", ""), body.get("time_seconds")))
            m = re.fullmatch(r"/api/assets/([A-Za-z0-9_-]+)/content", path)
            if m and method == "GET":
                asset_path, content_type = apis["study"].asset_content(m.group(1))
                self._send_file(asset_path, content_type)
                return
            m = re.fullmatch(r"/api/projects/([^/]+)/references", path)
            if m and method == "GET":
                return self._ok(apis["reference"].list_references(m.group(1)))
            if m and method == "POST":
                return self._ok(apis["reference"].upload_reference(
                    m.group(1),
                    filename=body.get("filename", "reference.png"),
                    role=body.get("role", "first_frame"),
                    data_base64=body.get("data_base64"),
                ))
            m = re.fullmatch(r"/api/projects/([^/]+)/references/upload-approve", path)
            if m and method == "POST":
                return self._ok(apis["reference"].upload_and_approve(
                    m.group(1),
                    filename=body.get("filename", "reference.png"),
                    role=body.get("role", "first_frame"),
                    data_base64=body.get("data_base64"),
                ))
            m = re.fullmatch(r"/api/projects/([^/]+)/references/([^/]+)/approve", path)
            if m and method == "POST":
                return self._ok(apis["reference"].approve_reference(m.group(1), m.group(2)))
            m = re.fullmatch(r"/api/projects/([^/]+)/references/([^/]+)/reject", path)
            if m and method == "POST":
                return self._ok(apis["reference"].reject_reference(
                    m.group(1), m.group(2), reason=body.get("reason", "")))
            m = re.fullmatch(r"/api/projects/([^/]+)/reference-board/([^/]+)", path)
            if m and method == "POST":
                return self._ok(apis["reference"].select_role_asset(
                    m.group(1), m.group(2), body.get("asset_id", "")))
            if m and method == "DELETE":
                return self._ok(apis["reference"].clear_role_binding(
                    m.group(1), m.group(2)))
            m = re.fullmatch(r"/api/projects/([^/]+)/intent", path)
            if m:
                if method == "GET":
                    return self._ok(apis["intent"].get_intent(m.group(1)))
                if method == "POST":
                    return self._ok(apis["intent"].analyze_intent(
                        m.group(1), body.get("natural_language", "")))
            m = re.fullmatch(r"/api/projects/([^/]+)/workflow/confirm", path)
            if m and method == "POST":
                return self._ok(apis["intent"].confirm_workflow(
                    m.group(1), body.get("workflow", "")))
            m = re.fullmatch(r"/api/projects/([^/]+)/workflow/select", path)
            if m and method == "POST":
                return self._ok(apis["intent"].select_workflow(
                    m.group(1), body.get("workflow", "")))
            m = re.fullmatch(r"/api/projects/([^/]+)/prompt", path)
            if m:
                if method == "GET":
                    return self._ok(apis["prompt"].get_prompt(m.group(1)))
                if method == "POST":
                    # Optional workflow override (contract surface unchanged:
                    # endpoint + response identical; absent -> intent workflow).
                    return self._ok(apis["prompt"].generate_prompt(
                        m.group(1),
                        workflow=body.get("workflow") or None,
                        generation_parameters=body.get("generation_parameters"),
                        prompt_engine=body.get("prompt_engine") or "AUTO",
                        image_consent=bool(body.get("image_consent"))))
            if path == "/api/prompt/providers" and method == "GET":
                return self._ok(apis["prompt"].provider_catalog())
            if path == "/api/prompt/providers/configure" and method == "POST":
                return self._ok(apis["prompt"].configure_provider(body))
            if path == "/api/prompt/providers/test" and method == "POST":
                return self._ok(apis["prompt"].test_provider(body))
            m = re.fullmatch(r"/api/projects/([^/]+)/estimate", path)
            if m and method == "POST":
                return self._ok(apis["job"].estimate(
                    m.group(1), body.get("generation_parameters")))
            m = re.fullmatch(r"/api/projects/([^/]+)/jobs", path)
            preflight_match = re.fullmatch(r"/api/projects/([^/]+)/jobs/preflight", path)
            if preflight_match and method == "POST":
                return self._ok(apis["job"].submit_job(
                    preflight_match.group(1),
                    seed=int(body.get("seed", 42)),
                    risk_reviewed=bool(body.get("risk_reviewed", False)),
                    generation_parameters=body.get("generation_parameters"),
                    camera_motion=body.get("camera_motion"),
                    runtime_target=body.get("runtime_target", "production"),
                    runtime_id=body.get("runtime_id"),
                    execution_purpose=body.get("execution_purpose"),
                    director_execution=body.get("director_execution"),
                    dry_run=True,
                ))
            if m and method == "GET":
                return self._ok(apis["job"].list_jobs(m.group(1)))
            if m and method == "POST":
                return self._ok(apis["job"].submit_job(
                    m.group(1),
                    seed=int(body.get("seed", 42)),
                    risk_reviewed=bool(body.get("risk_reviewed", False)),
                    generation_parameters=body.get("generation_parameters"),
                    camera_motion=body.get("camera_motion"),
                    runtime_target=body.get("runtime_target", "production"),
                    runtime_id=body.get("runtime_id"),
                    execution_purpose=body.get("execution_purpose"),
                    director_execution=body.get("director_execution"),
                ))
            m = re.fullmatch(r"/api/jobs/([^/]+)", path)
            if m and method == "GET":
                return self._ok(apis["job"].get_job(m.group(1)))
            m = re.fullmatch(r"/api/jobs/([^/]+)/detail", path)
            if m and method == "GET":
                return self._ok(apis["job"].get_job_detail(m.group(1)))
            m = re.fullmatch(r"/api/jobs/([^/]+)/retry", path)
            if m and method == "POST":
                return self._ok(apis["job"].retry_job(m.group(1)))
            m = re.fullmatch(r"/api/jobs/([^/]+)/retry-output", path)
            if m and method == "POST":
                return self._ok(apis["job"].retry_output_delivery(m.group(1)))
            m = re.fullmatch(r"/api/jobs/([^/]+)/recover-result", path)
            if m and method == "POST":
                return self._ok(apis["job"].recover_result(m.group(1)))
            m = re.fullmatch(r"/api/jobs/([^/]+)/cancel", path)
            if m and method == "POST":
                return self._ok(apis["job"].cancel(m.group(1)))
            m = re.fullmatch(r"/api/jobs/([^/]+)/result", path)
            if m and method == "GET":
                return self._ok(apis["output"].get_result(m.group(1)))
            m = re.fullmatch(r"/api/jobs/([^/]+)/deliveries", path)
            if m and method == "GET":
                return self._ok(apis["output"].list_deliveries(m.group(1)))
            if m and method == "POST":
                return self._ok(apis["job"].create_delivery(m.group(1), body))
            m = re.fullmatch(
                r"/api/jobs/([^/]+)/deliveries/(delivery-[a-f0-9]{24})/media", path)
            if m and method == "GET":
                self._send_media(apis["output"].delivery_media_path(m.group(1), m.group(2)))
                return
            m = re.fullmatch(r"/api/jobs/([^/]+)/media", path)
            if m and method == "GET":
                job_id = m.group(1)
                try:
                    self._send_media(apis["output"].media_path(job_id))
                except Exception as exc:
                    job_api = apis.get("job")
                    if job_api is not None and hasattr(job_api, "_record_result_event"):
                        try:
                            project_id, job = store.find_job(job_id)
                            if job.get("runtime") == "native":
                                job_api._record_result_event(
                                    project_id, job_id, "HTTP_SERVING", "FAILED",
                                    error=exc, error_code="HTTP_MEDIA_SERVING_FAILURE")
                        except Exception:
                            pass
                    raise
                return
            m = re.fullmatch(r"/api/jobs/([^/]+)/report", path)
            if m and method == "GET":
                return self._ok(apis["output"].get_report(m.group(1)))
            if path == "/api/catalog" and method == "GET":
                from ._paths import REPO_ROOT
                catalog = json.loads((REPO_ROOT / "configs" / "workflow_catalog.json").read_text(encoding="utf-8"))
                return self._ok(catalog)
            if path == "/api/capabilities" and method == "GET":
                return self._ok(apis["system"].capabilities())
            if path == "/api/system/environment" and method == "GET":
                return self._ok(apis["system"].environment())
            if path == "/api/system/engine-status" and method == "GET":
                return self._ok(apis["system"].engine_status())
            if path == "/api/system/desktop-settings" and method == "GET":
                return self._ok(apis["system"].desktop_settings())
            if path == "/api/system/desktop-settings" and method == "POST":
                return self._ok(apis["system"].save_desktop_settings(body))
            if path == "/api/system/configure" and method == "POST":
                return self._ok(apis["system"].configure(body))
            if path == "/api/system/recheck" and method == "POST":
                return self._ok(apis["system"].recheck())
            if path == "/api/system/open-comfyui" and method == "POST":
                return self._ok(apis["system"].open_comfyui(
                    str(body.get("job_id") or "")))
            if path == "/api/system/current-workflow" and method == "GET":
                values = parse_qs(query)
                return self._ok(apis["system"].current_workflow(
                    (values.get("job_id") or [""])[0]))
            if path == "/api/system/verify-workflow" and method == "POST":
                return self._ok(apis["system"].verify_current_workflow(
                    str(body.get("job_id") or ""),
                    str(body.get("snapshot_id") or ""),
                    body.get("workflow"),
                ))
            if path == "/api/system/restart-comfyui" and method == "POST":
                return self._ok(apis["system"].restart_comfyui())
            if path == "/api/system/runtime-update/status" and method == "GET":
                return self._ok(apis["system"].runtime_update_status())
            if path == "/api/system/pick-folder" and method == "POST":
                return self._ok(apis["system"].pick_folder())
            if path == "/api/system/open-path" and method == "POST":
                return self._ok(apis["system"].open_path(body.get("path", "")))
            if path == "/api/system/install-plan" and method == "GET":
                return self._ok(apis["system"].install_plan())
            if path == "/api/system/install-plan" and method == "POST":
                return self._ok(apis["system"].install_plan(body))
            if path == "/api/system/repair-model-paths" and method == "POST":
                return self._ok(apis["system"].repair_model_paths())
            if path == "/api/system/install" and method == "POST":
                return self._ok(apis["system"].install(body))
            m = re.fullmatch(r"/api/system/install/([^/]+)", path)
            if m and method == "GET":
                return self._ok(apis["system"].install_job(m.group(1)))
            m = re.fullmatch(r"/api/system/install/([^/]+)/cancel", path)
            if m and method == "POST":
                return self._ok(apis["system"].cancel_install(m.group(1)))
            if path == "/api/system/repair" and method == "POST":
                return self._ok(apis["system"].repair(body))
            raise KeyError(f"unknown api route: {method} {path}")

    return Handler


class _RequestBodyTooLarge(Exception):
    """Raised before reading an over-limit JSON request body."""


def make_server(addr: Tuple[str, int], data_root: Path,
                runtime: str = "real", mode: Optional[str] = None) -> StudioServer:
    import os
    store = StudioStore(data_root)
    from .intent_api import IntentAPI
    from .guide_frame_api import GuideFrameAPI
    from .job_api import JobAPI
    from .output_api import OutputAPI
    from .project_api import ProjectAPI
    from .prompt_api import PromptAPI
    from .reference_api import ReferenceAPI
    from .study_api import StudyAPI
    from .director_api import DirectorAPI
    from .system_api import SystemAPI
    from runtime.adapters.runtime_paths import resolve_runtime_paths

    runtime_adapter = None
    experimental_runtime_adapter = None
    runtime_paths = None
    if runtime == "real":
        runtime_paths = resolve_runtime_paths(data_root)
        comfy_input_dir = str(runtime_paths.input_root)
        from runtime.adapters.comfyui_client import ComfyUIClient
        from runtime.adapters.native_runtime_adapter import NativeRuntimeAdapter
        runtime_adapter = NativeRuntimeAdapter(
            client=ComfyUIClient(
                output_root=str(runtime_paths.output_root),
                strict_output=True,
                ffmpeg_path=str(runtime_paths.ffmpeg) if runtime_paths.ffmpeg else None,
                health_timeout=5.0,
                submission_timeout=60.0,
                metadata_timeout=10.0,
                observation_timeout=15.0,
                output_timeout=30.0,
            ),
            comfy_input_dir=comfy_input_dir,
            production_binding=True,
            runtime_paths=runtime_paths,
        )
    experimental_url = os.environ.get(
        "AVS_A5_EXPERIMENTAL_URL", "http://127.0.0.1:8190").strip().rstrip("/")
    from runtime.adapters.experimental_runtime_registry import (
        inspect_experimental_runtime_registry,
    )
    experimental_registry = inspect_experimental_runtime_registry(
        data_root,
        production_input=runtime_paths.input_root if runtime_paths else None,
        production_output=runtime_paths.output_root if runtime_paths else None,
    )
    experimental_config = experimental_registry.get("config") or {}
    experimental_public = dict(experimental_registry.get("public") or {})
    production_public = {
        "runtime_id": "production-h3-8189", "runtime_role": "production",
        "backend": "comfyui", "endpoint_identity": "loopback:8189",
        "comfyui_version": "0.33.1", "comfyui_git_sha": None,
        "route_enabled": True,
        "output_root_fingerprint": (
            getattr(runtime_adapter.client, "output_root_fingerprint", None)
            if runtime_adapter else None),
    }
    production_public["config_fingerprint"] = hashlib.sha256(
        json.dumps(production_public, sort_keys=True, separators=(",", ":"))
        .encode("utf-8")).hexdigest()
    if runtime_adapter is not None:
        runtime_adapter.runtime_identity_spec = dict(production_public)
    experimental_input = str(experimental_config.get("input_root") or "")
    experimental_output = str(experimental_config.get("output_root") or "")
    experimental_url = str(experimental_config.get("endpoint") or experimental_url)
    if experimental_registry.get("valid"):
        from runtime.adapters.comfyui_client import ComfyUIClient
        from runtime.adapters.native_runtime_adapter import NativeRuntimeAdapter
        experimental_runtime_adapter = NativeRuntimeAdapter(
            client=ComfyUIClient(
                base_url=experimental_url,
                output_root=experimental_output,
                strict_output=True,
                # Experimental output validation stays inside the pinned
                # isolated venv instead of borrowing production media tools.
                video_probe_python=experimental_config.get("python_executable"),
                health_timeout=3.0,
                submission_timeout=60.0,
                metadata_timeout=5.0,
                observation_timeout=15.0,
                output_timeout=30.0,
            ),
            comfy_input_dir=experimental_input,
            production_binding=True,
        )
        experimental_runtime_adapter.runtime_identity_spec = dict(experimental_public)
        experimental_runtime_adapter.runtime_launch_contract = {
            "source_root": experimental_config.get("source_root"),
            "input_root": experimental_input,
            "output_root": experimental_output,
            "temp_root": experimental_config.get("temp_root"),
            "user_root": experimental_config.get("user_root"),
            "python_executable": experimental_config.get("python_executable"),
            "extra_model_paths_config": experimental_config.get(
                "extra_model_paths_config"),
        }
    output_api = OutputAPI(store, allow_mock_outputs=False,
                           runtime_paths=runtime_paths,
                           experimental_video_probe_python=(
                               experimental_config.get("python_executable")
                               if experimental_registry.get("valid") else None))
    from runtime.adapters.comfyui_client import ComfyUIClient
    production_guide_client = runtime_adapter.client if runtime_adapter else None
    experimental_guide_client = ComfyUIClient(
        base_url=experimental_url,
        health_timeout=1.5, metadata_timeout=2.0)
    apis = {
        "project": ProjectAPI(store),
        "reference": ReferenceAPI(store),
        "guide": GuideFrameAPI(store, production_guide_client,
                                experimental_guide_client,
                                experimental_enabled=experimental_registry.get("valid") is True,
                                production_identity=production_public,
                                experimental_identity=experimental_public),
        "study": StudyAPI(store),
        "director": DirectorAPI(store, output_api=output_api),
        "intent": IntentAPI(store),
        "prompt": PromptAPI(store),
        "job": JobAPI(store, output_api=output_api,
                      runtime_adapter=runtime_adapter,
                      experimental_runtime_adapter=experimental_runtime_adapter,
                      allow_mock_jobs=False,
                      comfy_input_dir=str(runtime_paths.input_root) if runtime_paths else None,
                      experimental_comfy_input_dir=experimental_input or None,
                      runtime_paths=runtime_paths,
                      experimental_route_enabled=(
                          experimental_registry.get("valid") is True)),
        "output": output_api,
        "system": SystemAPI(store),
    }
    return StudioServer(addr, store, apis, mode=mode or ("setup" if runtime == "mock" else "production"))
