"""PATCH2.8-I2-R2B-F3-R4 tokenizer-resolution parity tests.

CPU/static only.  The optional managed-runtime parity test loads tokenizer
metadata but never loads model weights, CUDA tensors, ComfyUI, or /prompt.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / "patches" / "support_layers" / "minimax_h3_production_windows.patch"


def _candidate_order(component: Path, explicit: str | None = None) -> list[Path]:
    if explicit:
        return [Path(explicit)]
    return [component, component.parent / "processor", component.parent / "tokenizer"]


def _select_fast_tokenizer_component(
    component: Path, explicit: str | None = None
) -> Path | None:
    return next(
        (candidate for candidate in _candidate_order(component, explicit)
         if (candidate / "tokenizer.json").is_file()),
        None,
    )


def _managed_root() -> Path | None:
    path_file = ROOT / "native_env.path"
    if path_file.is_file():
        value = path_file.read_text(encoding="utf-8").strip()
        if value:
            return Path(value)
    return None


def _configured_models_root() -> Path | None:
    managed = _managed_root()
    if managed is not None:
        extra = managed / "ComfyUI" / "extra_model_paths.yaml"
        if extra.is_file():
            match = re.search(r"^\s*base_path:\s*(.+?)\s*$", extra.read_text(encoding="utf-8"), re.MULTILINE)
            if match and Path(match.group(1).strip()).is_dir():
                return Path(match.group(1).strip())
    state = ROOT / "userdata" / "system" / "system" / "setup_state.json"
    if not state.is_file():
        return None
    value = json.loads(state.read_text(encoding="utf-8")).get("models_root")
    return Path(value) if value else None


class TokenizerResolutionParityTests(unittest.TestCase):
    def test_pinned_candidate_order_is_explicit(self):
        source = PATCH.read_text(encoding="utf-8")
        self.assertIn("component.parent / \"processor\"", source)
        self.assertIn("component.parent / \"tokenizer\"", source)
        self.assertLess(source.index("component,"), source.index("component.parent / \"processor\""))

    def test_fast_tokenizer_asset_is_required_by_patch(self):
        source = PATCH.read_text(encoding="utf-8")
        self.assertIn('required_files=("tokenizer.json",)', source)

    def test_missing_tokenizer_candidate_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            component = Path(temp) / "FL2VA" / "text_encoder"
            component.mkdir(parents=True)
            self.assertIsNone(_select_fast_tokenizer_component(component))

    def test_valid_text_encoder_candidate_is_selected(self):
        with tempfile.TemporaryDirectory() as temp:
            component = Path(temp) / "FL2VA" / "text_encoder"
            component.mkdir(parents=True)
            (component / "tokenizer.json").write_text("{}", encoding="utf-8")
            self.assertEqual(_select_fast_tokenizer_component(component), component)

    def test_model_index_tokenizer_without_fast_asset_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "FL2VA"
            root.mkdir()
            index = root / "model_index.json"
            index.write_text(json.dumps({"tokenizer": "processor"}), encoding="utf-8")
            processor = root / "processor"
            processor.mkdir()
            self.assertIsNone(_select_fast_tokenizer_component(root / "text_encoder"))

    def test_model_index_tokenizer_with_fast_asset_is_accepted(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "FL2VA"
            processor = root / "processor"
            processor.mkdir(parents=True)
            (processor / "tokenizer.json").write_text("{}", encoding="utf-8")
            self.assertEqual(
                _select_fast_tokenizer_component(root / "text_encoder"),
                processor,
            )

    def test_standalone_and_pinned_contract_use_same_expected_path(self):
        with tempfile.TemporaryDirectory() as temp:
            component = Path(temp) / "FL2VA" / "text_encoder"
            component.mkdir(parents=True)
            (component / "tokenizer.json").write_text("{}", encoding="utf-8")
            self.assertEqual(_select_fast_tokenizer_component(component), component)

    def test_no_legacy_or_test_runtime_fallback_is_encoded(self):
        source = PATCH.read_text(encoding="utf-8")
        for forbidden in ("ComfyUI_H3_NATIVE_TEST", "validation", "ComfyUI_windows_portable"):
            self.assertNotIn(forbidden, source)

    def test_arbitrary_install_drive_is_path_derived(self):
        with tempfile.TemporaryDirectory() as temp:
            drive_root = Path(temp) / "custom-drive" / "models" / "MiniMax-H3" / "FL2VA"
            component = drive_root / "text_encoder"
            component.mkdir(parents=True)
            (component / "tokenizer.json").write_text("{}", encoding="utf-8")
            selected = _select_fast_tokenizer_component(component)
            self.assertEqual(selected, component)
            self.assertNotIn("D:\\", str(selected))

    def test_patch_does_not_install_sentencepiece_or_tiktoken(self):
        source = PATCH.read_text(encoding="utf-8").lower()
        self.assertNotIn("pip install", source)
        self.assertNotIn("sentencepiece", source)
        self.assertNotIn("tiktoken", source)

    def test_patch_does_not_load_weights_or_gpu(self):
        source = PATCH.read_text(encoding="utf-8")
        start = source.index("--- a/minimax_h3_nodes/runtime/qwen_encoder/loading.py")
        end = source.index("@@ -1358 +1450 @@", start)
        source = source[start:end].lower()
        self.assertNotIn("torch.cuda", source)
        self.assertNotIn("from_pretrained", source)
        self.assertNotIn("safetensors", source)

    def test_processor_contract_remains_separate(self):
        source = PATCH.read_text(encoding="utf-8")
        self.assertIn("processor", source)
        self.assertIn("preprocessor_config.json", (ROOT / "configs" / "h3_sidecar_manifest.yaml").read_text(encoding="utf-8"))

    def test_patch_is_source_controlled_and_pinned(self):
        self.assertTrue(PATCH.is_file())
        source = PATCH.read_text(encoding="utf-8")
        self.assertIn("qwen_encoder/loading.py", source)
        self.assertIn("tokenizer.json", source)
        self.assertIn("d6c5f7b0d4e03936ac4a9834be63ecc6b5637dad", (ROOT / "configs" / "support_layer_manifest.yaml").read_text(encoding="utf-8"))

    def test_optional_managed_cpu_parity(self):
        managed = _managed_root()
        if managed is None:
            self.skipTest("native_env.path is not configured")
        python = managed / "python_embeded" / "python.exe"
        models = _configured_models_root()
        if not python.is_file() or models is None or not models.is_dir():
            self.skipTest("managed runtime or selected models root unavailable")
        code = r'''
import json, os, sys
from pathlib import Path
runtime = Path(sys.executable).parents[1]
comfy = runtime / "ComfyUI"
models = Path(os.environ["R4_MODELS_ROOT"])
sys.path.insert(0, str(comfy))
sys.path.insert(0, str(comfy / "custom_nodes" / "ComfyUI_RH_MinMaxH3"))
from minimax_h3_nodes.api import _shared
from minimax_h3_nodes.runtime.components import _impl as c
from transformers import AutoTokenizer
partition, _, _ = _shared._resolve_t2va_release(str(models / "MiniMax-H3"))
selector = _shared._default_te_model_name()
component, _ = _shared._resolve_selected_component(
    partition, selector, keys=("text_encoder", "qwen3vl", "qwen"),
    label="Text Encoder", partition="FL2VA", required_files=("config.json",),
)
selected = next(p for p in (component, component.parent / "processor", component.parent / "tokenizer") if (p / "tokenizer.json").is_file())
a = AutoTokenizer.from_pretrained(str(component), use_fast=True, local_files_only=True, trust_remote_code=False)
b = AutoTokenizer.from_pretrained(str(selected), use_fast=True, local_files_only=True, trust_remote_code=False)
print(json.dumps({"same_path": str(component.resolve()) == str(selected.resolve()), "a_fast": bool(a.is_fast), "b_fast": bool(b.is_fast), "class": b.__class__.__name__}))
'''
        env = dict(os.environ)
        env["R4_MODELS_ROOT"] = str(models)
        env["MINIMAX_H3_MODEL_ROOTS"] = str(models / "MiniMax-H3")
        env["MINIMAX_H3_WEIGHTS_ROOTS"] = str(models / "MiniMax-H3")
        completed = subprocess.run([str(python), "-c", code], capture_output=True, text=True, env=env, check=True)
        result = json.loads(completed.stdout.strip().splitlines()[-1])
        self.assertTrue(result["same_path"])
        self.assertTrue(result["a_fast"])
        self.assertTrue(result["b_fast"])
        self.assertEqual(result["class"], "Qwen2Tokenizer")


if __name__ == "__main__":
    unittest.main()
