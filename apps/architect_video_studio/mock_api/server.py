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
from urllib.parse import parse_qs, urlparse

from ._paths import FRONTEND_DIR
from .store import StudioStore


class StudioServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, addr: Tuple[str, int], store: StudioStore,
                 apis: Dict[str, object], mode: str = "production") -> None:
        super().__init__(addr, _make_handler(store, apis))
        self.store = store
        self.apis = apis
        self.mode = mode


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

        def _send_file(self, path: Path, content_type: str, *, immutable: bool = False) -> None:
            body = path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "public, max-age=31536000, immutable" if immutable else "no-store")
            self.send_header("X-Content-Version", str(path.stat().st_mtime_ns))
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
                    self._route_api(method, path, self._read_json() if method in ("POST", "PATCH", "DELETE") else {}, parsed.query)
                else:
                    self._route_static(path)
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
            m = re.fullmatch(r"/api/projects/([^/]+)/estimate", path)
            if m and method == "POST":
                return self._ok(apis["job"].estimate(
                    m.group(1), body.get("generation_parameters")))
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
            m = re.fullmatch(r"/api/jobs/([^/]+)/detail", path)
            if m and method == "GET":
                return self._ok(apis["job"].get_job_detail(m.group(1)))
            m = re.fullmatch(r"/api/jobs/([^/]+)/retry", path)
            if m and method == "POST":
                return self._ok(apis["job"].retry_job(m.group(1)))
            m = re.fullmatch(r"/api/jobs/([^/]+)/cancel", path)
            if m and method == "POST":
                return self._ok(apis["job"].cancel(m.group(1)))
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
                return self._ok(apis["system"].open_comfyui())
            if path == "/api/system/current-workflow" and method == "GET":
                values = parse_qs(query)
                return self._ok(apis["system"].current_workflow(
                    (values.get("job_id") or [""])[0]))
            if path == "/api/system/restart-comfyui" and method == "POST":
                return self._ok(apis["system"].restart_comfyui())
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


def make_server(addr: Tuple[str, int], data_root: Path,
                runtime: str = "real", mode: Optional[str] = None) -> StudioServer:
    import os
    store = StudioStore(data_root)
    from .intent_api import IntentAPI
    from .job_api import JobAPI
    from .output_api import OutputAPI
    from .project_api import ProjectAPI
    from .prompt_api import PromptAPI
    from .reference_api import ReferenceAPI
    from .study_api import StudyAPI
    from .system_api import SystemAPI
    from runtime.adapters.runtime_paths import resolve_runtime_paths

    output_api = OutputAPI(store, allow_mock_outputs=False)
    runtime_adapter = None
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
    apis = {
        "project": ProjectAPI(store),
        "reference": ReferenceAPI(store),
        "study": StudyAPI(store),
        "intent": IntentAPI(store),
        "prompt": PromptAPI(store),
        "job": JobAPI(store, output_api=output_api,
                      runtime_adapter=runtime_adapter,
                      allow_mock_jobs=False,
                      comfy_input_dir=str(runtime_paths.input_root) if runtime_paths else None,
                      runtime_paths=runtime_paths),
        "output": output_api,
        "system": SystemAPI(store),
    }
    return StudioServer(addr, store, apis, mode=mode or ("setup" if runtime == "mock" else "production"))
