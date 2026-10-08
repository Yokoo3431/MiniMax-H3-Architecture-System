# App-only installation

Architect Video Studio can be installed without provisioning ComfyUI or H3
models. This mode installs the real Studio application payload and leaves the
generation runtime unbound until the user configures one later in Environment
Center.

## Requirements

- Windows 10/11 and the standard Windows PowerShell 5.1 installation path.
- An existing Python 3.10 or later interpreter. Setup reuses that interpreter;
  it does not install Python or download Python packages.
- The installed desktop shell uses the Windows WebView2 runtime when it is
  available; the local Studio HTTP service can also be opened in a browser.

## Install

Run `ArchitectVideoStudio-Setup.exe`, select **App-only**, and choose the
existing `python.exe` and an installation folder. Setup installs and registers
the application for the current Windows user. It does not download, extract,
copy, upgrade, restart, or modify ComfyUI, model files, or runtime support.

For managed acceptance automation, the self-extracting installer also accepts
the explicit App-only command form:

```text
ArchitectVideoStudio-Setup.exe --app-only --silent --install-root "<app-folder>" --bootstrap-python "<existing-python.exe>"
```

Silent mode is restricted to App-only installation. It does not provide a
silent path into runtime provisioning.

## Runtime state and data

Without a separately configured ComfyUI runtime, Studio starts in setup mode.
Projects, Studies, settings, and diagnostics remain available, while generation
capability is reported as unavailable. The application does not scan all local
drives to auto-adopt an unrelated runtime in this unbound App-only state.

The bootstrap interpreter reference and setup state are stored with the local
installation. User data remains under that installation's `userdata` folder.
Repair/reinstall updates application payload files without provisioning a
runtime; uninstall preserves `userdata` and does not delete externally
referenced runtimes or model directories.

## PowerShell policy

Setup and uninstall invoke Windows PowerShell without changing execution
policy and without `-ExecutionPolicy Bypass`. A policy that does not permit the
local installer script will fail closed; Setup does not weaken machine or user
security policy to force installation.
