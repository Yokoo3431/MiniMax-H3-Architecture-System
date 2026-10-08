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

For an isolated local acceptance run, add `--isolated`:

```text
ArchitectVideoStudio-Setup.exe --app-only --silent --isolated --install-root "<new-app-folder>" --bootstrap-python "<existing-python.exe>"
```

This explicit mode is handled natively by the same self-extracting
distribution executable, so it does not execute PowerShell. It requires a new
empty target or a target carrying this installer's isolation marker. It does
not write shared uninstall/App Paths registry keys, create a Start Menu
shortcut, remember the install location, or auto-launch the desktop shell.
Re-running against the same marked root performs an App-only repair; an
unmarked existing folder is rejected. Keep the distribution executable for
repair and uninstall.

The installed launcher has a headless setup-only entry for isolated acceptance:

```text
"<existing-python.exe>" -B launcher/launcher.py start --app-only --no-browser --studio-port 18788 --data-root "<separate-data-folder>"
```

This path requires an explicit non-production port and a data directory
outside the install/source tree. It skips runtime discovery and starts only
the Studio setup service; it does not inspect, start, or modify ComfyUI. The
selected data root contains separate `studio/` and `logs/` directories, while
child temp and package caches are rooted alongside them under that data root,
not inside the installed application. Stop the service with Ctrl+C in that
same process session.

Remove a marked isolated install without a UI prompt using the same
distribution executable:

```text
ArchitectVideoStudio-Setup.exe --uninstall --isolated --silent --install-root "<app-folder>"
```

Silent uninstall requires a valid ownership marker, the installed launcher,
and no isolated launcher lock. It removes only the application files under
that root, preserves in-root user data and model folders, and does not touch
the separate data root.

## Runtime state and data

Without a separately configured ComfyUI runtime, Studio starts in setup mode.
Projects, Studies, settings, and diagnostics remain available, while generation
capability is reported as unavailable. The application does not scan all local
drives to auto-adopt an unrelated runtime in this unbound App-only state.

The bootstrap interpreter reference and setup state are stored with the local
installation. By default, user data remains under that installation's
`userdata` folder; isolated acceptance may select a separate `--data-root`.
Repair/reinstall updates application payload files without provisioning a
runtime; uninstall preserves in-root `userdata` and does not delete the
separate data root, externally referenced runtimes, or model directories.

## PowerShell policy

The normal interactive installer path uses Windows PowerShell without
changing execution policy or using `-ExecutionPolicy Bypass`; it fails closed
when policy does not permit the local script. The explicit silent isolated
App-only install/uninstall path is native and remains available under a
Restricted policy. No path weakens machine or user security policy.
