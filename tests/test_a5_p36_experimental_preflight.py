"""A5.1-P3.6 routing and CPU-only preflight contract tests."""

from __future__ import annotations

import base64
import hashlib
import json
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from apps.architect_video_studio.mock_api.intent_api import IntentAPI  # noqa: E402
from apps.architect_video_studio.mock_api.director_api import DirectorAPI  # noqa: E402
from apps.architect_video_studio.mock_api.job_api import JobAPI  # noqa: E402
from apps.architect_video_studio.mock_api.output_api import OutputAPI  # noqa: E402
from apps.architect_video_studio.mock_api.project_api import ProjectAPI  # noqa: E402
from apps.architect_video_studio.mock_api.prompt_api import PromptAPI  # noqa: E402
from apps.architect_video_studio.mock_api.reference_api import ReferenceAPI  # noqa: E402
from apps.architect_video_studio.mock_api.server import make_server  # noqa: E402
from apps.architect_video_studio.mock_api.store import StudioStore  # noqa: E402
from runtime.adapters.experimental_runtime_registry import (  # noqa: E402
    EXPECTED_GIT_SHA, EXPECTED_PACKAGES, EXPECTED_RUNTIME_ID,
    EXPECTED_VERSION, _read_git_head, inspect_experimental_runtime_registry,
    live_runtime_executable_matches, live_runtime_process_matches,
)
from runtime.adapters.native_runtime_adapter import NativeRuntimeAdapter  # noqa: E402
from runtime.adapters.golden_workflow_binding import bind_golden_workflow  # noqa: E402
from runtime.adapters.production_workflow_binding import (  # noqa: E402
    validate_production_payload,
)
from runtime.a4_profiles import resolve_product_parameters  # noqa: E402
from runtime.multiframe_guides import guide_comfy_filename  # noqa: E402
from runtime.adapters.production_workflow_binding import (  # noqa: E402
    canonical_workflow_sha256,
)


def tiny_png(color=(255, 255, 255)) -> str:
    def chunk(tag: bytes, data: bytes) -> bytes:
        value = struct.pack(">I", len(data)) + tag + data
        return value + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    raw = b"\x00" + bytes(color)
    image = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
             + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    return base64.b64encode(image).decode("ascii")


GUIDE_INFO = {"MiniMaxH3AddGuide": {"input": {
    "required": {"positive": [], "latent": [], "frame_idx": []},
    "optional": {"image": [], "vae": []},
}}}


class FakeClient:
    def __init__(self, output_fp="a" * 24, *, object_info=None):
        self.base_url = "http://127.0.0.1:8190"
        self.output_root_fingerprint = output_fp
        self.object_info_value = GUIDE_INFO if object_info is None else object_info
        self.queue_calls = 0
        self.prompt_calls = 0

    def get_queue(self):
        self.queue_calls += 1
        return {"queue_running": [], "queue_pending": []}

    def object_info(self):
        return self.object_info_value

    def health_check(self):
        return {"available": True, "comfyui_version": EXPECTED_VERSION}

    def submit_workflow(self, *_args, **_kwargs):
        self.prompt_calls += 1
        raise AssertionError("dry-run must never call /prompt")


