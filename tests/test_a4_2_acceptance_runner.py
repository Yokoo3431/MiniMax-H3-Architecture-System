from __future__ import annotations

import unittest
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from runtime.a4_2_quality_acceptance import (
    A4_2AcceptanceError,
    _resolved_execution_parameters,
    _selected_arms,
    _needs_acceptance_probe,
    _reopen_misbound_acceptance_job,
    _validate_acceptance_study_gate,
    _validate_prepared_arm_graph,
    _video_frame_count,
)
from runtime.a4_profiles import resolve_product_parameters
from runtime.adapters.golden_workflow_binding import bind_golden_workflow
from runtime.reference_contract import reference_bindings


class TestA42AcceptanceRunnerGates(unittest.TestCase):
    def setUp(self):
        self.study = {
            "prompt_current": True,
            "reference_approved": True,
            "prompt_confirmed": False,
            "generate_allowed": False,
        }
        self.candidate_prompt = {
            "prompt_engine_provider": "OFFLINE_COMPILER",
            "verified": {"pass": True},
            "a4_profile": {
                "quality_profile": "STANDARD",
                "availability": "CANDIDATE_FOR_A4_2",
            },
        }

    def test_controlled_candidate_is_allowed_without_opening_normal_generation(self):
        result = _validate_acceptance_study_gate(self.study, self.candidate_prompt)
        self.assertEqual(
            result, "A4_2_STANDARD_CANDIDATE_WITH_PRODUCTION_GATE_CLOSED")

    def test_candidate_requires_verified_current_prompt_and_approved_reference(self):
        for study, prompt in (
            ({**self.study, "prompt_current": False}, self.candidate_prompt),
            ({**self.study, "reference_approved": False}, self.candidate_prompt),
            (self.study, {**self.candidate_prompt, "verified": {"pass": False}}),
        ):
            with self.subTest(study=study, prompt=prompt), self.assertRaises(
                    A4_2AcceptanceError):
                _validate_acceptance_study_gate(study, prompt)

    def test_candidate_gate_drift_is_rejected(self):
        for drift in (
            {"generate_allowed": True},
            {"prompt_confirmed": True},
        ):
            with self.subTest(drift=drift), self.assertRaisesRegex(
                    A4_2AcceptanceError, "candidate"):
                _validate_acceptance_study_gate(
                    {**self.study, **drift}, self.candidate_prompt)

    def test_non_candidate_prompt_still_requires_normal_study_confirmation(self):
        prompt = {
            "prompt_engine_provider": "CUSTOM_ADAPTER",
            "verified": {"pass": True},
            "a4_profile": {"quality_profile": "NATIVE_HIGH", "availability": "READY"},
        }
        with self.assertRaisesRegex(A4_2AcceptanceError, "confirmation"):
            _validate_acceptance_study_gate(self.study, prompt)
        confirmed = {**self.study, "prompt_confirmed": True}
        self.assertEqual(_validate_acceptance_study_gate(confirmed, prompt),
                         "CONFIRMED_PROMPT")

    def test_each_invocation_selects_exactly_one_arm(self):
        self.assertEqual(_selected_arms("STANDARD"), ("STANDARD",))
        self.assertEqual(_selected_arms("NATIVE_HIGH"), ("NATIVE_HIGH",))
        with self.assertRaisesRegex(A4_2AcceptanceError, "one explicit arm"):
            _selected_arms("BOTH")

    def test_failed_completed_evidence_is_reprobed_but_passed_evidence_is_not(self):
        self.assertTrue(_needs_acceptance_probe({"state": "COMPLETED"}))
        self.assertTrue(_needs_acceptance_probe({
            "state": "COMPLETED", "acceptance_evidence": {"pass": False}}))
        self.assertFalse(_needs_acceptance_probe({
            "state": "COMPLETED", "acceptance_evidence": {"pass": True}}))
        self.assertFalse(_needs_acceptance_probe({
            "state": "FAILED", "acceptance_evidence": {"pass": False}}))

    def test_decoded_frame_count_uses_ffmpeg_when_ffprobe_is_unavailable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            ffmpeg = Path(temp_dir) / "ffmpeg.exe"
            ffmpeg.touch()
            runtime_paths = SimpleNamespace(
                ffprobe=None, ffmpeg=ffmpeg,
                embedded_python=Path(temp_dir) / "python.exe",
            )
            stderr = "".join(
                f"[Parsed_showinfo_0] n: {index} pts: {index * 1000} pts_time: 0\n"
                for index in range(107))
            completed = SimpleNamespace(returncode=0, stderr=stderr)
            with patch("runtime.a4_2_quality_acceptance.subprocess.run",
                       return_value=completed) as run:
                frame_count = _video_frame_count(Path("private-output.mp4"), runtime_paths)

        self.assertEqual(frame_count, 107)
        command = run.call_args.args[0]
        self.assertIn("showinfo", command)
        self.assertEqual(command[command.index("-vsync") + 1], "0")
        self.assertIn("-f", command)

    def test_decoded_frame_count_rejects_incomplete_or_nonsequential_decode(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            ffmpeg = Path(temp_dir) / "ffmpeg.exe"
            ffmpeg.touch()
            runtime_paths = SimpleNamespace(
                ffprobe=None, ffmpeg=ffmpeg,
                embedded_python=Path(temp_dir) / "python.exe",
            )
            completed = SimpleNamespace(
                returncode=0,
                stderr="[showinfo] n: 0 pts: 0\n[showinfo] n: 2 pts: 2\n",
            )
            with patch("runtime.a4_2_quality_acceptance.subprocess.run",
                       return_value=completed):
                frame_count = _video_frame_count(Path("private-output.mp4"), runtime_paths)
        self.assertIsNone(frame_count)

    def _misbound_completed_job_fixture(self, width=1344, height=768):
        job_id = "job-high"
        graph = {
            "1": {"class_type": "MiniMaxH3ImageToVideo",
                  "inputs": {"width": width, "height": height}},
            "2": {"class_type": "SaveVideo",
                  "inputs": {"filename_prefix": f"video/{job_id}"}},
        }
        from runtime.adapters.production_workflow_binding import canonical_workflow_sha256
        workflow_sha = canonical_workflow_sha256(graph)
        entry = {"prompt": [1, "prompt-high", graph, {
            "architect_video_studio": {
                "avs_job_id": job_id,
                "execution_workflow_sha256": workflow_sha,
            }}, []], "status": {"status_str": "success", "completed": True}}
        job = {
            "id": job_id, "acceptance_campaign": "A4.2_NATIVE_QUALITY",
            "acceptance_arm": "NATIVE_HIGH", "state": "COMPLETED",
            "submission_state": "ACKNOWLEDGED", "prompt_id": "old-standard-prompt",
            "execution_workflow_sha256": workflow_sha,
            "acceptance_submission_attempts": 1,
            "acceptance_evidence": {"pass": False},
            "final_output_path": "stale-standard-output.mp4",
            "output_path": "stale-standard-output.mp4",
        }

        class _Store:
            def __init__(self, item):
                self.jobs = {item["id"]: dict(item)}

            def load_jobs(self, _project_id):
                return {key: dict(value) for key, value in self.jobs.items()}

            def save_jobs(self, _project_id, jobs):
                self.jobs = {key: dict(value) for key, value in jobs.items()}

        class _Client:
            def reconcile_prompt(self, **kwargs):
                self.kwargs = kwargs
                return {"status": "COMPLETED", "source": "history",
                        "prompt_id": "prompt-high", "entry": entry}

        return job, _Store(job), _Client()

    def test_false_terminal_job_rebinds_only_to_exact_high_history(self):
        job, store, client = self._misbound_completed_job_fixture()
        self.assertTrue(_reopen_misbound_acceptance_job(job, store, "study", client))
        recovered = store.load_jobs("study")["job-high"]
        self.assertEqual(recovered["prompt_id"], "prompt-high")
        self.assertEqual(recovered["state"], "RECONCILING")
        self.assertEqual(recovered["submission_state"], "RECONCILING")
        self.assertEqual(recovered["final_output_path"], "")
        self.assertEqual(recovered["acceptance_submission_attempts"], 1)
        self.assertIsNone(client.kwargs["prompt_id"])
        self.assertIsNone(client.kwargs["legacy_seed"])

    def test_false_terminal_job_refuses_wrong_canvas_history(self):
        job, store, client = self._misbound_completed_job_fixture(width=1248, height=704)
        self.assertFalse(_reopen_misbound_acceptance_job(job, store, "study", client))
        recovered = store.load_jobs("study")["job-high"]
        self.assertEqual(recovered["state"], "COMPLETED")
        self.assertEqual(recovered["prompt_id"], "old-standard-prompt")

    def _prepared_graph(self, arm):
        params, profile = resolve_product_parameters(
            "04_Drone_Aerial",
            {"quality": arm, "duration": 4.0, "fps": 24,
             "delivery_fps": 24, "seed": 42},
            allow_a4_2_candidate=(arm == "STANDARD"),
        )
        refs = [{
            "asset_id": "approved-reference",
            "project_id": "study-a4-2",
            "role": "first_frame",
            "approval_state": "APPROVED",
            "sha256": "A" * 64,
            "path_or_ref": "h3-a4-2-reference.png",
        }]
        profile_identity = {
            key: profile[key] for key in (
                "contract_version", "architecture_profile",
                "architecture_profile_version", "quality_profile_version",
                "prompt_profile_version",
            )
        }
        prompt_payload = {
            "prompt": "verified controlled acceptance prompt",
            "prompt_hash": "prompt-hash",
            "reference_bindings": reference_bindings(refs),
            "a4_profile": profile_identity,
        }
        graph = bind_golden_workflow({
            "study_id": "study-a4-2",
            "reference_assets": refs,
            "generation_parameters": params,
            "prompt_payload": prompt_payload,
        }, "04_Drone_Aerial", allow_a4_2_candidate=(arm == "STANDARD"))
        request = SimpleNamespace(
            workflow_id="04_Drone_Aerial",
            prompt_payload=prompt_payload,
            reference_assets=refs,
        )
        prepared = {"workflow_id": "04_Drone_Aerial", "translated_payload": graph}
        return request, params, profile, prepared

    def test_bound_graph_is_checked_against_absolute_arm_contract(self):
        for arm, canvas in (("STANDARD", (1248, 704)),
                            ("NATIVE_HIGH", (1344, 768))):
            request, params, profile, prepared = self._prepared_graph(arm)
            with self.subTest(arm=arm):
                resolved = _resolved_execution_parameters(params, profile)
                self.assertEqual(resolved["scheduler"], "simple")
                self.assertEqual(resolved["denoise"], 1.0)
                self.assertEqual(resolved["acceleration"], "off")
                actual = _validate_prepared_arm_graph(
                    arm, request, params, profile, prepared)
                self.assertEqual((actual["width"], actual["height"]), canvas)
                self.assertEqual(actual["frame_count"], 107)
                self.assertEqual(actual["fps"], 24.0)
                self.assertEqual(actual["seed"], 42)
                self.assertEqual(actual["steps"], 50)
                self.assertEqual(actual["sampler"], "euler")
                self.assertEqual(actual["scheduler"], "simple")
                self.assertEqual(actual["denoise"], 1.0)
                self.assertEqual(actual["acceleration"], "off")

    def test_bound_graph_rejects_shared_wrong_values_and_wrong_bindings(self):
        request, params, profile, prepared = self._prepared_graph("STANDARD")
        wrong_value = {**prepared, "translated_payload": {
            key: dict(value) for key, value in prepared["translated_payload"].items()
        }}
        for node in wrong_value["translated_payload"].values():
            if node.get("class_type") == "BasicScheduler":
                node["inputs"] = {**node["inputs"], "steps": 49}
                break
        with self.assertRaisesRegex(A4_2AcceptanceError, "mismatch in steps"):
            _validate_prepared_arm_graph("STANDARD", request, params, profile, wrong_value)

        changed_prompt = SimpleNamespace(
            workflow_id=request.workflow_id,
            prompt_payload={**request.prompt_payload, "prompt": "different prompt"},
            reference_assets=request.reference_assets,
        )
        with self.assertRaisesRegex(A4_2AcceptanceError, "Prompt binding"):
            _validate_prepared_arm_graph("STANDARD", changed_prompt, params, profile, prepared)

        changed_refs = SimpleNamespace(
            workflow_id=request.workflow_id,
            prompt_payload={**request.prompt_payload, "reference_bindings": []},
            reference_assets=request.reference_assets,
        )
        with self.assertRaisesRegex(A4_2AcceptanceError, "reference provenance"):
            _validate_prepared_arm_graph("STANDARD", changed_refs, params, profile, prepared)


if __name__ == "__main__":
    unittest.main()
