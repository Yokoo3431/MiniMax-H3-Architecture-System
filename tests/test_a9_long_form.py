"""A9 shot queue, continuity and assembly-identity CPU contracts."""

from __future__ import annotations

import copy
import hashlib
import tempfile
import json
import struct
import threading
import unittest
import urllib.request
import zlib
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from apps.architect_video_studio.mock_api.long_form_api import LongFormAPI
from apps.architect_video_studio.mock_api.server import StudioServer
from apps.architect_video_studio.mock_api.store import StudioStore
from runtime.long_form import (
    LongFormError, build_assembly_manifest, compile_continuity_binding,
    create_shot_queue, reconcile_shot_queue, resume_plan,
)
from runtime.long_form_assembly import (
    LongFormAssemblyError, LongFormAssembler,
)


PROJECT_ID = "project-a9-fixture"
WORKFLOW_SHA = "a" * 64
MEDIA_SHA_PREFIX = "b"


def director_sequence(count: int = 3) -> dict:
    return {
        "project_id": PROJECT_ID,
        "sequence_id": "sequence-a9-fixture",
        "revision": 7,
        "shots": [
            {"shot_id": f"shot-{index + 1}", "title": f"镜头 {index + 1}",
             "last_job_id": None, "camera_intent": "static",
             "action_intent": f"A{index + 1}"}
            for index in range(count)
        ],
    }


def result_identity(job_id: str, index: int) -> dict:
    return {
        "available": True,
        "job_id": job_id,
        "prompt_id": f"prompt-{index}",
        "workflow_sha256": WORKFLOW_SHA,
        "runtime_id": "production-h3-8189",
        "result_id": f"result:{job_id}",
        "media_sha256": MEDIA_SHA_PREFIX + str(index) * 63,
        "duration_seconds": 4.46,
        "width": 1344,
        "height": 768,
        "fps": 24,
        "audio_stream": True,
    }