class FakeExperimentalAdapter:
    name = "native"

    def __init__(self, *, version=EXPECTED_VERSION, git_sha=EXPECTED_GIT_SHA,
                 config_fp="b" * 64, output_fp="a" * 24, object_info=None,
                 fail_preflight=False):
        self.client = FakeClient(output_fp, object_info=object_info)
        self.runtime_identity_spec = {
            "runtime_id": EXPECTED_RUNTIME_ID,
            "runtime_role": "experimental",
            "backend": "comfyui",
            "endpoint_identity": "loopback:8190",
            "comfyui_version": version,
            "comfyui_git_sha": git_sha,
            "config_fingerprint": config_fp,
            "output_root_fingerprint": output_fp,
            "capabilities": ["MiniMaxH3AddGuide"],
        }
        self.fail_preflight = fail_preflight
        self.prepare_calls = 0
        self.generate_calls = 0

    def preflight(self):
        if self.fail_preflight:
            raise RuntimeError("offline")
        return {"ready": True, "health": {"comfyui_version": self.runtime_identity_spec[
            "comfyui_version"]}}

    def prepare(self, request):
        self.prepare_calls += 1
        params = request.generation_parameters
        payload = {
            "1": {"class_type": "MiniMaxH3ImageToVideo", "inputs": {
                "width": int(params["width"]),
                "height": int(params["height"]),
                "length": int(params["frame_count"])}},
            "1a": {"class_type": "RandomNoise", "inputs": {
                "noise_seed": int(params["seed"])}},
            "1b": {"class_type": "KSamplerSelect", "inputs": {
                "sampler_name": str(params["sampler_mode"])}},
            "1c": {"class_type": "BasicScheduler", "inputs": {
                "steps": int(params["steps"]),
                "scheduler": "simple", "denoise": 1.0}},
            "1d": {"class_type": "CreateVideo", "inputs": {
                "fps": float(params["fps"])}},
            "2": {"class_type": "BasicGuider", "inputs": {"conditioning": ["1", 0]}},
            "3": {"class_type": "SaveVideo", "inputs": {
                "filename_prefix": "video/04_Drone_Aerial_42",
                "format": "auto", "codec": "auto", "video": ["1", 0]}},
        }
        for offset, guide in enumerate(request.guide_frames, start=4):
            image_node = str(100 + offset)
            payload[image_node] = {"class_type": "LoadImage", "inputs": {
                "image": f"guide-{offset}.png"}}
            payload[str(offset)] = {"class_type": "MiniMaxH3AddGuide", "inputs": {
                "frame_idx": guide["resolved_frame_idx"],
                "image": [image_node, 0]}}
        for offset, reference in enumerate(request.reference_assets, start=20):
            payload[str(offset)] = {"class_type": "LoadImage", "inputs": {
                "image": reference["filename"]}}
        return {"translated_payload": payload, "guide_capability": {
            "node": "MiniMaxH3AddGuide", "available": True,
            "status": "AVAILABLE", "port": 8190,
        }}

    @staticmethod
    def attach_job_identity(prepared, job_id):
        prepared["translated_payload"]["3"]["inputs"]["filename_prefix"] += f"_{job_id}"
        prepared["avs_job_id"] = job_id
        prepared["execution_workflow_sha256"] = canonical_workflow_sha256(
            prepared["translated_payload"])
        return prepared

    def generate(self, *_args, **_kwargs):
        self.generate_calls += 1
        raise AssertionError("dry-run must not call generate")


class PreflightHarness:
    def __init__(self, adapter=None, *, route_enabled=True):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.store = StudioStore(root / "data")
        self.projects = ProjectAPI(self.store)
        self.references = ReferenceAPI(self.store)
        self.intents = IntentAPI(self.store)
        self.prompts = PromptAPI(self.store)
        self.adapter = adapter or FakeExperimentalAdapter()
        self.jobs = JobAPI(
            self.store, output_api=OutputAPI(self.store),
            experimental_runtime_adapter=self.adapter,
            experimental_route_enabled=route_enabled, allow_mock_jobs=False,
        )
        self.project_id = self._ready_project()

    def _ready_project(self):
        project = self.projects.create_project("CPU preflight fixture")
        pid = project["id"]
        self.references.upload_and_approve(
            pid, "start.png", role="first_frame", data_base64=tiny_png())
        self.intents.analyze_intent(pid, "做一个建筑外观主视角展示视频")
        self.prompts.generate_prompt(
            pid, workflow="01_Exterior_Hero",
            generation_parameters={"quality": "NATIVE_HIGH", "duration": 4.0,
                                   "fps": 24, "seed": 42},
            prompt_engine="OFFLINE_COMPILER")
        guide_rows = []
        for ordinal, seconds in enumerate((1.5, 3.0), start=1):
            ref = self.references.upload_and_approve(
                pid, f"guide-{ordinal}.png", role="timeline_guide",
                data_base64=tiny_png((255, 40 * ordinal, 0)))
            guide_rows.append({
                "guide_id": f"guide-{ordinal}", "asset_id": ref["reference"]["id"],
                "role": "timeline_guide", "requested_time_seconds": seconds,
                "ordinal": ordinal,
            })
        persisted = self.store.load_project(pid)
        persisted["guide_frames"] = guide_rows
        self.store.save_project(persisted)
        return pid

    def close(self):
        self.tmp.cleanup()

    def dry_run(self, **overrides):
        args = {
            "project_id": self.project_id, "seed": 42, "risk_reviewed": True,
            "generation_parameters": {"quality": "NATIVE_HIGH", "duration": 4.0,
                                      "fps": 24, "seed": 42},
            "camera_motion": "slow_push", "runtime_target": "experimental",
            "runtime_id": EXPECTED_RUNTIME_ID,
            "execution_purpose": "A5_EXPERIMENTAL_VALIDATION", "dry_run": True,
        }
        args.update(overrides)
        return self.jobs.submit_job(**args)


