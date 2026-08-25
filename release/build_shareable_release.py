"""Build the shareable Windows RC package without model weights or userdata.

The generated ZIP is the reviewable source package.  The Windows Setup.exe is
a native WinForms self-extracting launcher with the payload and setup script
embedded as resources; it does not require a visible console or an IExpress
secondary launcher.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / "release"
SETUP_CMD = ROOT / "installer" / "Setup.cmd"
SETUP_PS1 = ROOT / "installer" / "Setup.ps1"
SETUP_LAUNCHER_CS = ROOT / "installer" / "SetupLauncher.cs"
DESKTOP_SHELL_CS = ROOT / "launcher" / "DesktopShell.cs"
APP_ICON = ROOT / "assets" / "architect-video-studio.ico"

ROOT_FILES = (
    "README.md", "LICENSE", "THIRD_PARTY_NOTICES.md",
    "Start_ArchitectVideoStudio.bat", "Open_Native_ComfyUI.bat",
    "native_env.path.example", "distribution_config.yaml",
)
DIRECTORIES = (
    "launcher", "apps", "runtime", "configs", "models", "workflows", "assets",
    "references", "samples", "skills",
)
RELEASE_WORKFLOW_FILES = (
    "01_Exterior_Hero.json", "02_Day_Night_Transition.json",
    "03_Material_Detail.json", "04_Drone_Aerial.json",
    "05_Slow_Walkthrough.json",
)
DOC_FILES = (
    "docs/Quick_Start.md", "docs/Hardware_Requirements.md",
    "docs/Troubleshooting.md", "docs/Advanced_ComfyUI.md",
    "docs/User_Guide.md", "docs/Developer_Architecture.md",
)
HARDENING_FILES = (
    "patches/support_layers/minimax_h3_vae_offload_sync.patch",
)
EXCLUDED_PARTS = {
    ".git", "__pycache__", "userdata", "Logs", "logs", "screenshots",
    "data", "output_package", "internal_archive", "validation", "distribution_test",
    "minimax-h3-architectural-video",
}
EXCLUDED_NAMES = {
    "Start_MiniMax_H3_Architect.bat", "Diagnose_H3.bat", "Install_H3.bat",
    "Start_H3.bat", "Update_H3.bat", "env_report.json", "runtime.lock",
    "video_output_validation.json", "workflow_validation_report.json",
    # Historical developer-machine metadata is not an install input. Leaving
    # it in a portable payload can seed a stale absolute path before the
    # cross-drive environment discovery runs.
    "system_config.json",
    "run_prototype.py",
    "capture_r2b0_setup_screenshots.mjs", "capture_screenshots.mjs",
}
EXCLUDED_PREFIXES = (
    "audit_", "rc3", "rc33", "production_environment_report",
    "official_skill_validation_report", "workflow_reality_report",
)
# Model bodies are never bundled.  ``.bin`` is included as well because the
# repository may contain tiny fixture placeholders with model-like names; the
# installer must not present any such file as an installed model asset.
EXCLUDED_SUFFIXES = {".safetensors", ".bin", ".mp4", ".avi", ".mov", ".pyc"}


def _copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _allowed(relative: Path) -> bool:
    name = relative.name.lower()
    return not any(part in EXCLUDED_PARTS for part in relative.parts) and \
        relative.name not in EXCLUDED_NAMES and \
        not name.startswith(EXCLUDED_PREFIXES) and \
        relative.suffix.lower() not in EXCLUDED_SUFFIXES


def _copy_tree(source: Path, destination: Path) -> int:
    count = 0
    for item in source.rglob("*"):
        if not item.is_file():
            continue
        rel = item.relative_to(source)
        if _allowed(rel):
            _copy_file(item, destination / rel)
            count += 1
    return count


def assemble_payload(stage: Path) -> int:
    payload = stage / "payload"
    count = 0
    for name in ROOT_FILES:
        source = ROOT / name
        if source.is_file():
            _copy_file(source, payload / name)
            count += 1
    for directory in DIRECTORIES:
        source = ROOT / directory
        if source.is_dir():
            if directory == "workflows":
                for name in RELEASE_WORKFLOW_FILES:
                    workflow = source / name
                    if workflow.is_file() and _allowed(workflow.relative_to(source)):
                        _copy_file(workflow, payload / directory / name)
                        count += 1
            else:
                count += _copy_tree(source, payload / directory)
    for name in DOC_FILES:
        source = ROOT / name
        if source.is_file():
            _copy_file(source, payload / name)
            count += 1
    _copy_file(ROOT / "configs" / "installer_bootstrap.json",
               payload / "configs" / "installer_bootstrap.json")
    for relative in HARDENING_FILES:
        source = ROOT / relative
        if source.is_file():
            _copy_file(source, payload / relative)
            count += 1
    _copy_file(SETUP_CMD, stage / "Setup.cmd")
    _copy_file(SETUP_PS1, stage / "Setup.ps1")
    return count + 2


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _find_csc() -> Path:
    compiler_candidates = [
        Path(os.environ.get("WINDIR", r"C:\Windows"))
        / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe",
        Path(os.environ.get("WINDIR", r"C:\Windows"))
        / "Microsoft.NET" / "Framework" / "v4.0.30319" / "csc.exe",
    ]
    compiler = next((p for p in compiler_candidates if p.is_file()), None)
    if compiler is None:
        compiler_name = shutil.which("csc.exe")
        compiler = Path(compiler_name) if compiler_name else None
    if compiler is None:
        raise RuntimeError("The .NET Framework C# compiler is required to build Windows GUI launchers.")
    return compiler


def _find_webview2_sdk() -> tuple[Path, Path, Path]:
    """Use the installed WebView2 SDK and ship its managed/native host files."""
    roots = [
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
        / "Microsoft Visual Studio" / "2022" / "BuildTools" / "Common7" / "IDE" / "PrivateAssemblies",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        / "Microsoft Visual Studio" / "2022" / "BuildTools" / "Common7" / "IDE" / "PrivateAssemblies",
    ]
    for root in roots:
        core = root / "Microsoft.Web.WebView2.Core.dll"
        wpf = root / "Microsoft.Web.WebView2.Wpf.dll"
        if not (core.is_file() and wpf.is_file()):
            continue

        # Visual Studio's PrivateAssemblies directory contains the x86 loader
        # for the IDE.  The desktop shell is compiled x64, so shipping that
        # file causes BadImageFormatException before CoreWebView2 is created.
        # Prefer the matching x64 native loader from the installed WebView2
        # runtime bundle, while retaining a same-directory fallback for other
        # SDK layouts.
        loader_candidates = [
            root.parent / "CommonExtensions" / "Microsoft" / "Markdown" / "runtimes" / "win-x64" / "native" / "WebView2Loader.dll",
            root / "runtimes" / "win-x64" / "native" / "WebView2Loader.dll",
            root / "WebView2Loader.dll",
        ]
        loader = next((candidate for candidate in loader_candidates if candidate.is_file()), None)
        if loader is not None:
            return core, wpf, loader
    raise RuntimeError("Microsoft WebView2 SDK assemblies are required to build the desktop shell.")


def build_desktop_shell(payload: Path) -> Path:
    output = payload / "launcher" / "ArchitectVideoStudioDesktop.exe"
    output.parent.mkdir(parents=True, exist_ok=True)
    core, wpf, loader = _find_webview2_sdk()
    framework = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319"
    wpf_refs = framework / "WPF"
    result = subprocess.run(
        [_find_csc(), "/nologo", "/target:winexe", "/optimize+",
         "/platform:x64", "/r:System.Windows.Forms.dll", "/r:System.Drawing.dll",
         f"/r:{wpf_refs / 'WindowsFormsIntegration.dll'}", f"/r:{wpf_refs / 'PresentationCore.dll'}",
         f"/r:{wpf_refs / 'PresentationFramework.dll'}", f"/r:{wpf_refs / 'WindowsBase.dll'}",
         f"/r:{framework / 'System.Xaml.dll'}",
         f"/r:{core}", f"/r:{wpf}",
         f"/win32icon:{APP_ICON}",
         f"/out:{output}", str(DESKTOP_SHELL_CS)],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0 or not output.is_file():
        raise RuntimeError(f"Desktop shell compilation failed: {result.stdout}\n{result.stderr}")
    shutil.copy2(core, output.parent / core.name)
    shutil.copy2(wpf, output.parent / wpf.name)
    shutil.copy2(loader, output.parent / loader.name)
    return output


def build_setup_launcher(stage: Path) -> Path:
    compiler = _find_csc()
    output = stage / "SetupLauncher.exe"
    result = subprocess.run(
        [str(compiler), "/nologo", "/target:winexe", "/optimize+",
         "/r:System.Windows.Forms.dll", "/r:System.Drawing.dll",
         f"/win32icon:{APP_ICON}",
         f"/resource:{stage / 'payload.zip'},payload.zip",
         f"/resource:{stage / 'Setup.ps1'},Setup.ps1",
         f"/out:{output}", str(SETUP_LAUNCHER_CS)],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0 or not output.is_file():
        raise RuntimeError(f"Setup launcher compilation failed: {result.stdout}\n{result.stderr}")
    return output


def build_zip(stage: Path, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for item in sorted(stage.rglob("*")):
            if item.is_file():
                archive.write(item, item.relative_to(stage).as_posix())
    return output


def build_setup(stage: Path, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(stage / "SetupLauncher.exe", output)
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=RELEASE / "dist")
    args = parser.parse_args()
    output_dir = (ROOT / args.output_dir).resolve() if not args.output_dir.is_absolute() else args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="architect-video-studio-release-") as temp:
        stage = Path(temp)
        files = assemble_payload(stage)
        build_desktop_shell(stage / "payload")
        files += 4
        build_zip(stage / "payload", stage / "payload.zip")
        build_setup_launcher(stage)
        setup = build_setup(stage, output_dir / "ArchitectVideoStudio-Setup.exe")
        package = build_zip(stage, output_dir / "ArchitectVideoStudio-RC.zip")
    # The ZIP is also a convenient reviewable package; put the generated EXE
    # at its root without ever adding model files or userdata.
    with zipfile.ZipFile(package, "a", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(setup, "ArchitectVideoStudio-Setup.exe")
    manifest = {
        "schema_version": 1,
        "product": "Architect Video Studio",
        "candidate": "v0.8.0-rc1-shareable",
        "installer": setup.name,
        "package": package.name,
        "payload_files": files,
        "models_bundled": False,
        "gpu_product_acceptance": "PENDING_OWNER_AUTHORIZATION",
        "hardware_policy": {"supported_vram_gb": 24, "lower_vram": "EXPERIMENTAL"},
        "runtime_contract": json.loads(
            (ROOT / "configs" / "release_runtime_manifest.json").read_text(encoding="utf-8")
        ),
        "models_root_policy": "independent shared Models root; existing valid files are reused",
        "sha256": {setup.name: _sha256(setup), package.name: _sha256(package)},
    }
    (output_dir / "SHAREABLE_RC_MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"setup": str(setup), "package": str(package), "manifest": manifest}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
