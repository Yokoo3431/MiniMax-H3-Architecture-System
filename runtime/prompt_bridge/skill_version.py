"""Official H3 Skill version policy (RC3.3 PATCH2.5-A, Phase 1).

Production pins the reviewed Official MiniMax H3 Skill revision. Upstream changes
must NEVER silently alter production behavior.

Identities:
    pinned_skill_revision    - the reviewed/approved skill hashes production uses
    installed_skill_revision - the skill files present in this repository
    latest_upstream_skill_revision - the newest upstream revision (checked
                                     manually/periodically; never auto-fetched)

Policy:
    installed == pinned  -> GENERATION_ALLOWED
    installed != pinned  -> BLOCK (configuration error)
    upstream != pinned   -> generation allowed, surface OFFICIAL_SKILL_UPDATE_AVAILABLE
    upstream unknown     -> generation allowed, surface SKILL_UPSTREAM_CHECK_REQUIRED
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Dict, Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_INSTALLED_SKILL_DIR = _REPO_ROOT / "references" / "known_good_h3" / "comfy_official" / "skill_check"

# Upstream-relative key -> installed file name in this repository.
_INSTALLED_SKILL_FILES = {
    "SKILL.md": "SKILL.md",
    "references/base-en.txt": "base-en.txt",
}

# Pinned revision recorded from the PATCH2.5 baseline freeze (2026-08-14).
# Update ONLY through the controlled upgrade procedure
# (docs/Official_H3_Skill_Update_Policy.md).
PINNED_SKILL_REVISION = {
    "label": "2026-07-29-main-reviewed",
    "files": {
        "SKILL.md": "3411537CB4FC9B580AE4137DE683948952331D4A862DE0C1CA183D9BC1AA60CE",
        "references/base-en.txt": "AEFB0DA9FBE3E9F69AB52A2DBEEB7D8610C811D680F3D415DA7596BBB5AB2B0C",
    },
}

# Latest upstream revision, filled by the manual upgrade procedure ONLY.
# None/UNKNOWN -> generation allowed + SKILL_UPSTREAM_CHECK_REQUIRED flag.
LATEST_UPSTREAM_SKILL_REVISION: Optional[Dict[str, str]] = None


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def installed_skill_revision() -> Dict[str, str]:
    return {
        rel: sha256_file(_INSTALLED_SKILL_DIR / installed_name)
        for rel, installed_name in _INSTALLED_SKILL_FILES.items()
    }


def _files_match(a: Dict[str, str], b: Dict[str, str]) -> bool:
    return a.get("SKILL.md") == b.get("SKILL.md") and a.get("references/base-en.txt") == b.get("references/base-en.txt")


def check_skill_version(pinned: Optional[Dict[str, Dict[str, str]]] = None,
                        latest: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Returns the production skill-version gate result."""
    pinned = pinned or PINNED_SKILL_REVISION
    latest = latest if latest is not None else LATEST_UPSTREAM_SKILL_REVISION
    installed = installed_skill_revision()
    pinned_files = pinned["files"]

    installed_matches = _files_match(installed, pinned_files)
    upstream_known = latest is not None and "SKILL.md" in latest and "references/base-en.txt" in latest
    upstream_matches = _files_match(latest or {}, pinned_files) if upstream_known else False

    flags = []
    if not installed_matches:
        status = "BLOCKED"
        flags.append("INSTALLED_SKILL_MISMATCH_PINNED")
    else:
        status = "GENERATION_ALLOWED"
        if upstream_known and not upstream_matches:
            flags.append("OFFICIAL_SKILL_UPDATE_AVAILABLE")
        elif not upstream_known:
            flags.append("SKILL_UPSTREAM_CHECK_REQUIRED")

    return {
        "status": status,
        "installed_matches_pinned": installed_matches,
        "upstream_matches_pinned": upstream_matches if upstream_known else None,
        "flags": flags,
        "pinned_revision": pinned.get("label", "unknown"),
        "installed_skill_revision": installed,
        "pinned_skill_revision": pinned_files,
        "latest_upstream_skill_revision": latest or "UNKNOWN",
    }


def require_generation_allowed() -> Dict[str, str]:
    """Raises if the installed skill does not match the pinned revision."""
    gate = check_skill_version()
    if gate["status"] != "GENERATION_ALLOWED":
        raise RuntimeError(
            "Skill version gate BLOCKED: installed skill != pinned revision. "
            f"flags={gate['flags']}. Follow docs/Official_H3_Skill_Update_Policy.md."
        )
    return gate


if __name__ == "__main__":
    import json

    print(json.dumps(check_skill_version(), indent=2, ensure_ascii=False))
