"""CPU/static coverage for the final product job path and user-facing UX."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from apps.architect_video_studio.mock_api.job_api import _classify_failure  # noqa: E402
from runtime.adapters.runtime_paths import RuntimePathError, resolve_runtime_paths  # noqa: E402


class TestCanonicalJobPaths(unittest.TestCase):
    def _runtime(self, root: Path) -> tuple[Path, Path]:
        runtime = root / "runtime"
        comfy = runtime / "ComfyUI"
        (runtime / "python_embeded").mkdir(parents=True)
        (comfy / "custom_nodes").mkdir(parents=True)
        (comfy / "models").mkdir()
        (root / "models").mkdir()
        (root / "workflows").mkdir()
        (runtime / "python_embeded" / "python.exe").write_bytes(b"test")
        (comfy / "main.py").write_text("# test", encoding="utf-8")
        return runtime, root / "models"

    def test_resolves_contract_without_cwd_or_placeholder(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runtime, models = self._runtime(root)
            contract = resolve_runtime_paths(
                root / "userdata" / "studio",
                repo_root=root,
                environ={"H3_NATIVE_ROOT": str(runtime), "H3_MODELS_ROOT": str(models)},
            )
            contract.validate_for_job()
            self.assertEqual(contract.runtime_root, runtime.resolve())
            self.assertEqual(contract.embedded_python, runtime / "python_embeded" / "python.exe")
            self.assertNotIn("<NATIVE_ROOT>", json.dumps(contract.as_dict()))
            self.assertTrue(contract.input_root.is_dir())
            self.assertTrue(contract.output_root.is_dir())

    def test_placeholder_input_is_not_accepted_as_runtime_path(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runtime, models = self._runtime(root)
            contract = resolve_runtime_paths(
                root / "userdata" / "studio", repo_root=root,
                environ={"H3_NATIVE_ROOT": str(runtime), "H3_MODELS_ROOT": str(models),
                         "H3_COMFY_INPUT": "<NATIVE_ROOT>/ComfyUI/input"},
            )
            self.assertEqual(contract.input_root, runtime / "ComfyUI" / "input")

    def test_installed_runtime_contract_overrides_stale_package_input(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runtime, models = self._runtime(root / "adopted")
            app = root / "app"
            (app / "userdata" / "studio").mkdir(parents=True)
            (app / "native_env.path").write_text(str(runtime), encoding="utf-8")
            (app / "models_env.path").write_text(str(models), encoding="utf-8")
            stale = app / "ArchitectVideoStudio_Runtime" / "ComfyUI" / "input"
            contract = resolve_runtime_paths(
                app / "userdata" / "studio", repo_root=app,
                environ={
                    "H3_NATIVE_ROOT": str(stale.parents[2]),
                    "H3_MODELS_ROOT": str(app / "Models"),
                    "H3_COMFY_INPUT": str(stale),
                    "H3_COMFY_OUTPUT": str(stale.parent / "output"),
                },
            )
            self.assertEqual(contract.runtime_root, runtime.resolve())
            self.assertEqual(contract.input_root, runtime / "ComfyUI" / "input")
            self.assertEqual(contract.output_root, runtime / "ComfyUI" / "output")

    def test_path_contract_accepts_powershell_utf8_bom(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runtime, models = self._runtime(root)
            (root / "native_env.path").write_text("\ufeff" + str(runtime), encoding="utf-8")
            (root / "models_env.path").write_text("\ufeff" + str(models), encoding="utf-8")
            contract = resolve_runtime_paths(root / "userdata" / "studio", repo_root=root)
            self.assertEqual(contract.runtime_root, runtime.resolve())
            self.assertEqual(contract.models_root, models.resolve())

    def test_invalid_runtime_has_environment_category(self):
        category, message = _classify_failure(RuntimePathError("missing runtime"))
        self.assertEqual(category, "ENVIRONMENT_ERROR")
        self.assertIn("运行环境", message)

    def test_missing_reference_has_input_category(self):
        category, message = _classify_failure(FileNotFoundError("reference.png"))
        self.assertEqual(category, "INPUT_ERROR")
        self.assertIn("参考图", message)


class TestProductionJobUiContract(unittest.TestCase):
    def test_job_detail_and_simple_studio_assets_exist(self):
        jobs = (ROOT / "apps/architect_video_studio/frontend/jobs.html").read_text(encoding="utf-8")
        script = (ROOT / "apps/architect_video_studio/frontend/js/jobs.js").read_text(encoding="utf-8")
        studio = (ROOT / "apps/architect_video_studio/frontend/workspace.html").read_text(encoding="utf-8")
        self.assertIn("job-detail", jobs)
        self.assertIn("/detail", script)
        self.assertIn("/retry", script)
        self.assertIn("高级设置", studio)
        self.assertIn("开始生成", studio)


if __name__ == "__main__":
    unittest.main()
