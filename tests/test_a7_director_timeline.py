"""A7 Director shot, compiler, and retake lineage CPU contracts."""

from __future__ import annotations

import copy
import base64
import hashlib
import json
import struct
import sys
import tempfile
import threading
import unittest
from urllib.error import HTTPError
import urllib.request
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from apps.architect_video_studio.mock_api.director_api import DirectorAPI  # noqa: E402
from apps.architect_video_studio.mock_api.server import make_server  # noqa: E402
from apps.architect_video_studio.mock_api.store import StudioStore  # noqa: E402
from runtime.director_timeline import (  # noqa: E402
    DirectorTimelineError, compile_shot, new_shot, normalize_sequence,
)


def fixture_ref(asset_id="asset-1", project_id="project-1", state="APPROVED"):
    digest = hashlib.sha256(asset_id.encode()).hexdigest()
    return {"id": asset_id, "project_id": project_id, "state": state,
            "role": "first_frame", "sha256": digest,
            "source_identity": f"sha256:{digest}"}


def fixture_shot(**overrides):
    value = new_shot(title="总览镜头")
    value.update({"action_intent": "从海岸上空展示驿站建筑与场地关系。"})
    value.update(overrides)
    return value


def tiny_png_base64() -> str:
    def chunk(tag: bytes, data: bytes) -> bytes:
        payload = struct.pack(">I", len(data)) + tag + data
        return payload + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
           + chunk(b"IDAT", zlib.compress(b"\x00\xff\xff\xff"))
           + chunk(b"IEND", b""))
    return base64.b64encode(png).decode("ascii")


def request_json(url: str, method: str = "GET", body=None) -> dict:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        url, data=data, method=method,
        headers={"Content-Type": "application/json"} if data is not None else {})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            envelope = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise AssertionError(exc.read().decode("utf-8", errors="replace")) from exc
    if not envelope.get("ok"):
        raise AssertionError(envelope)
    return envelope["data"]


class DirectorFrontendRegressionTests(unittest.TestCase):
    def test_guide_count_is_declared_before_runtime_selector_uses_it(self):
        source = (ROOT / "apps" / "architect_video_studio" / "frontend" /
                  "js" / "workspace.js").read_text(encoding="utf-8")
        start = source.index("const cards = shots.map((shot, index) => {")
        end = source.index("timelineOffset += effective;", start)
        shot_renderer = source[start:end]
        declaration = shot_renderer.index("const guideCount")
        first_reference = shot_renderer.index("guideCount")
        self.assertEqual(first_reference, declaration + len("const "))


