# GitHub Actions CI/CD Pipeline Guide (`.github/workflows/`)

## Pipelines Overview

1. **`test.yml`**:
   - Triggers on `push` and `pull_request` to `main`.
   - Runs `python -m unittest discover -s tests -p "test_*.py"`.
2. **`release.yml`**:
   - Triggers on git tags `v*`.
   - Runs test suite, calls `release/package_builder.py`, creates GitHub release, and attaches `MiniMax-H3-Architecture-System-vX.X.X.zip`.
3. **`diagnostic.yml`**:
   - Weekly scheduled run to execute `scripts/health_check.py` and update `docs/runtime_health_report.md`.
