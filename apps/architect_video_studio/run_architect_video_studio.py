"""Run the Architect Video Studio local service.

This is the production desktop-backend entry point.  The service is hosted
inside the native desktop shell; the browser remains an explicit fallback.
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
    apply_process_environment(REPO_ROOT)
    parser = argparse.ArgumentParser(description="Architect Video Studio")
    parser.add_argument("--port", type=int, default=8788)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--runtime", choices=("mock", "real"), default="real",
                        help="real = Native ComfyUI runtime")
    args = parser.parse_args()

    data_root = Path(args.data).resolve()
    server = make_server(("127.0.0.1", args.port), data_root, runtime=args.runtime)
    print(f"Architect Video Studio service running on http://127.0.0.1:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
