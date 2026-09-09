"""Run the single, isolated Advanced A1 V2 B-arm GPU acceptance.

The script prints sanitized JSON only.  It never prints prompts, reference
paths, package paths, raw Comfy history, or media bytes.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.advanced_gpu_acceptance import (
    finalize_reconciled_b_arm, run_advanced_b_arm,
)
from runtime.adapters.runtime_paths import resolve_runtime_paths


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--source-job-id", required=True)
    parser.add_argument("--finalize-job-id", default="")
    args = parser.parse_args()
    paths = resolve_runtime_paths(args.data_root)
    if args.finalize_job_id:
        evidence = finalize_reconciled_b_arm(
            data_root=args.data_root, project_id=args.project_id,
            job_id=args.finalize_job_id, runtime_paths=paths,
        )
    else:
        evidence = run_advanced_b_arm(
            data_root=args.data_root, project_id=args.project_id,
            source_job_id=args.source_job_id, runtime_paths=paths,
        )
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