class DirectorTimelineCompilerTests(unittest.TestCase):
    def setUp(self):
        self.base_prompt = {
            "workflow": "01_Exterior_Hero", "mode": "I2VA",
            "prompt": "integrated_multimodal_description: <Picture 1> is fully referenced. A coastal visitor pavilion.",
            "prompt_hash": "base", "verified": {"pass": True},
            "reference_bindings": [{"asset_id": "asset-1", "role": "first_frame"}],
        }
        self.references = {"asset-1": fixture_ref()}
        self.shot = fixture_shot(reference_asset_ids=["asset-1"])

    def compile(self, shot=None):
        return compile_shot(
            self.base_prompt, shot or self.shot,
            {"duration": 4.0, "quality": "NATIVE_HIGH", "fps": 24, "seed": 42},
            workflow_id="01_Exterior_Hero", project_id="project-1",
            references=self.references, guide_frames=[])

    def test_compiler_is_deterministic_and_records_real_h3_frame_lattice(self):
        first = self.compile()
        second = self.compile()
        self.assertEqual(first["prompt"]["prompt"], second["prompt"]["prompt"])
        self.assertEqual(first["prompt"]["prompt_hash"], second["prompt"]["prompt_hash"])
        self.assertEqual(first["provenance"]["resolved_frame_count"], 107)
        self.assertEqual(first["provenance"]["effective_duration_seconds"], 4.458333)
        self.assertEqual(first["provenance"]["camera_intent_type"], "PROMPT_CAMERA_INTENT")
        self.assertIn("not geometric camera control", first["compiled_fragment"])
        self.assertEqual(first["provenance"]["reference_bindings"][0]["content_sha256"],
                         self.references["asset-1"]["sha256"])

    def test_camera_change_only_changes_director_compiled_fragment(self):
        before = self.compile()
        changed = fixture_shot(reference_asset_ids=["asset-1"], camera_intent="slow_push")
        after = self.compile(changed)
        self.assertNotEqual(before["prompt"]["prompt_hash"], after["prompt"]["prompt_hash"])
        self.assertNotEqual(before["provenance"]["shot_sha256"], after["provenance"]["shot_sha256"])
        self.assertEqual(before["generation_parameters"], after["generation_parameters"])
        frozen = fixture_shot(
            reference_asset_ids=["asset-1"],
            generation_settings={"quality": "NATIVE_HIGH", "fps": 24, "seed": 42})
        with self.assertRaisesRegex(DirectorTimelineError,
                                   "DIRECTOR_SETTINGS_MISMATCH"):
            compile_shot(
                self.base_prompt, frozen,
                {"duration": 4.0, "quality": "NATIVE_HIGH", "seed": 43},
                workflow_id="01_Exterior_Hero", project_id="project-1",
                references=self.references, guide_frames=[])
        source = (ROOT / "apps/architect_video_studio/frontend/js/workspace.js").read_text(
            encoding="utf-8")
        self.assertIn("timelineOffset += effective;", source)
        self.assertIn("shot.generation_settings?.seed", source)

    def test_rejects_unapproved_cross_project_missing_and_unbound_references(self):
        for ref, code in (
            (fixture_ref(state="PENDING"), "DIRECTOR_REFERENCE_NOT_APPROVED"),
            (fixture_ref(project_id="another-project"), "DIRECTOR_REFERENCE_CROSS_PROJECT"),
        ):
            with self.subTest(code=code):
                with self.assertRaisesRegex(DirectorTimelineError, code):
                    compile_shot(self.base_prompt, self.shot,
                                 {"duration": 4, "quality": "NATIVE_HIGH"},
                                 workflow_id="01_Exterior_Hero", project_id="project-1",
                                 references={"asset-1": ref}, guide_frames=[])
        with self.assertRaisesRegex(DirectorTimelineError, "DIRECTOR_REFERENCE_MISSING"):
            compile_shot(self.base_prompt, self.shot,
                         {"duration": 4, "quality": "NATIVE_HIGH"},
                         workflow_id="01_Exterior_Hero", project_id="project-1",
                         references={}, guide_frames=[])
        wrong = fixture_shot(reference_asset_ids=[])
        with self.assertRaisesRegex(DirectorTimelineError, "DIRECTOR_REFERENCE_SELECTION_MISMATCH"):
            self.compile(wrong)

    def test_rejects_invalid_camera_duration_settings_and_partial_guide_selection(self):
        for shot, code in (
            (fixture_shot(camera_intent="free_camera"), "DIRECTOR_CAMERA_INTENT_INVALID"),
            (fixture_shot(duration_seconds=3.99), "DIRECTOR_DURATION_INVALID"),
        ):
            with self.subTest(code=code):
                with self.assertRaisesRegex(DirectorTimelineError, code):
                    normalize_sequence({"shots": [shot]}, "project-1")
        with self.assertRaisesRegex(DirectorTimelineError, "DIRECTOR_SETTINGS_MISMATCH"):
            compile_shot(self.base_prompt, self.shot,
                         {"duration": 5, "quality": "NATIVE_HIGH"},
                         workflow_id="01_Exterior_Hero", project_id="project-1",
                         references=self.references, guide_frames=[])
        with self.assertRaisesRegex(DirectorTimelineError, "DIRECTOR_GUIDE_SELECTION_UNSUPPORTED"):
            compile_shot(
                self.base_prompt, fixture_shot(reference_asset_ids=["asset-1"],
                                                guide_asset_ids=["guide-a"]),
                {"duration": 4, "quality": "NATIVE_HIGH"},
                workflow_id="01_Exterior_Hero", project_id="project-1",
                references=self.references,
                guide_frames=[{"guide_id": "guide-a"}, {"guide_id": "guide-b"}])

    def test_sequence_reorder_changes_order_but_preserves_shot_identity(self):
        first, second = fixture_shot(), fixture_shot()
        normalized = normalize_sequence({"shots": [first, second]}, "project-1")
        reversed_sequence = normalize_sequence(
            {**normalized, "shots": list(reversed(normalized["shots"]))}, "project-1")
        self.assertEqual(reversed_sequence["shots"][0]["shot_id"], second["shot_id"])
        self.assertEqual(reversed_sequence["shots"][1]["shot_id"], first["shot_id"])
        self.assertEqual([s["ordinal"] for s in reversed_sequence["shots"]], [0, 1])


class DirectorAPIContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = StudioStore(Path(self.temp.name))
        self.store.save_project({"id": "project-1", "name": "fixture",
                                 "guide_frames": []})
        self.store.save_references("project-1", {"asset-1": fixture_ref()})
        self.store.save_prompt("project-1", {
            "workflow": "01_Exterior_Hero", "mode": "I2VA",
            "prompt": "A coastal architecture study.", "prompt_hash": "base",
            "verified": {"pass": True},
            "reference_bindings": [{"asset_id": "asset-1", "role": "first_frame"}],
        })
        self.output_api = type("Output", (), {
            "get_result": lambda _self, job_id: {
                "job_id": job_id, "output": {"available": True,
                                                "media_url": f"/api/jobs/{job_id}/media"}}
        })()
        self.api = DirectorAPI(self.store, self.output_api)

    def tearDown(self):
        self.temp.cleanup()

    def test_new_sequence_inherits_verified_prompt_quality_and_duration(self):
        prompt = self.store.load_prompt("project-1")
        prompt["generation_parameters"] = {"quality": "PREVIEW", "duration": 6.0}
        self.store.save_prompt("project-1", prompt)

        created = self.api.create("project-1")
        shot = created["sequence"]["shots"][0]

        self.assertEqual(shot["generation_settings"]["quality"], "PREVIEW")
        self.assertEqual(shot["duration_seconds"], 6.0)

    def test_create_compile_and_retake_preserve_immutable_source_lineage(self):
        created = self.api.create("project-1")
        sequence = created["sequence"]
        shot = sequence["shots"][0]
        shot["action_intent"] = "Reveal the coastal pavilion."
        shot["reference_asset_ids"] = ["asset-1"]
        sequence = self.api.save("project-1", {
            "expected_revision": sequence["revision"], "sequence": sequence})["sequence"]
        compiled = self.api.compile("project-1", {
            "sequence_id": sequence["sequence_id"],
            "sequence_revision": sequence["revision"],
            "shot_id": shot["shot_id"],
            "generation_parameters": {"duration": 4, "quality": "NATIVE_HIGH", "seed": 42},
        })
        self.assertFalse(compiled["submission_performed"])
        self.assertEqual(compiled["director_provenance"]["shot_id"], shot["shot_id"])
        self.assertIn("Timeline:", compiled["compiled_fragment"])
        with self.assertRaisesRegex(DirectorTimelineError,
                                   "DIRECTOR_SEQUENCE_STALE_REVISION"):
            self.api.compile("project-1", {
                "sequence_id": sequence["sequence_id"],
                "sequence_revision": sequence["revision"] - 1,
                "shot_id": shot["shot_id"],
                "generation_parameters": {
                    "duration": 4, "quality": "NATIVE_HIGH", "seed": 42,
                },
            })
        original_contract = copy.deepcopy(sequence["shots"][0])
        original_contract["last_job_id"] = "job-source"
        sequence["shots"][0] = original_contract
        sequence["revision"] += 1
        self.store.save_json(self.store.project_dir("project-1") / "director.json", sequence)
        self.store.save_jobs("project-1", {"job-source": {
            "id": "job-source", "project_id": "project-1", "state": "COMPLETED",
            "seed": 42,
            "generation_parameters": {"quality": "NATIVE_HIGH", "duration": 4.0},
            "execution_workflow_sha256": "a" * 64,
            "director_execution": {"sequence_id": sequence["sequence_id"],
                                   "shot_id": shot["shot_id"]},
        }})
        retake_result = self.api.create_retake("project-1", shot["shot_id"], {
            "sequence_id": sequence["sequence_id"],
            "source_job_id": "job-source", "retake_reason": "相机方向微调",
            "changes": {"camera_intent": "slow_push"},
        })
        retake = retake_result["shot"]
        self.assertNotEqual(retake["shot_id"], shot["shot_id"])
        self.assertEqual(retake["camera_intent"], "slow_push")
        self.assertEqual(retake["lineage"]["source_job_id"], "job-source")
        self.assertEqual(retake["lineage"]["changed_fields"], ["camera_intent"])
        self.assertEqual(retake["generation_settings"]["seed"], 42)
        after = self.api.get("project-1")["sequence"]
        self.assertEqual(after["shots"][0]["camera_intent"], "static")
        self.assertEqual(after["shots"][0]["last_job_id"], "job-source")
        self.assertEqual(after["shots"][0]["generation_settings"]["seed"], 42)
        tampered = copy.deepcopy(after)
        tampered["shots"][1]["lineage"]["retake_reason"] = "rewritten provenance"
        with self.assertRaisesRegex(DirectorTimelineError,
                                   "DIRECTOR_RETAKE_LINEAGE_IMMUTABLE"):
            self.api.save("project-1", {
                "expected_revision": after["revision"], "sequence": tampered,
            })

    def test_executed_shot_cannot_be_edited_in_place(self):
        sequence = self.api.create("project-1")["sequence"]
        shot = sequence["shots"][0]
        shot["action_intent"] = "Reveal the pavilion."
        shot["last_job_id"] = "job-source"
        sequence = self.api.save("project-1", {
            "sequence": sequence, "expected_revision": sequence["revision"]})["sequence"]
        sequence["shots"][0]["camera_intent"] = "orbit"
        with self.assertRaisesRegex(DirectorTimelineError, "DIRECTOR_EXECUTED_SHOT_IMMUTABLE"):
            self.api.save("project-1", {"sequence": sequence,
                                         "expected_revision": sequence["revision"]})

    def test_retake_rejects_non_completed_or_unrelated_source_jobs(self):
        sequence = self.api.create("project-1")["sequence"]
        shot = sequence["shots"][0]
        with self.assertRaisesRegex(DirectorTimelineError, "DIRECTOR_RETAKE_SOURCE_JOB_NOT_FOUND"):
            self.api.create_retake("project-1", shot["shot_id"], {
                "source_job_id": "not-a-job", "retake_reason": "test",
                "changes": {"camera_intent": "slow_push"},
            })


