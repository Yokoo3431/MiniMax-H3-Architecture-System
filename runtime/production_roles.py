"""Explicit runtime-role policy for managed production promotion."""

from __future__ import annotations

from pathlib import Path

ACTIVE_PRODUCTION_NATIVE = "ACTIVE_PRODUCTION_NATIVE"
LEGACY_VALIDATED_REFERENCE = "LEGACY_VALIDATED_REFERENCE"
TEST_RUNTIME = "TEST_RUNTIME"
VALIDATION_RUNTIME = "VALIDATION_RUNTIME"
INSTALL_TARGET = "INSTALL_TARGET"
MANAGED_RUNTIME_NAME = "ArchitectVideoStudio_Runtime"


def is_managed_runtime_path(path: Path) -> bool:
    parts = {part.casefold() for part in Path(path).resolve().parts}
    return MANAGED_RUNTIME_NAME.casefold() in parts and "validation" not in parts and "test" not in parts


def can_promote_validation_runtime(source: Path, target: Path) -> bool:
    source_parts = {part.casefold() for part in Path(source).resolve().parts}
    return "validation" in source_parts and is_managed_runtime_path(target)


def role_state(active: Path, models: Path, legacy: Path, test: Path,
               validation: Path | None = None, install_target: Path | None = None) -> dict:
    """Return serializable role metadata without scanning or selecting paths."""
    return {
        "active_role": ACTIVE_PRODUCTION_NATIVE,
        "active_native_root": str(Path(active).resolve()),
        "models_root": str(Path(models).resolve()),
        "legacy_validated_reference": str(Path(legacy).resolve()),
        "test_runtime": str(Path(test).resolve()),
        "validation_runtime": str(Path(validation).resolve()) if validation else None,
        "install_target": str(Path(install_target).resolve()) if install_target else None,
        "selection_policy": [
            "explicitly configured active_native_root",
            "persisted adopted production runtime",
            "SETUP_REQUIRED",
        ],
    }


__all__ = [
    "ACTIVE_PRODUCTION_NATIVE", "LEGACY_VALIDATED_REFERENCE", "TEST_RUNTIME",
    "VALIDATION_RUNTIME", "INSTALL_TARGET", "MANAGED_RUNTIME_NAME",
    "is_managed_runtime_path", "can_promote_validation_runtime", "role_state",
]
