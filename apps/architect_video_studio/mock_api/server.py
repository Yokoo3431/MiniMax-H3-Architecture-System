"""Stdlib HTTP server for the Architect Video Studio prototype.

Serves the static frontend + /api/* JSON contract. Localhost only. No ComfyUI,
GPU, or Native runtime interaction.
"""

from __future__ import annotations

import json
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple
from urllib.parse import urlparse

from ._paths import FRONTEND_DIR
from .store import StudioStore


class StudioServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, addr: Tuple[str, int], store: StudioStore, apis: Dict[str, object]) -> None:
        super().__init__(addr, _make_handler(store, apis))
        self.store = store
        self.apis = apis


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
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_file(self, path: Path, content_type: str) -> None:
            body = path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_json(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0:
                return {}
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
                    self._route_api(method, path, self._read_json() if method == "POST" else {})
                else:
                    self._route_static(path)
            except KeyError as exc:
                self._fail(HTTPStatus.NOT_FOUND, str(exc))
            except ValueError as exc:
                self._fail(HTTPStatus.CONFLICT, str(exc))
            except Exception as exc:  # noqa: BLE001 - prototype server boundary
                self._fail(HTTPStatus.INTERNAL_SERVER_ERROR, f"{type(exc).__name__}: {exc}")

        def do_GET(self) -> None:
            self._dispatch("GET")

        def do_POST(self) -> None:
            self._dispatch("POST")

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
        def _route_api(self, method: str, path: str, body: dict) -> None:
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
                return self._ok(apis["project"].get_project(m.group(1)))
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
            m = re.fullmatch(r"/api/projects/([^/]+)/references/([^/]+)/approve", path)
            if m and method == "POST":
                return self._ok(apis["reference"].approve_reference(m.group(1), m.group(2)))
            m = re.fullmatch(r"/api/projects/([^/]+)/references/([^/]+)/reject", path)
            if m and method == "POST":
                return self._ok(apis["reference"].reject_reference(
                    m.group(1), m.group(2), reason=body.get("reason", "")))
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
            m = re.fullmatch(r"/api/projects/([^/]+)/prompt", path)
            if m:
                if method == "GET":
                    return self._ok(apis["prompt"].get_prompt(m.group(1)))
                if method == "POST":
                    # Optional workflow override (contract surface unchanged:
                    # endpoint + response identical; absent -> intent workflow).
                    return self._ok(apis["prompt"].generate_prompt(
                        m.group(1),
                        workflow=body.get("workflow") or None))
            m = re.fullmatch(r"/api/projects/([^/]+)/jobs", path)
            if m and method == "GET":
                return self._ok(apis["job"].list_jobs(m.group(1)))
            if m and method == "POST":
                return self._ok(apis["job"].submit_job(
                    m.group(1),
                    seed=int(body.get("seed", 42)),
                    risk_reviewed=bool(body.get("risk_reviewed", False)),
                    generation_parameters=body.get("generation_parameters"),
                    camera_motion=body.get("camera_motion"),
                ))
            m = re.fullmatch(r"/api/jobs/([^/]+)", path)
            if m and method == "GET":
                return self._ok(apis["job"].get_job(m.group(1)))
            m = re.fullmatch(r"/api/jobs/([^/]+)/result", path)
            if m and method == "GET":
                return self._ok(apis["output"].get_result(m.group(1)))
            m = re.fullmatch(r"/api/jobs/([^/]+)/report", path)
            if m and method == "GET":
                return self._ok(apis["output"].get_report(m.group(1)))
            if path == "/api/catalog" and method == "GET":
                from ._paths import REPO_ROOT
                catalog = json.loads((REPO_ROOT / "configs" / "workflow_catalog.json").read_text(encoding="utf-8"))
                return self._ok(catalog)
            if path == "/api/system/environment" and method == "GET":
                return self._ok(apis["system"].environment())
            if path == "/api/system/configure" and method == "POST":
                return self._ok(apis["system"].configure(body))
            if path == "/api/system/recheck" and method == "POST":
                return self._ok(apis["system"].recheck())
            if path == "/api/system/open-comfyui" and method == "POST":
                return self._ok(apis["system"].open_comfyui())
            raise KeyError(f"unknown api route: {method} {path}")

    return Handler


def make_server(addr: Tuple[str, int], data_root: Path,
                runtime: str = "real") -> StudioServer:
    import os
    store = StudioStore(data_root)
    from .intent_api import IntentAPI
    from .job_api import JobAPI
    from .output_api import OutputAPI
    from .project_api import ProjectAPI
    from .prompt_api import PromptAPI
    from .reference_api import ReferenceAPI
    from .system_api import SystemAPI

    output_api = OutputAPI(store)
    runtime_adapter = None
    if runtime == "real":
        comfy_input_dir = os.environ.get(
            "H3_COMFY_INPUT", "<NATIVE_ROOT>/ComfyUI/input")
        from runtime.adapters.comfyui_client import ComfyUIClient
        from runtime.adapters.native_runtime_adapter import NativeRuntimeAdapter
        runtime_adapter = NativeRuntimeAdapter(
            client=ComfyUIClient(),
            comfy_input_dir=comfy_input_dir,
        )
    apis = {
        "project": ProjectAPI(store),
        "reference": ReferenceAPI(store),
        "intent": IntentAPI(store),
        "prompt": PromptAPI(store),
        "job": JobAPI(store, output_api=output_api,
                      runtime_adapter=runtime_adapter,
                      comfy_input_dir=os.environ.get(
                          "H3_COMFY_INPUT", "<NATIVE_ROOT>/ComfyUI/input")),
        "output": output_api,
        "system": SystemAPI(store),
    }
    return StudioServer(addr, store, apis)
