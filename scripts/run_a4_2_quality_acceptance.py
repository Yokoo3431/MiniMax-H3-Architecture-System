"""Explicit entry point for the one controlled A4.2 GPU comparison."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.a4_2_quality_acceptance import (
    ARMS, A4_2AcceptanceError, run_a4_2_acceptance,
)
from runtime.adapters.runtime_paths import resolve_runtime_paths


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--api-base", default="http://127.0.0.1:8788")
    parser.add_argument("--observe-timeout-seconds", type=float, default=1800.0)
    parser.add_argument(
        "--arm", choices=ARMS, default="STANDARD",
        help="Run exactly one arm; NATIVE_HIGH requires a separately recorded STANDARD pass.",
    )
    parser.add_argument(
        "--execute-gpu", action="store_true", required=True,
        help="Explicitly authorize the selected local A4.2 acceptance arm.",
    )
    args = parser.parse_args()
    try:
        paths = resolve_runtime_paths(args.data_root)
        result = run_a4_2_acceptance(
            data_root=args.data_root,
            project_id=args.project_id,
            runtime_paths=paths,
            api_base=args.api_base,
            observe_timeout_seconds=args.observe_timeout_seconds,
            arm=args.arm,
        )
    except A4_2AcceptanceError as exc:
        print(json.dumps({"classification": "A4_2_BLOCKED", "reason": str(exc)},
                         ensure_ascii=False))
        return 2
    except Exception as exc:  # keep owner paths/content out of terminal logs
        print(json.dumps({
            "classification": "A4_2_FAILED_BEFORE_OR_DURING_ACCEPTANCE",
            "error_type": type(exc).__name__,
        }, ensure_ascii=False))
        return 3
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["classification"] in (
        "A4_2_STANDARD_PASS_HIGH_NOT_RUN", "A4_2_PAIR_COMPLETE") else 2


if __name__ == "__main__":
    raise SystemExit(main())
