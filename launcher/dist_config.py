"""Distribution configuration loader (PATCH2.8-C path independence).

All paths in distribution_config.yaml are relative to the config file; this
loader resolves them against the distribution root. No absolute dev paths.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml


class DistributionConfig:
    def __init__(self, config_path: Path) -> None:
        self.config_path = Path(config_path).resolve()
        self.root = self.config_path.parent
        data = yaml.safe_load(self.config_path.read_text(encoding="utf-8"))
        self.data = data

    def resolve(self, rel: str) -> Path:
        return (self.root / rel).resolve()

    # distribution areas
    @property
    def studio_app(self) -> Path:
        return self.resolve(self.data["distribution"]["studio_app"])

    @property
    def studio_workdir(self) -> Path:
        return self.resolve(self.data["distribution"]["studio_workdir"])

    @property
    def userdata(self) -> Path:
        return self.resolve(self.data["distribution"]["userdata"])

    @property
    def logs(self) -> Path:
        return self.resolve(self.data["distribution"]["logs"])

    @property
    def configs(self) -> Path:
        return self.resolve(self.data["distribution"]["configs"])

    @property
    def workflows(self) -> Path:
        return self.resolve(self.data["distribution"]["workflows"])

    @property
    def runtime(self) -> Path:
        return self.resolve(self.data["distribution"]["runtime"])

    @property
    def samples(self) -> Path:
        return self.resolve(self.data["distribution"]["samples"])

    # native runtime
    @property
    def native_comfyui_root(self) -> Path:
        return self.resolve(self.data["native_runtime"]["comfyui_root"])

    @property
    def models_root(self) -> Path:
        return self.resolve(self.data["native_runtime"]["models_root"])

    @property
    def comfy_input(self) -> Path:
        return self.resolve(self.data["native_runtime"]["comfy_input"])

    @property
    def comfy_output(self) -> Path:
        return self.resolve(self.data["native_runtime"]["comfy_output"])

    @property
    def comfyui_port(self) -> int:
        return int(self.data["native_runtime"]["port"])

    @property
    def studio_port(self) -> int:
        return int(self.data["studio"]["port"])

    @property
    def runtime_mode(self) -> str:
        return self.data["studio"].get("runtime_mode", "real")

    @property
    def safe_load(self) -> str:
        return self.data["native_runtime"].get("safe_load", "pread")

    def apply_environment(self) -> None:
        """Export resolved paths as env vars for launcher/studio/comfy modules."""
        import os
        os.environ["H3_NATIVE_ROOT"] = str(self.native_comfyui_root)
        os.environ["H3_MODELS_ROOT"] = str(self.models_root)
        os.environ["H3_COMFY_INPUT"] = str(self.comfy_input)
        os.environ["H3_COMFY_OUTPUT"] = str(self.comfy_output)
        os.environ["H3_BASELINE"] = str(self.configs / "native_production_baseline.json")
        os.environ["H3_ENV_REPORT"] = str(self.root / "env_report.json")
        os.environ["H3_STUDIO_DATA"] = str(self.userdata / "studio")
        os.environ["H3_WINDOWS_SAFE_LOAD"] = self.safe_load
