"""Deterministic regression inventory guard.

The guard never rewrites the frozen inventory.  Baseline updates are an
explicit review action performed by a human with ``apply_patch``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import unittest
from collections import Counter, defaultdict
from pathlib import Path
from types import ModuleType
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = ROOT / "configs" / "regression_test_inventory.txt"
BASELINE_PATH = ROOT / "configs" / "regression_baseline.json"
SOURCE_MANIFEST_PATH = ROOT / "configs" / "regression_test_sources.json"
CANONICAL_COMMAND = 'python -m unittest discover -s tests -p "test*.py"'


class InventoryError(RuntimeError):
    pass


def _flatten(suite: unittest.TestSuite) -> Iterable[unittest.TestCase]:
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _flatten(item)
        else:
            yield item


def discover_cases() -> list[unittest.TestCase]:
    suite = unittest.defaultTestLoader.discover("tests", pattern="test*.py")
    cases = list(_flatten(suite))
    ids = [case.id() for case in cases]
    duplicates = sorted(name for name, count in Counter(ids).items() if count > 1)
    if duplicates:
        raise InventoryError("DUPLICATE_TEST_IDS:\n" + "\n".join(duplicates))
    return sorted(cases, key=lambda case: case.id())


def discovered_ids() -> list[str]:
    return [case.id() for case in discover_cases()]


def _module_path(module_name: str, modules: dict[str, ModuleType]) -> Path:
    module = modules.get(module_name)
    if module is None or not getattr(module, "__file__", None):
        raise InventoryError(f"test module has no source file: {module_name}")
    path = Path(module.__file__).resolve()
    try:
        return path.relative_to(ROOT)
    except ValueError as exc:
        raise InventoryError(f"test source is outside repository: {path}") from exc


def source_manifest(cases: list[unittest.TestCase] | None = None) -> dict:
    cases = cases or discover_cases()
    modules = dict(sys.modules)
    grouped: dict[str, list[str]] = defaultdict(list)
    for case in cases:
        relative = _module_path(case.__class__.__module__, modules)
        grouped[str(relative).replace("\\", "/")].append(case.id())
    files = []
    for relative, ids in sorted(grouped.items()):
        path = ROOT / relative
        files.append({
            "path": relative,
            "tracked_status": "tracked" if _is_tracked(path) else "untracked",
            "sha256": _sha256(path),
            "discovered_test_count": len(ids),
            "classification": _classification(relative),
        })
    excluded = []
    runtime_dir = ROOT / "tests" / "runtime"
    for path in sorted(runtime_dir.glob("test*.py")):
        excluded.append({
            "path": str(path.relative_to(ROOT)).replace("\\", "/"),
            "tracked_status": "tracked" if _is_tracked(path) else "untracked",
            "sha256": _sha256(path),
            "discovered_test_count": _ast_test_count(path),
            "classification": "INTEGRATION",
            "canonical_command": "python -m unittest discover -s tests/runtime -p \"test*.py\"",
            "reason_excluded": "real ComfyUI/GPU or prompt-endpoint behavior; explicit opt-in only",
        })
    return {
        "schema_version": 1,
        "canonical_command": CANONICAL_COMMAND,
        "files": files,
        "excluded_sources": excluded,
    }


def expected_skips(cases: list[unittest.TestCase] | None = None) -> list[dict]:
    cases = cases or discover_cases()
    skips = []
    for case in cases:
        # unittest stores skip metadata either on the individual method
        # wrapper or on the TestCase class.  The latter is used by the
        # historical external-machine integration guards.
        method = getattr(case.__class__, case._testMethodName, None)
        case_skip = bool(getattr(case, "__unittest_skip__", False))
        method_skip = bool(getattr(method, "__unittest_skip__", False))
        class_skip = bool(getattr(case.__class__, "__unittest_skip__", False))
        if not (case_skip or method_skip or class_skip):
            continue
        reason = getattr(case, "__unittest_skip_why__", None)
        if reason is None:
            reason = getattr(method, "__unittest_skip_why__", None)
        if reason is None:
            reason = getattr(case.__class__, "__unittest_skip_why__", "")
        skips.append({"id": case.id(), "reason": str(reason)})
    return sorted(skips, key=lambda item: item["id"])


def compare_inventory(current: list[str], frozen: list[str]) -> dict[str, list[str]]:
    current_set, frozen_set = set(current), set(frozen)
    return {
        "ADDED": sorted(current_set - frozen_set),
        "REMOVED": sorted(frozen_set - current_set),
        "SKIP_CHANGED": [],
    }


def compare_skip_inventory(current: list[dict], frozen: list[dict]) -> list[str]:
    current_map = {item["id"]: item.get("reason", "") for item in current}
    frozen_map = {item["id"]: item.get("reason", "") for item in frozen}
    return sorted(
        item_id for item_id in set(current_map) | set(frozen_map)
        if current_map.get(item_id) != frozen_map.get(item_id)
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _is_tracked(path: Path) -> bool:
    import subprocess
    result = subprocess.run(["git", "ls-files", "--error-unmatch", str(path.relative_to(ROOT))],
                            cwd=ROOT, capture_output=True, text=True, check=False)
    return result.returncode == 0


def _ast_test_count(path: Path) -> int:
    import ast
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return sum(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
               and node.name.startswith("test") for node in ast.walk(tree))


def _classification(relative: str) -> str:
    if relative in {"tests/test_v080_rc31_integration.py", "tests/test_v080_rc32_native_reconstruction.py"}:
        return "OPTIONAL_EXTERNAL"
    return "CORE_REGRESSION"


def check() -> int:
    current = discovered_ids()
    if not INVENTORY_PATH.is_file() or not BASELINE_PATH.is_file():
        print("MISSING baseline inventory or metadata")
        return 2
    frozen = [line.strip() for line in INVENTORY_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    delta = compare_inventory(current, frozen)
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    delta["SKIP_CHANGED"] = compare_skip_inventory(
        expected_skips(), baseline.get("expected_skip_ids", [])
    )
    for key in ("ADDED", "REMOVED", "SKIP_CHANGED"):
        print(f"{key}: {len(delta[key])}")
        for item in delta[key]:
            print(f"  {item}")
    return 1 if delta["ADDED"] or delta["REMOVED"] or delta["SKIP_CHANGED"] else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="compare current IDs to the frozen inventory")
    args = parser.parse_args(argv)
    if args.check:
        return check()
    print("Use --check. Baseline files are never auto-generated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
