"""PATCH2.8-I2-R2B-F3-R5 CPU/static processor and dtype reconciliation tests."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "scripts" / "probe_qwen_visual_device_cycle.py"
FORENSICS = ROOT / "docs" / "PATCH2.8I2_R2BF3_Qwen_Visual_Offload_Forensics.md"
OLD_G1R2 = ROOT / "docs" / "PATCH2.8I2_R2BF3_G1R2_Final_Baseline_Visual_Probe.md"


def _managed_runtime() -> Path:
    return Path((ROOT / "native_env.path").read_text(encoding="utf-8").strip()).resolve()


def _models_root() -> Path:
    state = json.loads((ROOT / "userdata" / "system" / "setup_state.json").read_text(encoding="utf-8"))
    return Path(state["models_root"]).resolve()


class ProcessorDtypeContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = PROBE.read_text(encoding="utf-8")
        cls.encoder = _managed_runtime() / "ComfyUI" / "custom_nodes" / "ComfyUI_RH_MinMaxH3" / "minimax_h3_nodes" / "runtime" / "qwen_encoder" / "encoder.py"
        cls.loading = cls.encoder.with_name("loading.py")

    def test_production_fl2va_uses_image_processor(self):
        source = self.encoder.read_text(encoding="utf-8")
        self.assertIn("vision = processor.image_processor(", source)
        self.assertIn("images=images,", source)
        self.assertIn('return_tensors="pt"', source)

    def test_probe_uses_same_preprocessing_seam(self):
        self.assertIn('image_processor = getattr(processor_obj, "image_processor", None)', self.source)
        self.assertIn('vision = image_processor(images=[image], return_tensors="pt")', self.source)
        self.assertIn("minimax_h3_multi_image_presentation_ids", self.source)
        self.assertIn("minimax_h3_multi_image_presentation_token_tags", self.source)

    def test_probe_has_no_wrapper_text_none_shortcut(self):
        self.assertNotRegex(self.source, r'(?<!image_)processor\(images=')
        self.assertNotRegex(self.source, r'(?<!image_)processor\(images=\[')

    def test_cpu_validation_fields_are_explicit(self):
        for fragment in (
            'vision.get("pixel_values")',
            'vision.get("image_grid_thw")',
            'tuple(image_grid_thw.shape[1:]) != (3,)',
            'merge_size = int(getattr(image_processor, "merge_size", 0))',
            'image_token_counts',
            'input_ids.ndim != 1',
            'token_tags.ndim != 1',
        ):
            self.assertIn(fragment, self.source)

    def test_presentation_alignment_checks_image_placeholders(self):
        self.assertIn('convert_tokens_to_ids("<|image_pad|>")', self.source)
        self.assertIn("placeholder_count != image_token_counts[0]", self.source)
        self.assertIn("token_tags must align with input_ids", self.source)

    def test_production_source_calls_encode_ids_after_presentation(self):
        source = self.encoder.read_text(encoding="utf-8")
        self.assertLess(source.index("minimax_h3_multi_image_presentation_ids"), source.index("hidden = self.encode_ids("))
        self.assertIn("pixel_values=pixel_values", source)
        self.assertIn("image_grid_thw=image_grid_thw", source)

    def test_live_visual_contract_is_fp32_and_includes_buffer(self):
        source = FORENSICS.read_text(encoding="utf-8")
        self.assertIn("live managed module observed as FP32", source)
        self.assertIn("351 parameters plus one buffer", source)
        self.assertIn("2,381,067,272", OLD_G1R2.read_text(encoding="utf-8"))

    def test_loader_constructs_meta_model_before_stream_assignment(self):
        source = self.loading.read_text(encoding="utf-8")
        self.assertIn("with init_empty_weights():", source)
        self.assertIn("model_cls._from_config", source)
        self.assertIn("_stream_load_quantized_backbone(", source)
        self.assertIn("model_dtype=model_dtype", source)

    def test_loader_casts_pass_through_tensor_to_target_dtype(self):
        source = self.loading.read_text(encoding="utf-8")
        needle = "tensor = tensor.to(dtype=target.dtype)"
        self.assertIn(needle, source)
        self.assertLess(source.index("tensor.dtype != target.dtype"), source.index(needle))
        self.assertIn("_assign_param(model, local, tensor.to(device=offload_device))", source)

    def test_no_speculative_dtype_conversion_patch(self):
        patch = (ROOT / "patches" / "support_layers" / "minimax_h3_production_windows.patch").read_text(encoding="utf-8")
        self.assertNotIn("visual.to(dtype", patch)
        self.assertNotIn("visual = visual.to(torch.bfloat16", patch)
        self.assertNotIn("model.visual.to(torch.bfloat16", patch)

    def test_checkpoint_vs_live_dtype_claim_is_explicit(self):
        source = FORENSICS.read_text(encoding="utf-8")
        self.assertIn("checkpoint region is BF16", source)
        self.assertIn("live managed FP32", source)
        self.assertIn("no dtype conversion patch has been applied", source)

    def test_memory_model_uses_observed_fp32_bytes(self):
        source = FORENSICS.read_text(encoding="utf-8")
        self.assertIn("2,381,067,272 bytes", source)
        self.assertIn("hypothetical BF16", source)
        self.assertNotIn("bulk BF16 visual CUDA-to-CPU", source)

    def test_probe_preprocess_is_before_cuda_migration(self):
        self.assertLess(self.source.index("prepared = _production_fl2va_preprocess"), self.source.index('"G1R3-06"'))
        self.assertLess(self.source.index('"G1R3-06"'), self.source.index("visual.to(load_device)"))

    def test_production_prompt_is_non_empty_diagnostic_prompt(self):
        self.assertRegex(self.source, r'prompt = "[^"]+"')

    def test_no_production_entry_or_generation_call(self):
        self.assertNotIn("Studio JobAPI", self.source)
        self.assertNotIn("requests.post", self.source)

    def test_no_model_download_or_mutation_in_r5_test(self):
        self.assertNotIn("download", type(self).__module__.lower())
        self.assertNotIn("safetensors.save", self.source)

    def test_managed_cpu_processor_contract(self):
        runtime = _managed_runtime()
        python = runtime / "python_embeded" / "python.exe"
        models = _models_root()
        if not python.is_file() or not models.is_dir():
            self.fail("managed runtime/models root required for R5 CPU contract validation")
        code = r'''
import json, os, sys
from pathlib import Path
from PIL import Image
runtime = Path(sys.executable).parents[1]
comfy = runtime / "ComfyUI"
h3 = comfy / "custom_nodes" / "ComfyUI_RH_MinMaxH3"
models = Path(os.environ["R5_MODELS_ROOT"])
sys.path.insert(0, str(comfy))
sys.path.insert(0, str(h3))
from transformers import AutoProcessor, AutoTokenizer
from minimax_h3_nodes.runtime.presentation import minimax_h3_multi_image_presentation_ids, minimax_h3_multi_image_presentation_token_tags
component = models / "MiniMax-H3" / "FL2VA" / "text_encoder"
tokenizer = AutoTokenizer.from_pretrained(str(component), local_files_only=True, trust_remote_code=False, use_fast=True)
processor = AutoProcessor.from_pretrained(str(component), local_files_only=True, trust_remote_code=False)
image = Image.open(Path(os.environ["R5_IMAGE"])).convert("RGB")
vision = processor.image_processor(images=[image], return_tensors="pt")
grid = vision["image_grid_thw"]
merge = int(processor.image_processor.merge_size)
counts = [int(grid[0].prod().item()) // (merge ** 2)]
prompt = "A modern architectural exterior with clear massing and daylight."
ids = minimax_h3_multi_image_presentation_ids(tokenizer, prompt=prompt, image_token_counts=counts)
tags = minimax_h3_multi_image_presentation_token_tags(tokenizer, prompt=prompt, image_token_counts=counts)
pad = int(tokenizer.convert_tokens_to_ids("<|image_pad|>"))
print(json.dumps({"tokenizer": tokenizer.__class__.__name__, "fast": bool(tokenizer.is_fast), "processor": processor.__class__.__name__, "image_processor": processor.image_processor.__class__.__name__, "pixel_shape": list(vision["pixel_values"].shape), "grid_shape": list(grid.shape), "merge_size": merge, "image_token_counts": counts, "ids_ndim": ids.ndim, "ids": int(ids.numel()), "placeholders": int((ids == pad).sum().item()), "tags": int(tags.numel())}))
'''
        env = dict(os.environ)
        env["R5_MODELS_ROOT"] = str(models)
        env["R5_IMAGE"] = str(ROOT / "samples" / "01_Exterior_Hero.png")
        completed = subprocess.run([str(python), "-c", code], capture_output=True, text=True, env=env, check=True)
        result = json.loads(completed.stdout.strip().splitlines()[-1])
        self.assertEqual(result["tokenizer"], "Qwen2Tokenizer")
        self.assertTrue(result["fast"])
        self.assertEqual(result["processor"], "Qwen2_5_VLProcessor")
        self.assertEqual(result["grid_shape"][1], 3)
        self.assertGreater(result["merge_size"], 0)
        self.assertGreater(result["image_token_counts"][0], 0)
        self.assertEqual(result["placeholders"], result["image_token_counts"][0])
        self.assertEqual(result["ids"], result["tags"])


if __name__ == "__main__":
    unittest.main()