class ExperimentalRegistryTests(unittest.TestCase):
    def test_live_listener_executable_must_match_pinned_python(self):
        expected = Path("C:/A5Runtime/.venv/Scripts/python.exe")
        matching = SimpleNamespace(returncode=0, stdout="MATCH", stderr="")
        wrong_executable = SimpleNamespace(
            returncode=1, stdout="NO_MATCH", stderr="")

        def run_and_check_script(*args, **kwargs):
            encoded = args[0][-1]
            script = base64.b64decode(encoded).decode("utf-16le")
            self.assertIn("$p.ExecutablePath", script)
            self.assertIn("$exe.Equals($expected", script)
            self.assertIn("Get-NetTCPConnection -LocalPort 8190", script)
            self.assertIn("--port 8190", script)
            return matching

        with patch("runtime.adapters.experimental_runtime_registry.os.name", "nt"), \
                patch("runtime.adapters.experimental_runtime_registry.Path.is_file",
                      return_value=True), \
                patch("runtime.adapters.experimental_runtime_registry.os.path.isfile",
                      return_value=True), \
                patch("runtime.adapters.experimental_runtime_registry.shutil.which",
                      return_value="C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"), \
                patch("runtime.adapters.experimental_runtime_registry.subprocess.run",
                      side_effect=run_and_check_script):
            self.assertTrue(live_runtime_executable_matches(expected))

        with patch("runtime.adapters.experimental_runtime_registry.os.name", "nt"), \
                patch("runtime.adapters.experimental_runtime_registry.Path.is_file",
                      return_value=True), \
                patch("runtime.adapters.experimental_runtime_registry.os.path.isfile",
                      return_value=True), \
                patch("runtime.adapters.experimental_runtime_registry.shutil.which",
                      return_value="C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"), \
                patch("runtime.adapters.experimental_runtime_registry.subprocess.run",
                      return_value=wrong_executable):
            self.assertFalse(live_runtime_executable_matches(expected))

    def test_registry_matches_pinned_runtime_without_exposing_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "ComfyUI"
            (source / "comfy_extras").mkdir(parents=True)
            (source / "main.py").write_text("", encoding="utf-8")
            (source / "comfyui_version.py").write_text(
                '__version__ = "0.36.0"\n', encoding="utf-8")
            (source / "comfy_extras" / "nodes_minimax_h3.py").write_text(
                "class MiniMaxH3AddGuide:\n    pass\n", encoding="utf-8")
            (source / ".git").mkdir()
            (source / ".git" / "HEAD").write_text(
                EXPECTED_GIT_SHA + "\n", encoding="ascii")
            venv = root / ".venv"
            scripts = venv / "Scripts"
            site = venv / "Lib" / "site-packages"
            scripts.mkdir(parents=True)
            site.mkdir(parents=True)
            python = scripts / "python.exe"
            python.write_bytes(b"fixture")
            (venv / "pyvenv.cfg").write_text("version = 3.12.10\n", encoding="utf-8")
            roots = {}
            for name in ("input_root", "output_root", "temp_root", "user_root", "models_root"):
                roots[name] = root / name
                roots[name].mkdir()
            config = {
                "schema_version": 1, "enabled": True,
                "runtime_id": EXPECTED_RUNTIME_ID, "runtime_role": "experimental",
                "backend": "comfyui", "endpoint": "http://127.0.0.1:8190",
                "source_root": str(source), "python_executable": str(python),
                "comfyui_version": EXPECTED_VERSION,
                "comfyui_git_sha": EXPECTED_GIT_SHA,
                "extra_model_paths_config": str(root / "extra-model-paths.yaml"),
                **{key: str(value) for key, value in roots.items()},
            }
            Path(config["extra_model_paths_config"]).write_text(
                "models: {}\n", encoding="utf-8")
            registry_file = root / "runtime.json"
            registry_file.write_text(json.dumps(config), encoding="utf-8")
            distributions = [SimpleNamespace(
                metadata={"Name": package}, version=version)
                for package, version in EXPECTED_PACKAGES.items()]
            with patch("runtime.adapters.experimental_runtime_registry.importlib.metadata.distributions",
                          return_value=distributions):
                result = inspect_experimental_runtime_registry(
                    root, registry_path=registry_file,
                    production_input=root / "prod-input",
                    production_output=root / "prod-output")
            self.assertTrue(result["valid"], result)
            self.assertTrue(result["public"]["route_enabled"])
            self.assertEqual(result["public"]["runtime_id"], EXPECTED_RUNTIME_ID)
            public_json = json.dumps(result["public"])
            self.assertNotIn(str(root), public_json)
            self.assertEqual(len(result["public"]["config_fingerprint"]), 64)

            (source / ".git" / "HEAD").write_text("0" * 40 + "\n", encoding="ascii")
            mismatched = inspect_experimental_runtime_registry(
                root, registry_path=registry_file,
                production_input=root / "prod-input",
                production_output=root / "prod-output")
            self.assertFalse(mismatched["valid"])
            self.assertEqual(mismatched["reason"],
                             "EXPERIMENTAL_RUNTIME_GIT_SHA_MISMATCH")

    def test_git_head_resolves_packed_ref_without_git_executable(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "ComfyUI"
            git_dir = source / ".git"
            git_dir.mkdir(parents=True)
            (git_dir / "HEAD").write_text(
                "ref: refs/heads/pinned-runtime\n", encoding="ascii")
            (git_dir / "packed-refs").write_text(
                f"# pack-refs with: peeled fully-peeled\n{EXPECTED_GIT_SHA} refs/heads/pinned-runtime\n",
                encoding="ascii")
            self.assertEqual(_read_git_head(source), EXPECTED_GIT_SHA)

    def test_git_head_resolves_linked_worktree_common_packed_ref(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "worktree" / "ComfyUI"
            source.mkdir(parents=True)
            common_git_dir = root / "worktree" / ".git"
            worktree_git_dir = common_git_dir / "worktrees" / "runtime"
            worktree_git_dir.mkdir(parents=True)
            (source / ".git").write_text(
                "gitdir: ../.git/worktrees/runtime\n",
                encoding="ascii")
            (worktree_git_dir / "commondir").write_text("../..\n", encoding="ascii")
            (worktree_git_dir / "HEAD").write_text(
                "ref: refs/heads/pinned-runtime\n", encoding="ascii")
            (common_git_dir / "packed-refs").write_text(
                f"{EXPECTED_GIT_SHA} refs/heads/pinned-runtime\n", encoding="ascii")
            self.assertEqual(_read_git_head(source), EXPECTED_GIT_SHA)

    def test_git_head_rejects_invalid_ref_and_returns_detached_commit(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "ComfyUI"
            git_dir = source / ".git"
            git_dir.mkdir(parents=True)
            head = git_dir / "HEAD"
            head.write_text("ref: ../outside\n", encoding="ascii")
            self.assertIsNone(_read_git_head(source))
            head.write_text("0" * 40 + "\n", encoding="ascii")
            self.assertEqual(_read_git_head(source), "0" * 40)

    def test_live_process_must_match_pinned_entry_and_isolated_roots(self):
        root = Path("C:/A5Runtime/ComfyUI")
        config = {
            "source_root": str(root), "input_root": "C:/A5Runtime/io/input",
            "output_root": "C:/A5Runtime/io/output",
            "temp_root": "C:/A5Runtime/io/temp",
            "user_root": "C:/A5Runtime/io/user",
            "extra_model_paths_config": "C:/A5Runtime/config/models.yaml",
        }
        argv = ["main.py", "--port", "8190", "--input-directory", config["input_root"],
                "--output-directory", config["output_root"], "--temp-directory",
                config["temp_root"], "--user-directory", config["user_root"],
                "--extra-model-paths-config", config["extra_model_paths_config"]]
        self.assertTrue(live_runtime_process_matches(argv, config))
        wrong = list(argv)
        wrong[wrong.index("--output-directory") + 1] = "C:/Production/output"
        self.assertFalse(live_runtime_process_matches(wrong, config))
        self.assertFalse(live_runtime_process_matches(argv + ["--port", "8191"], config))

    def test_missing_or_disabled_registry_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.assertFalse(inspect_experimental_runtime_registry(root)["valid"])


class ExperimentalPreflightTests(unittest.TestCase):
    def setUp(self):
        self.h = PreflightHarness()

    def tearDown(self):
        self.h.close()

    def test_dry_run_persists_sanitized_identity_without_creating_job_or_prompt(self):
        project_before = self.h.store.load_project(self.h.project_id)
        jobs_before = self.h.store.load_jobs(self.h.project_id)
        result = self.h.dry_run()
        self.assertEqual(result["state"], "DRY_RUN")
        self.assertEqual(result["runtime_identity"]["runtime_id"], EXPECTED_RUNTIME_ID)
        self.assertEqual(result["runtime_identity"]["runtime_role"], "experimental")
        self.assertEqual(result["runtime_identity"]["comfyui_version"], EXPECTED_VERSION)
        self.assertEqual(result["runtime_identity"]["comfyui_git_sha"], EXPECTED_GIT_SHA)
        self.assertEqual(result["guide_count"], 2)
        self.assertEqual(result["guide_frame_indexes"], [36, 72])
        self.assertEqual(result["bound_execution_parameters"]["reference_count"], 3)
        self.assertEqual(len(result["workflow_sha256"]), 64)
        self.assertIn(result["id"], result["expected_output_prefix"])
        self.assertEqual(result["submission_state"], "NOT_PERFORMED")
        self.assertFalse(result["submission_attempted"])
        self.assertEqual(self.h.adapter.client.prompt_calls, 0)
        self.assertEqual(self.h.adapter.generate_calls, 0)
        self.assertEqual(self.h.adapter.client.queue_calls, 2)
        self.assertEqual(self.h.store.load_jobs(self.h.project_id), jobs_before)
        self.assertEqual(self.h.store.load_project(self.h.project_id)["state"],
                         project_before["state"])
        self.assertFalse(self.h.jobs._threads)
        record_path = self.h.store.data_root / "preflights" / f"{result['id']}.json"
        record = json.loads(record_path.read_text(encoding="utf-8"))
        self.assertEqual(record["state"], "DRY_RUN")
        self.assertEqual(record["prompt_id"], None)
        self.assertEqual(record["runtime_identity"], result["runtime_identity"])
        self.assertEqual(record["guide_prompt_compilation"]["compiler_version"],
                         "a5.2-storyboard-timing-v1")
        self.assertEqual(record["guide_prompt_compilation"]["guide_frame_indexes"],
                         [36, 72])
        self.assertEqual(record["execution_prompt_sha256"],
                         record["guide_prompt_compilation"]["execution_prompt_sha256"])
        self.assertEqual(len(record["execution_prompt_sha256"]), 64)
        serialized = record_path.read_text(encoding="utf-8")
        self.assertNotIn("做一个建筑外观主视角展示视频", serialized)
        self.assertNotIn(str(self.h.store.data_root), serialized)
        self.assertFalse(record["private_paths_included"])

    def test_experimental_route_requires_runtime_id_and_a5_purpose(self):
        with self.assertRaisesRegex(ValueError, "EXPERIMENTAL_RUNTIME_ID_REQUIRED"):
            self.h.dry_run(runtime_id=None)
        with self.assertRaisesRegex(ValueError, "EXPERIMENTAL_JOB_NOT_AUTHORIZED"):
            self.h.dry_run(execution_purpose="PRODUCTION")
        self.assertEqual(self.h.adapter.client.prompt_calls, 0)
        self.assertEqual(self.h.store.load_jobs(self.h.project_id), {})

    def test_a7_director_preflight_is_explicit_and_never_submits(self):
        director = DirectorAPI(self.h.store)
        sequence = director.create(self.h.project_id)["sequence"]
        shot = sequence["shots"][0]
        shot["action_intent"] = "展示建筑与海岸场地关系。"
        shot["runtime_requirement"] = "experimental"
        sequence = director.save(self.h.project_id, {
            "expected_revision": sequence["revision"], "sequence": sequence,
        })["sequence"]
        shot = sequence["shots"][0]
        result = self.h.jobs.submit_job(
            self.h.project_id, seed=42, risk_reviewed=True,
            generation_parameters={"quality": "NATIVE_HIGH", "duration": 4.0,
                                   "fps": 24, "seed": 42},
            runtime_target="experimental", runtime_id=EXPECTED_RUNTIME_ID,
            execution_purpose="A7_DIRECTOR_VALIDATION",
            director_execution={"sequence_id": sequence["sequence_id"],
                                "sequence_revision": sequence["revision"],
                                "shot_id": shot["shot_id"]},
            dry_run=True)
        self.assertEqual(result["state"], "DRY_RUN")
        self.assertEqual(result["snapshot_type"],
                         "A7_DIRECTOR_EXPERIMENTAL_PREFLIGHT")
        self.assertEqual(result["execution_purpose"], "A7_DIRECTOR_VALIDATION")
        self.assertEqual(result["runtime_identity"]["runtime_id"], EXPECTED_RUNTIME_ID)
        self.assertEqual(result["guide_frame_indexes"], [36, 72])
        self.assertEqual(result["director_execution"]["shot_id"], shot["shot_id"])
        self.assertEqual(len(result["workflow_sha256"]), 64)
        self.assertIn(result["id"], result["expected_output_prefix"])
        self.assertFalse(result["submission_attempted"])
        self.assertEqual(result["submission_state"], "NOT_PERFORMED")
        self.assertEqual(self.h.adapter.client.prompt_calls, 0)
        self.assertEqual(self.h.adapter.generate_calls, 0)
        self.assertEqual(self.h.store.load_jobs(self.h.project_id), {})
        saved_sequence = director.get(self.h.project_id)["sequence"]
        self.assertIsNone(saved_sequence["shots"][0]["last_job_id"])

    def test_a7_experimental_target_rejects_missing_director_authorization(self):
        with self.assertRaisesRegex(ValueError, "EXPERIMENTAL_JOB_NOT_AUTHORIZED"):
            self.h.dry_run(execution_purpose="A7_DIRECTOR_VALIDATION")
        with self.assertRaisesRegex(ValueError, "EXPERIMENTAL_PURPOSE_TARGET_MISMATCH"):
            self.h.jobs.submit_job(
                self.h.project_id, risk_reviewed=True,
                runtime_target="production", runtime_id="production-h3-8189",
                execution_purpose="A7_DIRECTOR_VALIDATION",
                director_execution={"sequence_id": "sequence-fixture",
                                    "shot_id": "shot-fixture"},
                dry_run=True)
        self.assertEqual(self.h.adapter.client.prompt_calls, 0)
        self.assertEqual(self.h.store.load_jobs(self.h.project_id), {})

    def test_dry_run_rejects_study_gate_failure_before_compile(self):
        with patch("apps.architect_video_studio.mock_api.job_api.build_study_state",
                   return_value={"generate_allowed": False,
                                 "gate_reasons": ["reference approval is stale"]}):
            with self.assertRaisesRegex(ValueError, "PREFLIGHT_STUDY_GATES_FAILED"):
                self.h.dry_run()
        self.assertEqual(self.h.adapter.prepare_calls, 0)
        self.assertEqual(self.h.adapter.client.prompt_calls, 0)
        self.assertEqual(self.h.adapter.generate_calls, 0)
        self.assertEqual(self.h.store.load_jobs(self.h.project_id), {})

    def test_route_disabled_fingerprint_and_capability_fail_closed(self):
        disabled = PreflightHarness(route_enabled=False)
        try:
            with self.assertRaisesRegex(ValueError, "EXPERIMENTAL_ROUTE_DISABLED"):
                disabled.dry_run()
        finally:
            disabled.close()
        wrong = PreflightHarness(adapter=FakeExperimentalAdapter(git_sha="0" * 40))
        try:
            with self.assertRaisesRegex(ValueError, "EXPERIMENTAL_RUNTIME_FINGERPRINT_MISMATCH"):
                wrong.dry_run()
        finally:
            wrong.close()
        missing = PreflightHarness(adapter=FakeExperimentalAdapter(object_info={}))
        try:
            with self.assertRaisesRegex(ValueError, "GUIDE_RUNTIME_UNAVAILABLE"):
                missing.dry_run()
        finally:
            missing.close()

    def test_offline_and_wrong_live_version_reject_without_fallback(self):
        offline = PreflightHarness(adapter=FakeExperimentalAdapter(fail_preflight=True))
        try:
            with self.assertRaisesRegex(ValueError, "EXPERIMENTAL_RUNTIME_UNAVAILABLE"):
                offline.dry_run()
            self.assertIsNone(offline.jobs.runtime_adapter)
            self.assertEqual(offline.adapter.client.prompt_calls, 0)
        finally:
            offline.close()
        wrong = PreflightHarness()
        wrong.adapter.preflight = lambda: {"ready": True, "health": {
            "comfyui_version": "0.35.1"}}
        try:
            with self.assertRaisesRegex(ValueError, "EXPERIMENTAL_RUNTIME_VERSION_MISMATCH"):
                wrong.dry_run()
            self.assertEqual(wrong.adapter.client.prompt_calls, 0)
        finally:
            wrong.close()

    def test_a5_guides_never_fall_back_to_production(self):
        with self.assertRaisesRegex(ValueError, "GUIDE_RUNTIME_ISOLATION_REQUIRED"):
            self.h.jobs.submit_job(
                self.h.project_id, risk_reviewed=True,
                runtime_target="production", dry_run=True)
        self.assertEqual(self.h.store.load_jobs(self.h.project_id), {})
        self.assertEqual(self.h.adapter.client.prompt_calls, 0)

    def test_native_guide_compile_allows_unstaged_deterministic_image_names(self):
        params, _ = resolve_product_parameters(
            "04_Drone_Aerial",
            {"quality": "PREVIEW", "duration": 4.0, "fps": 24, "seed": 42},
            seed=42)
        guides = []
        for ordinal, frame_idx in enumerate((36, 72), start=1):
            asset_id = f"fixture-guide-{ordinal}"
            digest = ("A" if ordinal == 1 else "B") * 64
            guide = {
                "asset_id": asset_id, "role": "timeline_guide",
                "requested_time_seconds": frame_idx / 24,
                "resolved_frame_idx": frame_idx, "ordinal": ordinal,
                "content_sha256": digest, "approval_state": "APPROVED",
                "approval_evidence": {"state": "APPROVED"},
                "source_identity": f"reference:{asset_id}:v1:sha256:{digest}",
                "filename": f"guide-{ordinal}.png",
            }
            guide["comfy_filename"] = guide_comfy_filename(guide)
            guides.append(guide)
        request = {
            "study_id": "synthetic-study",
            "reference_assets": [{"asset_id": "fixture-start", "role": "first_frame",
                                  "path_or_ref": "fixture-start.png"}],
            "guide_frames": guides, "workflow_id": "04_Drone_Aerial",
            "camera_motion": "aerial_reveal", "generation_parameters": params,
            "prompt_payload": {"prompt": "synthetic preflight fixture"},
        }
        base = bind_golden_workflow(request, "04_Drone_Aerial")
        object_info = {
            str(node["class_type"]): {"input": {"required": {}, "optional": {}}}
            for node in base.values()
        }
        object_info["LoadImage"] = {"input": {
            "required": {"image": [["already-staged.png"], {}]}, "optional": {}}}
        object_info["MiniMaxH3AddGuide"] = {"input": {
            "required": {"positive": [], "latent": [], "frame_idx": []},
            "optional": {"image": [], "vae": []}}}
        adapter = NativeRuntimeAdapter(client=FakeClient(object_info=object_info))
        with patch("runtime.adapters.native_runtime_adapter.validate_request",
                   return_value=[]):
            prepared = adapter.prepare(request)
        checked = validate_production_payload(
            prepared["translated_payload"], object_info,
            allow_dynamic_asset_inputs=True)
        self.assertTrue(checked["ready"], checked)
        self.assertEqual(sum(node.get("class_type") == "MiniMaxH3AddGuide"
                             for node in prepared["translated_payload"].values()), 2)
        self.assertEqual(sum(node.get("class_type") == "LoadImage"
                             for node in prepared["translated_payload"].values()), 3)
        # The staged filename list intentionally excludes these dry-run names.
        self.assertTrue(all(name != "already-staged.png" for name in
                            [node["inputs"]["image"] for node in
                             prepared["translated_payload"].values()
                             if node.get("class_type") == "LoadImage"]))

    def test_prompt_id_is_durably_recorded_before_observer_poll(self):
        job_id = "job-submit-order-fixture"
        jobs = self.h.store.load_jobs(self.h.project_id)
        jobs[job_id] = {
            "id": job_id, "project_id": self.h.project_id,
            "state": "PREPARING", "prompt_id": None,
            "submission_state": "SUBMITTING", "stages": [],
        }
        self.h.store.save_jobs(self.h.project_id, jobs)
        adapter = NativeRuntimeAdapter(client=FakeClient())
        payload = {"15": {"class_type": "SaveVideo", "inputs": {
            "filename_prefix": f"video/{job_id}", "format": "auto",
            "codec": "auto", "video": ["1", 0],
        }}}
        prepared = {
            "job_id": "native-submit-order-fixture",
            "avs_job_id": job_id,
            "client_id": "test-client",
            "translated_payload": payload,
            "execution_workflow_sha256": canonical_workflow_sha256(payload),
            "control": {"history_timeout_seconds": 1, "poll_interval_seconds": 0},
        }
        sequence = []
        adapter.submit = lambda _request: "prompt-persist-before-poll"
        adapter.submission_callback = lambda info: (
            self.h.jobs._record_submission(self.h.project_id, job_id, info),
            sequence.append("persisted"),
        )

        class StopAfterPersistence(RuntimeError):
            pass

        def observed_poll(*_args, **_kwargs):
            persisted = self.h.store.load_jobs(self.h.project_id)[job_id]
            self.assertEqual(persisted["prompt_id"], "prompt-persist-before-poll")
            sequence.append("poll")
            raise StopAfterPersistence("test boundary")

        adapter.poll = observed_poll
        with self.assertRaisesRegex(StopAfterPersistence, "test boundary"):
            adapter.generate({}, prepared=prepared)
        self.assertEqual(sequence, ["persisted", "poll"])
        self.assertEqual(adapter.client.prompt_calls, 0)


class TestExperimentalMediaToolIsolation(unittest.TestCase):
    def test_experimental_comfy_client_does_not_inherit_production_ffmpeg(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            production = root / "production"
            experimental = root / "experimental"
            production_input = production / "input"
            production_output = production / "output"
            experimental_input = experimental / "input"
            experimental_output = experimental / "output"
            for path in (production_input, production_output,
                         experimental_input, experimental_output):
                path.mkdir(parents=True)
            production_ffmpeg = production / "ffmpeg.exe"
            paths = SimpleNamespace(
                input_root=production_input, output_root=production_output,
                ffmpeg=production_ffmpeg,
            )
            public = {
                "runtime_id": EXPECTED_RUNTIME_ID,
                "runtime_role": "experimental",
                "backend": "comfyui",
                "endpoint_identity": "loopback:8190",
                "comfyui_version": EXPECTED_VERSION,
                "comfyui_git_sha": EXPECTED_GIT_SHA,
                "config_fingerprint": "c" * 64,
                "output_root_fingerprint": "d" * 24,
                "capabilities": ["MiniMaxH3AddGuide"],
                "route_enabled": True,
            }
            registry = {
                "valid": True,
                "config": {
                    "endpoint": "http://127.0.0.1:8190",
                    "input_root": str(experimental_input),
                    "output_root": str(experimental_output),
                    "temp_root": str(experimental / "temp"),
                    "user_root": str(experimental / "user"),
                    "models_root": str(experimental / "models"),
                    "source_root": str(experimental / "source"),
                    "python_executable": str(experimental / "python.exe"),
                    "extra_model_paths_config": str(experimental / "models.yaml"),
                },
                "public": public,
            }
            clients = []

            def fake_client(**kwargs):
                client = SimpleNamespace(
                    base_url=kwargs.get("base_url", "http://127.0.0.1:8189"),
                    output_root=kwargs.get("output_root"),
                    output_root_fingerprint="e" * 24,
                )
                clients.append((client, kwargs))
                return client

            with patch("runtime.adapters.runtime_paths.resolve_runtime_paths",
                       return_value=paths), \
                 patch("runtime.adapters.experimental_runtime_registry.inspect_experimental_runtime_registry",
                       return_value=registry), \
                 patch("runtime.adapters.comfyui_client.ComfyUIClient",
                       side_effect=fake_client), \
                 patch("runtime.adapters.native_runtime_adapter.NativeRuntimeAdapter",
                       side_effect=lambda client, **_kwargs:
                       SimpleNamespace(client=client)):
                server = make_server(
                    ("127.0.0.1", 0), root / "userdata" / "studio", runtime="real")
                try:
                    self.assertGreaterEqual(len(clients), 3)
                    self.assertEqual(clients[0][1].get("ffmpeg_path"),
                                     str(production_ffmpeg))
                    self.assertNotIn("ffmpeg_path", clients[1][1])
                    self.assertEqual(
                        clients[1][1].get("video_probe_python"),
                        registry["config"]["python_executable"])
                    self.assertEqual(
                        server.apis["job"].output_api.experimental_video_probe_python,
                        registry["config"]["python_executable"])
                    self.assertTrue(server.apis["job"].experimental_route_enabled)
                finally:
                    server.server_close()


if __name__ == "__main__":
    unittest.main()