class LongFormQueueContractTests(unittest.TestCase):
    def test_modes_are_canonical_and_identity_is_required_for_lock(self):
        bindings = [{"asset_id": "asset-site", "role": "site_reference",
                     "content_sha256": "c" * 64, "approval_state": "APPROVED"}]
        queue = create_shot_queue(
            project_id=PROJECT_ID, director_sequence=director_sequence(),
            continuity_modes={"shot-2": "LOCK_PROJECT_IDENTITY"},
            project_identity_bindings=bindings)
        self.assertEqual(queue["shots"][1]["continuity_modes"],
                         ["LOCK_PROJECT_IDENTITY"])
        self.assertIsNone(queue["shots"][1]["previous_shot_id"])
        self.assertEqual(queue["target"], {"width": 1344, "height": 768, "fps": 24})
        with self.assertRaisesRegex(LongFormError, "IDENTITY_REQUIRED"):
            create_shot_queue(
                project_id=PROJECT_ID, director_sequence=director_sequence(),
                continuity_modes={"shot-2": "LOCK_PROJECT_IDENTITY"})
        with self.assertRaisesRegex(LongFormError, "COMBINATION_UNSUPPORTED"):
            create_shot_queue(
                project_id=PROJECT_ID, director_sequence=director_sequence(),
                continuity_modes={"shot-2": ["LOCK_PROJECT_IDENTITY",
                                              "CONTINUE_VISUALLY"]},
                project_identity_bindings=bindings)

    def test_first_shot_cannot_continue_and_conflicting_modes_fail_closed(self):
        with self.assertRaisesRegex(LongFormError, "FIRST_SHOT_CANNOT_CONTINUE"):
            create_shot_queue(
                project_id=PROJECT_ID, director_sequence=director_sequence(),
                continuity_modes={"shot-1": "CONTINUE_VISUALLY"})
        with self.assertRaisesRegex(LongFormError, "CONTINUITY_MODES_CONFLICT"):
            create_shot_queue(
                project_id=PROJECT_ID, director_sequence=director_sequence(),
                continuity_modes={"shot-2": ["INDEPENDENT", "CONTINUE_VISUALLY"]})

    def test_project_sequence_and_shot_identity_are_validated(self):
        source = director_sequence()
        source["project_id"] = "project-other"
        with self.assertRaisesRegex(LongFormError, "CROSS_PROJECT"):
            create_shot_queue(project_id=PROJECT_ID, director_sequence=source)
        with self.assertRaisesRegex(LongFormError, "SHOT_NOT_IN_DIRECTOR"):
            create_shot_queue(project_id=PROJECT_ID,
                              director_sequence=director_sequence(),
                              shot_ids=["shot-1", "shot-404"])

    def test_restart_reconciliation_preserves_completed_and_resumes_first_failure(self):
        queue = create_shot_queue(project_id=PROJECT_ID,
                                  director_sequence=director_sequence())
        queue["shots"][0]["job_id"] = "job-a"
        queue["shots"][1]["job_id"] = "job-b"
        result = reconcile_shot_queue(
            queue,
            {"job-a": {"id": "job-a", "project_id": PROJECT_ID,
                       "state": "COMPLETED"},
             "job-b": {"id": "job-b", "project_id": PROJECT_ID,
                       "state": "FAILED"}},
            {"job-a": result_identity("job-a", 1)})
        self.assertEqual(result["shots"][0]["state"], "RESULT_READY")
        self.assertEqual(result["shots"][0]["job_id"], "job-a")
        self.assertEqual(result["shots"][1]["state"], "FAILED")
        first_resume = resume_plan(result)
        after_restart = resume_plan(copy.deepcopy(result))
        self.assertEqual(first_resume, after_restart)
        self.assertEqual(first_resume["action"], "RETRY_FAILED_SHOT_EXPLICITLY")
        self.assertEqual(first_resume["shot_id"], "shot-2")
        self.assertFalse(first_resume["submission_performed"])
        self.assertEqual(result["shots"][0]["job_id"], "job-a")

    def test_running_job_is_waited_on_not_resubmitted_after_restart(self):
        queue = create_shot_queue(project_id=PROJECT_ID,
                                  director_sequence=director_sequence())
        queue["shots"][0]["job_id"] = "job-running"
        result = reconcile_shot_queue(
            queue, {"job-running": {"id": "job-running",
                                    "project_id": PROJECT_ID,
                                    "state": "RUNNING"}}, {})
        self.assertEqual(resume_plan(result), {
            "action": "WAIT_EXISTING_JOB", "shot_id": "shot-1",
            "job_id": "job-running", "submission_performed": False})

    def test_continuity_binding_requires_ready_predecessor_and_strong_frame_identity(self):
        queue = create_shot_queue(
            project_id=PROJECT_ID, director_sequence=director_sequence(),
            continuity_modes={"shot-2": "CONTINUE_VISUALLY"})
        with self.assertRaisesRegex(LongFormError, "PREVIOUS_RESULT_REQUIRED"):
            compile_continuity_binding(queue, 1, None)
        queue["shots"][0]["state"] = "RESULT_READY"
        previous = {"job_id": "job-a", "result_id": "result:job-a",
                    "media_sha256": "e" * 64, "last_frame_asset_id": "frame-a",
                    "last_frame_sha256": "f" * 64, "last_frame_idx": 106}
        binding = compile_continuity_binding(queue, 1, previous)
        self.assertEqual([ref["role"] for ref in binding["reference_bindings"]],
                         ["first_frame"])
        self.assertEqual(binding["reference_bindings"][0]["frame_selector"],
                         "LAST_DECODED_FRAME")
        self.assertEqual(binding["reference_bindings"][0]["frame_idx"], 106)
        bad_previous = {**previous, "last_frame_sha256": "bad"}
        with self.assertRaisesRegex(LongFormError, "PREVIOUS_FRAME_IDENTITY_INCOMPLETE"):
            compile_continuity_binding(queue, 1, bad_previous)

    def test_assembly_manifest_is_deterministic_ordered_and_requires_three_ready_jobs(self):
        queue = create_shot_queue(project_id=PROJECT_ID,
                                  director_sequence=director_sequence())
        with self.assertRaisesRegex(LongFormError, "REQUIRES_THREE_SHOTS"):
            build_assembly_manifest({**queue, "shots": queue["shots"][:2]})
        jobs = {f"job-{index}": {"id": f"job-{index}",
                                  "project_id": PROJECT_ID,
                                  "state": "COMPLETED"}
                for index in range(3)}
        identities = {job_id: result_identity(job_id, index)
                      for index, job_id in enumerate(jobs, 1)}
        for shot, job_id in zip(queue["shots"], jobs):
            shot["job_id"] = job_id
        reconciled = reconcile_shot_queue(queue, jobs, identities)
        first = build_assembly_manifest(reconciled)
        second = build_assembly_manifest(copy.deepcopy(reconciled))
        self.assertEqual(first["manifest_sha256"], second["manifest_sha256"])
        self.assertEqual(first["transition_policy"], "CUT")
        self.assertEqual(first["audio_policy"], "KEEP_PER_SHOT_CUT")
        self.assertEqual([shot["ordinal"] for shot in first["shots"]], [0, 1, 2])
        self.assertFalse(first["postprocess_applied"])

    def test_assembly_rejects_duplicate_jobs_and_incomplete_execution_identity(self):
        queue = create_shot_queue(project_id=PROJECT_ID,
                                  director_sequence=director_sequence())
        for ordinal, shot in enumerate(queue["shots"], 1):
            job_id = f"job-{ordinal}"
            identity = result_identity(job_id, ordinal)
            shot.update(state="RESULT_READY", job_identity={
                "job_id": job_id, "prompt_id": identity["prompt_id"],
                "workflow_sha256": identity["workflow_sha256"],
                "runtime_id": identity["runtime_id"]}, result_identity={
                "result_id": identity["result_id"],
                "media_sha256": identity["media_sha256"]})
        queue["shots"][2]["job_identity"]["job_id"] = "job-1"
        with self.assertRaisesRegex(LongFormError, "DUPLICATE_JOB"):
            build_assembly_manifest(queue)
        queue["shots"][2]["job_identity"]["job_id"] = "job-3"
        queue["shots"][2]["job_identity"]["workflow_sha256"] = "unknown"
        with self.assertRaisesRegex(LongFormError, "IDENTITY_INCOMPLETE"):
            build_assembly_manifest(queue)


