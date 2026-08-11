"""Release Package Builder Script
Builds MiniMax-H3-Architecture-System-v0.5.0.zip excluding model weights and output video files.
"""

import os
import sys
import json
import zipfile
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_FILE = SYSTEM_ROOT / "release" / "release_manifest.json"
RELEASE_DIR = SYSTEM_ROOT / "release"

def should_exclude(rel_path: str, excludes: list[str]) -> bool:
    low = rel_path.lower()
    if "__pycache__" in low or ".git" in low:
        return True
    for pat in excludes:
        if pat.startswith("*.") and low.endswith(pat[1:]):
            return True
    return False

def build_release_package() -> Path:
    if not MANIFEST_FILE.is_file():
        raise FileNotFoundError(f"Release manifest missing at {MANIFEST_FILE}")

    with open(MANIFEST_FILE, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    zip_name = manifest.get("package_filename", "MiniMax-H3-Architecture-System-v0.5.0.zip")
    zip_path = RELEASE_DIR / zip_name

    excludes = manifest.get("exclude_patterns", [])
    inc_dirs = manifest.get("include_directories", [])
    inc_files = manifest.get("include_files", [])

    print("=================================================================", flush=True)
    print("      MINIMAX H3 V0.5 AUTOMATED RELEASE PACKAGE BUILDER          ", flush=True)
    print("=================================================================", flush=True)
    print(f"Target Zip Output : {zip_path}", flush=True)

    added_files = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # Add root files
        for fn in inc_files:
            fp = SYSTEM_ROOT / fn
            if fp.is_file():
                zf.write(fp, arcname=fn)
                added_files += 1

        # Add target directories
        for d in inc_dirs:
            dp = SYSTEM_ROOT / d
            if dp.is_dir():
                for root, _, files in os.walk(dp):
                    for file in files:
                        full_path = Path(root) / file
                        rel_path = full_path.relative_to(SYSTEM_ROOT).as_posix()

                        if not should_exclude(rel_path, excludes):
                            zf.write(full_path, arcname=rel_path)
                            added_files += 1

    zip_size_mb = zip_path.stat().st_size / (1024 ** 2)
    print("\n=================================================================", flush=True)
    print(f"[SUCCESS] Packaging Completed!", flush=True)
    print(f"Total Added Files : {added_files}", flush=True)
    print(f"Final Package Size: {zip_size_mb:.2f} MB", flush=True)
    print(f"Zip Location      : {zip_path}", flush=True)
    print("=================================================================", flush=True)

    return zip_path

if __name__ == "__main__":
    build_release_package()
