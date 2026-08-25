"""Development compatibility wrapper for the production Studio service.

Usage:
    python run_prototype.py [--port 8788] [--data <dir>]

Serves the static frontend + mock /api contract on 127.0.0.1.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from apps.architect_video_studio.mock_api._paths import DEFAULT_DATA_ROOT  # noqa: E402
from apps.architect_video_studio.mock_api.server import make_server  # noqa: E402
from runtime.storage_policy import apply_process_environment  # noqa: E402


def main() -> None:
    # Direct Studio launches receive the same project-local cache policy as
    # launches managed by launcher.ProcessManager.
    apply_process_environment(REPO_ROOT)
    parser = argparse.ArgumentParser(description="Architect Video Studio (development compatibility entry)")
    parser.add_argument("--port", type=int, default=8788)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--runtime", choices=("mock", "real"), default="real",
                        help="mock = simulated jobs; real = Native ComfyUI runtime")
    args = parser.parse_args()

    data_root = Path(args.data).resolve()
    server = make_server(("127.0.0.1", args.port), data_root, runtime=args.runtime)
    print("=" * 64)
    print("  Architect Video Studio - LOCAL UI PROTOTYPE (PATCH2.6-B)")
    print(f"  URL:  http://127.0.0.1:{args.port}")
    print(f"  Data: {data_root}")
    print(f"  Runtime: {args.runtime} "
          + ("(Native ComfyUI + PREAD)" if args.runtime == "real"
             else "(mock simulation, no GPU)"))
    print("  Ctrl+C to stop.")
    print("=" * 64, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
        sys.exit(0)


if __name__ == "__main__":
    main()