class DirectorHTTPAndJobIntegrationTests(unittest.TestCase):
    """Exercise real Studio routes with temporary data and the non-GPU mock backend."""

    def test_api_compile_and_job_snapshot_keep_director_provenance_without_prompt(self):
        with tempfile.TemporaryDirectory() as temp:
            server = make_server(("127.0.0.1", 0), Path(temp), runtime="mock")
            # Explicitly enable the repository's CPU-only mock Job sink; it
            # persists the Job contract but cannot contact Comfy /prompt.
            server.apis["job"].allow_mock_jobs = True
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                project = request_json(base + "/api/projects", "POST", {
                    "name": "A7 synthetic fixture"})
                project_id = project["id"]
                approved = request_json(
                    base + f"/api/projects/{project_id}/references/upload-approve",
                    "POST", {"filename": "synthetic.png", "role": "first_frame",
                             "data_base64": tiny_png_base64()})
                self.assertEqual(approved["reference"]["state"], "APPROVED")
                request_json(base + f"/api/projects/{project_id}/intent", "POST", {
                    "natural_language": "展示海岸建筑与场地关系"})
                request_json(base + f"/api/projects/{project_id}/prompt", "POST", {})

                director_url = base + f"/api/projects/{project_id}/director"
                sequence = request_json(director_url, "POST", {"title": "合成验收"})[
                    "sequence"]
                shot = sequence["shots"][0]
                shot["action_intent"] = "从海岸上空展示建筑与场地关系。"
                sequence = request_json(director_url, "PUT", {
                    "expected_revision": sequence["revision"],
                    "sequence": sequence})["sequence"]

                compile_result = request_json(
                    base + f"/api/projects/{project_id}/director/compile", "POST", {
                        "sequence_id": sequence["sequence_id"],
                        "sequence_revision": sequence["revision"],
                        "shot_id": shot["shot_id"],
                        "generation_parameters": {
                            "duration": 4.0, "quality": "NATIVE_HIGH",
                            "fps": 24, "seed": 42,
                        },
                    })
                self.assertFalse(compile_result["submission_performed"])
                self.assertEqual(compile_result["director_provenance"]["resolved_frame_count"], 107)
                self.assertEqual(compile_result["execution_prompt"],
                                 compile_result["compiled_prompt"])
                self.assertEqual(compile_result["source_prompt_hash"],
                                 server.apis["prompt"].store.load_prompt(
                                     project_id)["prompt_hash"])

                queue = request_json(
                    base + f"/api/projects/{project_id}/long-form", "POST", {})

                created = request_json(base + f"/api/projects/{project_id}/jobs", "POST", {
                    "seed": 42, "risk_reviewed": True,
                    "generation_parameters": {
                        "duration": 4.0, "quality": "NATIVE_HIGH", "fps": 24,
                    },
                    "director_execution": {
                        "sequence_id": sequence["sequence_id"],
                        "sequence_revision": sequence["revision"],
                        "shot_id": shot["shot_id"],
                    },
                    "long_form_execution": {
                        "queue_id": queue["queue_id"], "shot_id": shot["shot_id"],
                    },
                })
                job = created.get("job", created)
                self.assertEqual(job["runtime"], "mock")
                self.assertEqual(job["director_execution"]["shot_id"], shot["shot_id"])
                self.assertEqual(job["prompt_snapshot"]["prompt"],
                                 compile_result["execution_prompt"])
                self.assertIn("Director shot:", job["prompt_snapshot"]["prompt"])
                self.assertIn("Timeline:", job["prompt_snapshot"]["prompt"])
                self.assertEqual(job["execution_trace"]["director_execution"][
                    "camera_intent_type"], "PROMPT_CAMERA_INTENT")
                self.assertEqual(job["submission_state"], "NOT_STARTED")
                bound_queue = request_json(
                    base + f"/api/projects/{project_id}/long-form/{queue['queue_id']}")
                self.assertEqual(bound_queue["shots"][0]["job_id"], job["id"])
                self.assertEqual(bound_queue["shots"][0]["state"], "PREFLIGHT")
                self.assertEqual(
                    job["director_execution"]["long_form_execution"]["queue_id"],
                    queue["queue_id"])
                saved = request_json(base + f"/api/projects/{project_id}/director")
                self.assertEqual(saved["sequence"]["shots"][0]["last_job_id"], job["id"])
                self.assertEqual(saved["sequence"]["shots"][0][
                    "generation_settings"]["seed"], 42)
                self.assertEqual(len(server.apis["job"]._threads), 0)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