class FakeOutputAPI:
    def __init__(self, media: dict[str, Path]):
        self.media = media
        self.get_result_calls = 0

    def get_result(self, job_id: str) -> dict:
        self.get_result_calls += 1
        path = self.media[job_id]
        return {
            "output": {"available": True},
            "ffprobe": {"available": True, "duration_seconds": 4.46,
                        "width": 1344, "height": 768, "fps": 24.0,
                        "video_codec": "h264", "container_format": "mp4",
                        "audio_stream": True, "frame_count": 107},
        }

    def media_path(self, job_id: str) -> Path:
        return self.media[job_id]


class LongFormAPITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = StudioStore(self.root / "data")
        self.project_id = PROJECT_ID
        self.store.save_json(self.store.project_file(self.project_id), {
            "id": self.project_id, "state": "COMPLETED", "name": "A9 fixture"})
        sequence = director_sequence()
        self.store.save_json(self.store.project_dir(self.project_id) / "director.json",
                             sequence)
        self.media = {}
        jobs = {}
        for index, shot in enumerate(sequence["shots"], 1):
            job_id = f"job-a9-{index}"
            shot["last_job_id"] = job_id
            path = self.root / f"fixture-{index}.mp4"
            path.write_bytes(f"synthetic-media-{index}".encode("ascii"))
            self.media[job_id] = path
            jobs[job_id] = {
                "id": job_id, "project_id": self.project_id,
                "state": "COMPLETED", "runtime": "native",
                "workflow": "04_Drone_Aerial", "prompt_id": f"prompt-{index}",
                "execution_workflow_sha256": WORKFLOW_SHA,
                "runtime_id": "production-h3-8189",
                "execution_trace": {"runtime_identity": {
                    "runtime_id": "production-h3-8189"},
                    "workflow_sha256": WORKFLOW_SHA},
                "director_execution": {"sequence_id": sequence["sequence_id"],
                                        "shot_id": shot["shot_id"]},
            }
        self.store.save_json(self.store.project_dir(self.project_id) / "director.json",
                             sequence)
        self.store.save_jobs(self.project_id, jobs)
        self.output_api = FakeOutputAPI(self.media)
        self.api = LongFormAPI(self.store, output_api=self.output_api)

    def test_persistent_queue_reconciles_jobs_and_resumes_without_submission(self):
        queue = self.api.create(self.project_id, {})
        self.assertEqual(queue["status"], "ASSEMBLY_PENDING")
        self.assertEqual([shot["state"] for shot in queue["shots"]],
                         ["RESULT_READY"] * 3)
        self.assertTrue(all(shot["result_identity"]["media_sha256"]
                            == hashlib.sha256(self.media[shot["job_id"]].read_bytes()
                                              ).hexdigest()
                            for shot in queue["shots"]))
        resume = self.api.resume(self.project_id, queue["queue_id"])
        self.assertEqual(resume["resume"]["action"], "ASSEMBLE")
        self.assertFalse(resume["submission_performed"])
        restarted = LongFormAPI(self.store, output_api=self.output_api)
        recovered = restarted.get(self.project_id, queue["queue_id"])
        self.assertEqual(recovered["queue_id"], queue["queue_id"])
        self.assertEqual([item["job_id"] for item in recovered["shots"]],
                         [f"job-a9-{index}" for index in range(1, 4)])

    def test_queue_creation_is_idempotent_and_bind_job_checks_shot_lineage(self):
        first = self.api.create(self.project_id, {})
        second = self.api.create(self.project_id, {})
        self.assertEqual(first["queue_id"], second["queue_id"])
        self.assertEqual(first["request_sha256"], second["request_sha256"])
        with self.assertRaisesRegex(LongFormError, "SHOT_IDENTITY_MISMATCH"):
            self.api.bind_job(self.project_id, first["queue_id"],
                              "shot-2", "job-a9-1")
        with self.assertRaisesRegex(LongFormError, "JOB_QUEUE_IDENTITY_MISMATCH"):
            self.api.bind_job(self.project_id, first["queue_id"],
                              "shot-2", "job-a9-2")

    def test_queue_slot_reservation_prevents_duplicate_pre_submission_jobs(self):
        sequence_path = self.store.project_dir(self.project_id) / "director.json"
        sequence = self.store.load_json(sequence_path)
        for shot in sequence["shots"]:
            shot["last_job_id"] = None
        self.store.save_json(sequence_path, sequence)
        queue = self.api.create(self.project_id, {})
        first_job = {
            "id": "job-a9-reserved-1", "project_id": self.project_id,
            "director_execution": {
                "sequence_id": sequence["sequence_id"],
                "shot_id": "shot-1",
                "long_form_execution": {
                    "queue_id": queue["queue_id"], "shot_id": "shot-1"},
            },
        }
        reserved = self.api.reserve_job(
            self.project_id, queue["queue_id"], "shot-1", first_job)
        self.assertEqual(reserved["shots"][0]["job_id"], first_job["id"])
        self.assertEqual(reserved["shots"][0]["state"], "PREFLIGHT")
        second_job = copy.deepcopy(first_job)
        second_job["id"] = "job-a9-reserved-2"
        with self.assertRaisesRegex(LongFormError, "SHOT_NOT_SUBMITTABLE"):
            self.api.reserve_job(
                self.project_id, queue["queue_id"], "shot-1", second_job)
        persisted = self.api.get(self.project_id, queue["queue_id"])
        self.assertEqual(persisted["shots"][0]["job_id"], first_job["id"])
        self.assertEqual(self.store.load_jobs(self.project_id).get(
            second_job["id"]), None)

    def test_next_shot_is_enforced_and_persisted_job_provenance_recovers_binding(self):
        sequence_path = self.store.project_dir(self.project_id) / "director.json"
        sequence = self.store.load_json(sequence_path)
        for shot in sequence["shots"]:
            shot["last_job_id"] = None
        self.store.save_json(sequence_path, sequence)
        queue = self.api.create(self.project_id, {})
        with self.assertRaisesRegex(LongFormError, "NOT_NEXT_IN_SEQUENCE"):
            self.api.prepare_for_job(self.project_id, queue["queue_id"], "shot-2")

        new_job = {
            "id": "job-a9-recovered",
            "project_id": self.project_id,
            "state": "PREPARING",
            "prompt_id": None,
            "director_execution": {
                "sequence_id": sequence["sequence_id"],
                "shot_id": "shot-1",
                "long_form_execution": {
                    "queue_id": queue["queue_id"], "shot_id": "shot-1"},
            },
        }
        jobs = self.store.load_jobs(self.project_id)
        jobs[new_job["id"]] = new_job
        self.store.save_jobs(self.project_id, jobs)
        recovered = self.api.get(self.project_id, queue["queue_id"])
        self.assertEqual(recovered["shots"][0]["job_id"], new_job["id"])
        self.assertEqual(recovered["shots"][0]["state"], "PREFLIGHT")
        self.assertEqual(self.api.resume(self.project_id, queue["queue_id"])
                         ["resume"]["action"], "WAIT_EXISTING_JOB")

    def test_predecessor_frame_index_must_be_a_nonnegative_integer(self):
        queue = create_shot_queue(
            project_id=self.project_id,
            director_sequence=director_sequence(),
            continuity_modes={"shot-2": "CONTINUE_VISUALLY"})
        queue["shots"][0]["state"] = "RESULT_READY"
        predecessor = {
            "job_id": "job-a", "result_id": "result:job-a",
            "media_sha256": "e" * 64, "last_frame_asset_id": "frame-a",
            "last_frame_sha256": "f" * 64, "last_frame_idx": 1.5,
        }
        with self.assertRaisesRegex(LongFormError, "FRAME_IDENTITY_INCOMPLETE"):
            compile_continuity_binding(queue, 1, predecessor)

    def test_resume_after_second_shot_failure_keeps_first_completed(self):
        jobs = self.store.load_jobs(self.project_id)
        jobs["job-a9-2"]["state"] = "FAILED"
        self.store.save_jobs(self.project_id, jobs)
        queue = self.api.create(self.project_id, {})
        self.assertEqual(queue["shots"][0]["state"], "RESULT_READY")
        self.assertEqual(queue["shots"][1]["state"], "FAILED")
        self.assertEqual(self.api.resume(self.project_id, queue["queue_id"])
                         ["resume"]["action"], "RETRY_FAILED_SHOT_EXPLICITLY")
        # Existing completed Job identity is retained after a service restart.
        again = LongFormAPI(self.store, output_api=self.output_api).get(
            self.project_id, queue["queue_id"])
        self.assertEqual(again["shots"][0]["job_id"], "job-a9-1")
        self.assertEqual(again["shots"][0]["state"], "RESULT_READY")

    def test_http_create_and_resume_routes_are_cpu_only(self):
        server = StudioServer(
            ("127.0.0.1", 0), self.store, {"long_form": self.api})
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_address[1]}"
        request = urllib.request.Request(
            f"{base}/api/projects/{self.project_id}/long-form",
            data=b"{}", headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=5) as response:
            created = json.loads(response.read().decode("utf-8"))
        self.assertTrue(created["ok"])
        queue_id = created["data"]["queue_id"]
        request = urllib.request.Request(
            f"{base}/api/projects/{self.project_id}/long-form/{queue_id}/resume",
            data=b"{}", headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=5) as response:
            resumed = json.loads(response.read().decode("utf-8"))
        self.assertEqual(resumed["data"]["resume"]["action"], "ASSEMBLE")
        self.assertFalse(resumed["data"]["submission_performed"])

    def test_assembly_reuses_cpu_result_and_serves_http_range(self):
        queue = self.api.create(self.project_id, {})
        calls = []

        def fake_assemble(sources, probes, *, width, height, fps,
                          audio_policy, output_path):
            calls.append((tuple(sources), width, height, fps, audio_policy))
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"synthetic-assembled-video")
            return {
                "status": "READY",
                "ffmpeg_version": "synthetic-ffmpeg",
                "output_sha256": hashlib.sha256(
                    output_path.read_bytes()).hexdigest(),
                "size_bytes": output_path.stat().st_size,
                "media": {"duration_seconds": 13.38, "width": width,
                          "height": height, "fps": fps,
                          "video_codec": "h264", "audio_stream": True,
                          "frame_count": 321, "container_format": "mp4",
                          "probe_tool": "synthetic-fixture"},
            }

        self.api.assembler.assemble = fake_assemble
        first = self.api.assemble(self.project_id, queue["queue_id"])
        second = self.api.assemble(self.project_id, queue["queue_id"])
        self.assertFalse(first["generation_submitted"])
        self.assertTrue(second["reused"])
        self.assertEqual(first["assembly"]["assembly_id"],
                         second["assembly"]["assembly_id"])
        self.assertEqual(len(calls), 1)

        server = StudioServer(
            ("127.0.0.1", 0), self.store, {"long_form": self.api})
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.shutdown)
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}"
            f"/api/projects/{self.project_id}/long-form/"
            f"{queue['queue_id']}/media",
            headers={"Range": "bytes=0-8"})
        with urllib.request.urlopen(request, timeout=5) as response:
            self.assertEqual(response.status, 206)
            self.assertEqual(response.headers.get("Content-Range"),
                             "bytes 0-8/25")
            self.assertEqual(response.read(), b"synthetic")

    @staticmethod
    def _png_fixture() -> bytes:
        def chunk(name: bytes, data: bytes) -> bytes:
            return (struct.pack(">I", len(data)) + name + data
                    + struct.pack(">I", zlib.crc32(name + data) & 0xffffffff))
        raw = b"\x00\x40\x80\xc0\xff"
        return (b"\x89PNG\r\n\x1a\n"
                + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))

    def test_continue_visually_derives_and_persists_exact_predecessor_frame(self):
        sequence_path = self.store.project_dir(self.project_id) / "director.json"
        sequence = self.store.load_json(sequence_path)
        sequence["shots"][2]["last_job_id"] = None
        self.store.save_json(sequence_path, sequence)
        jobs = self.store.load_jobs(self.project_id)
        jobs.pop("job-a9-3")
        self.store.save_jobs(self.project_id, jobs)
        self.media.pop("job-a9-3")
        queue = self.api.create(
            self.project_id, {"continuity_modes": {"shot-3": "CONTINUE_VISUALLY"}})

        def fake_extract(source, *, frame_count, output_path):
            self.assertEqual(frame_count, 107)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            data = self._png_fixture()
            output_path.write_bytes(data)
            digest = hashlib.sha256(data).hexdigest()
            return {"asset_id": f"frame-{digest[:32]}",
                    "content_sha256": digest, "source_frame_idx": frame_count - 1}

        self.api.assembler.extract_last_frame = fake_extract
        before = self.store.load_project(self.project_id)
        prepared = self.api.prepare_for_job(
            self.project_id, queue["queue_id"], "shot-3")
        again = self.api.prepare_for_job(
            self.project_id, queue["queue_id"], "shot-3")
        after = self.store.load_project(self.project_id)
        self.assertEqual(prepared["binding"], again["binding"])
        self.assertEqual(prepared["binding"]["reference_bindings"][0]["frame_selector"],
                         "LAST_DECODED_FRAME")
        self.assertEqual(prepared["binding"]["reference_bindings"][0]["frame_idx"], 106)
        self.assertEqual(prepared["reference"]["approval_basis"],
                         "USER_SELECTED_CONTINUE_VISUALLY")
        self.assertEqual(before.get("selected_reference_asset_ids"),
                         after.get("selected_reference_asset_ids"))
        persisted = self.api.get(self.project_id, queue["queue_id"])
        self.assertEqual(persisted["shots"][2]["continuity_binding"],
                         prepared["binding"])
        self.assertFalse(prepared["submission_performed"])


class LongFormAssemblySafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sources = []
        self.probes = []
        for index in range(3):
            source = self.root / f"source-{index}.mp4"
            source.write_bytes(b"source" + bytes([index]))
            self.sources.append(source)
            self.probes.append({"duration_seconds": 1.0, "audio_stream": False})
        self.output = self.root / "out" / "assembly.mp4"
        self.assembler = LongFormAssembler(
            ffmpeg_executable=self.root / "ffmpeg.exe", min_free_bytes=0,
            probe=lambda path, **kwargs: {
                "available": True, "duration_seconds": 3.0, "width": 320,
                "height": 180, "fps": 24.0, "video_codec": "h264",
                "audio_stream": False, "frame_count": 72,
                "container_format": "mp4", "probe_tool": "fixture",
            }, timeout_seconds=1)
        # A path is needed for the command builder; subprocess execution is
        # replaced below and never launches this synthetic executable.
        self.assembler.ffmpeg = self.root / "ffmpeg.exe"

    def _run_successful_fake_encode(self, command, **kwargs):
        if "-version" in command:
            return SimpleNamespace(returncode=0, stdout="ffmpeg fixture\n", stderr="")
        Path(command[-1]).write_bytes(b"assembled-fixture")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def test_probe_failure_cleans_partial_and_preserves_no_partial_output(self):
        def broken_probe(*args, **kwargs):
            raise RuntimeError("synthetic probe failure")

        self.assembler.probe = broken_probe
        with patch("runtime.long_form_assembly.subprocess.run",
                   side_effect=self._run_successful_fake_encode):
            with self.assertRaisesRegex(LongFormAssemblyError, "MEDIA_PROBE_FAILED"):
                self.assembler.assemble(
                    self.sources, self.probes, width=320, height=180, fps=24,
                    audio_policy="MUTE", output_path=self.output)
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.output.parent.glob("*.partial.mp4")), [])
        self.assertEqual(list(self.output.parent.glob(".*.partial.mp4")), [])

    def test_media_assembly_is_bounded_by_aggregate_source_size(self):
        with patch("runtime.long_form_assembly.MAX_SOURCE_BYTES", 8), \
                patch("runtime.long_form_assembly.subprocess.run") as run:
            with self.assertRaisesRegex(LongFormAssemblyError, "SOURCE_SIZE_LIMIT"):
                self.assembler.assemble(
                    self.sources, self.probes, width=320, height=180, fps=24,
                    audio_policy="MUTE", output_path=self.output)
        run.assert_not_called()

    def test_media_assembly_rejects_output_overwriting_a_source(self):
        with self.assertRaisesRegex(LongFormAssemblyError, "OUTPUT_MUST_BE_DISTINCT"):
            self.assembler.assemble(
                [self.sources[0], self.sources[1], self.sources[2]], self.probes,
                width=320, height=180, fps=24, audio_policy="MUTE",
                output_path=self.sources[0])


if __name__ == "__main__":
    unittest.main()
