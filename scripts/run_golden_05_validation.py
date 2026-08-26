"""Run the single owner-authorized real validation for 05_Slow_Walkthrough.

This script deliberately uses the historical native UI asset through
NativeRuntimeAdapter.  It writes the exact API graph only after ComfyUI
returns a real, ffmpeg-validated MP4; it never downloads or changes models.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.adapters.comfyui_client import ComfyUIClient
from runtime.adapters.native_runtime_adapter import NativeRuntimeAdapter
from runtime.adapters.runtime_adapter import VideoGenerationRequest
from runtime.adapters.runtime_paths import resolve_runtime_paths


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", required=True, type=Path)
    parser.add_argument("--models-root", required=True, type=Path)
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--golden-output", default=ROOT / "production_workflows/golden/05_Slow_Walkthrough.json", type=Path)
    parser.add_argument("--base-url", default="http://127.0.0.1:8189")
    parser.add_argument("--seed", default=777888904, type=int)
    args = parser.parse_args()

    runtime = args.runtime_root.resolve()
    models = args.models_root.resolve()
    reference = args.reference.resolve()
    if not reference.is_file():
        raise SystemExit(f"reference not found: {reference}")

    # Use a content-addressed Comfy input name so no old browser/Comfy tab can
    # accidentally point this run at a previous reference image.
    digest = hashlib.sha256(reference.read_bytes()).hexdigest()[:12]
    staged_name = f"avs_golden_05_{digest}{reference.suffix.lower() or '.png'}"
    input_dir = runtime / "ComfyUI" / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    staged = input_dir / staged_name
    shutil.copy2(reference, staged)

    data_root = ROOT / "userdata" / "studio"
    paths = resolve_runtime_paths(
        data_root,
        repo_root=ROOT,
        environ={
            "H3_NATIVE_ROOT": str(runtime),
            "H3_MODELS_ROOT": str(models),
        },
    )
    client = ComfyUIClient(
        base_url=args.base_url,
        timeout=60.0,
        output_root=str(paths.output_root),
        strict_output=True,
        ffmpeg_path=str(paths.ffmpeg) if paths.ffmpeg else None,
    )
    if not client.input_file_available(staged_name):
        raise SystemExit(f"ComfyUI cannot see staged input: {staged_name}")

    request = VideoGenerationRequest(
        study_id="golden-05-validation",
        reference_assets=[{
            "asset_id": f"golden-05-{digest}",
            "role": "first_frame",
            "path_or_ref": staged_name,
            "sha256": hashlib.sha256(reference.read_bytes()).hexdigest(),
        }],
        workflow_id="05_Slow_Walkthrough",
        camera_motion="walkthrough",
        generation_parameters={
            "resolution": "1344x768", "fps": 24, "duration": 4.0,
            "quality": "diagnostic", "seed": args.seed,
        },
        prompt_payload={
            "mode": "I2VA",
            "prompt": "First-person architectural interior walkthrough framing; the camera moves forward gently through the space at a slow, stable pace with natural daylight and soft material detail.",
            "prompt_hash": "golden-05-historical-prompt",
        },
        output_spec={
            "container": "mp4", "codec": "h264", "fps": 24,
            "resolution": "1344x768", "report_format": "json",
        },
        gates={
            "reference_approved": True, "intent_confirmed": True,
            "prompt_verified": True, "risk_reviewed": True,
        },
    )
    adapter = NativeRuntimeAdapter(
        client=client,
        production_binding=False,
        runtime_paths=paths,
        comfy_input_dir=str(paths.input_root),
    )
    prepared = adapter.prepare(request)
    payload = prepared["translated_payload"]
    classes = [node["class_type"] for node in payload.values()]
    if len(payload) != 15 or "RHMiniMaxH3TextEncoderLoader" in classes:
        raise SystemExit(f"historical graph contract failed: {classes}")
    if payload["2"]["class_type"] != "CLIPLoader" or payload["3"]["class_type"] != "UNETLoader":
        raise SystemExit(f"native loader contract failed: {classes}")

    result = adapter.generate(request)
    # NativeRuntimeAdapter.status() intentionally exposes only a status
    # snapshot.  The validated artifact is retrieved through its output
    # contract after COMPLETED; treating the status snapshot as the output
    # would misclassify a successful Comfy history as "no MP4".
    output = adapter.get_output(result["job_id"])
    video_path = Path(str(output.get("video_path") or ""))
    if not video_path.is_file():
        raise SystemExit(f"validated job returned no MP4: {video_path}")

    args.golden_output.parent.mkdir(parents=True, exist_ok=True)
    args.golden_output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    report = {
        "status": "GOLDEN_05_PASS",
        "workflow": "05_Slow_Walkthrough",
        "workflow_asset": prepared["workflow_asset"],
        "execution_workflow_sha256": prepared["execution_workflow_sha256"],
        "node_count": len(payload),
        "node_types": classes,
        "prompt_id": result.get("prompt_id"),
        "output": output,
        "mp4": str(video_path),
        "mp4_sha256": hashlib.sha256(video_path.read_bytes()).hexdigest(),
        "reference_sha256": request.reference_assets[0]["sha256"],
        "safe_load": "H3_WINDOWS_SAFE_LOAD=pread",
        "runtime_flags": ["--lowvram", "--disable-async-offload", "--disable-pinned-memory"],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
