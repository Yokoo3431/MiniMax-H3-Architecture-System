"""Windows Setup runtime-adoption contract tests using synthetic folders only."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _require_local_script_policy(test_case: unittest.TestCase,
                                 powershell: Path) -> None:
    if not powershell.is_file():
        test_case.skipTest("Windows PowerShell 5.1 is unavailable")
    probe = subprocess.run(
        [str(powershell), "-NoLogo", "-NoProfile", "-NonInteractive",
         "-Command", "Get-ExecutionPolicy"],
        capture_output=True, text=True, timeout=10, check=False,
    )
    policy = probe.stdout.strip().splitlines()[-1] if probe.stdout.strip() else ""
    if probe.returncode != 0 or policy not in {"RemoteSigned", "Unrestricted"}:
        test_case.skipTest(
            "effective PowerShell policy does not permit unsigned local test scripts; "
            "the test will not override execution policy"
        )


class TestSetupRuntimeCompatibility(unittest.TestCase):
    def _validation_functions(self, setup: str) -> str:
        def extract(name: str, next_name: str) -> str:
            start = setup.index(f"function {name}")
            end = setup.index(f"function {next_name}", start)
            return setup[start:end]

        return "\n".join((
            extract("Test-RuntimeLayout", "Test-RuntimeCompatibility"),
            extract("Test-RuntimeCompatibility", "Get-RegisteredRuntimePath"),
            extract("Resolve-ValidationRuntime", "Assert-ValidationTarget"),
            extract("Assert-ValidationTarget", "Invoke-ValidationInstall"),
            extract("Invoke-ValidationInstall", "Find-ExistingRuntime"),
            extract("Copy-Payload", "Stop-ExistingDesktopShell"),
        ))

    def test_validation_mode_stages_only_app_and_reuses_registered_runtime(self):
        powershell = (
            Path(os.environ.get("WINDIR", r"C:\Windows"))
            / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        )
        if not powershell.is_file():
            self.skipTest("Windows PowerShell 5.1 is unavailable")

        setup = (ROOT / "installer" / "Setup.ps1").read_text(encoding="utf-8")
        functions = self._validation_functions(setup)
        with tempfile.TemporaryDirectory(prefix="avs-validation-stage-") as temp:
            root = Path(temp)
            runtime = root / "registered-runtime"
            (runtime / "python_embeded").mkdir(parents=True)
            (runtime / "python_embeded" / "python.exe").write_bytes(b"existing-python")
            (runtime / "ComfyUI").mkdir()
            (runtime / "ComfyUI" / "main.py").write_text("existing ComfyUI", encoding="utf-8")
            version = runtime / "ComfyUI" / "comfyui_version.py"
            version.write_text('__version__ = "0.33.1"\n', encoding="utf-8")
            main_before = (runtime / "ComfyUI" / "main.py").read_bytes()
            python_before = (runtime / "python_embeded" / "python.exe").read_bytes()
            payload = root / "payload"
            payload.mkdir()
            (payload / "app-entry.py").write_text("synthetic AVS payload", encoding="utf-8")
            target = root / f"avs-validation-{uuid.uuid4().hex}"
            script = root / "validation-stage.ps1"
            script.write_text(
                functions
                + "\nfunction Get-RegisteredRuntimePath([string]$RegistrationPath) { return "
                + _ps_quote(str(runtime)) + " }\n"
                + "function Get-PSDrive { throw 'validation mode must not scan drives' }\n"
                + "function Invoke-ResumableDownload([string]$Url, [string]$Destination) { throw 'validation mode must not download' }\n"
                + "$config = [pscustomobject]@{ runtime = [pscustomobject]@{ version = '0.33.1' } }\n"
                + "$result = Invoke-ValidationInstall $config " + _ps_quote(str(payload)) + " "
                + _ps_quote(str(target)) + " 'synthetic-registration'\n"
                + "if ($result.Mode -ne 'VALIDATION_PAYLOAD_ONLY') { throw 'wrong validation mode' }\n"
                + "if ($result.RuntimeVersion -ne '0.33.1') { throw 'runtime version not recorded' }\n"
                + "if (-not (Test-Path -LiteralPath (Join-Path $result.InstallRoot 'app-entry.py'))) { throw 'AVS payload was not staged' }\n"
                + "if (-not (Test-Path -LiteralPath (Join-Path $result.InstallRoot 'native_env.path'))) { throw 'runtime pointer was not staged' }\n"
                + "if (Test-Path -LiteralPath (Join-Path $result.InstallRoot 'ArchitectVideoStudio_Runtime')) { throw 'ComfyUI was copied into the validation install' }\n"
                + "if ((Get-Content -LiteralPath (Join-Path $result.InstallRoot 'native_env.path') -Raw).Trim() -ne "
                + _ps_quote(str(runtime)) + ") { throw 'validation did not point at the existing runtime' }\n"
                + "Write-Output 'PASS'\n",
                encoding="utf-8",
            )
            _require_local_script_policy(self, powershell)
            result = subprocess.run(
                [str(powershell), "-NoLogo", "-NoProfile", "-NonInteractive",
                 "-File", str(script)],
                capture_output=True, text=True, timeout=20,
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            self.assertIn("PASS", result.stdout)
            self.assertEqual((runtime / "ComfyUI" / "main.py").read_bytes(), main_before)
            self.assertEqual((runtime / "python_embeded" / "python.exe").read_bytes(), python_before)
            self.assertEqual(version.read_text(encoding="utf-8"), '__version__ = "0.33.1"\n')

    def test_validation_mode_fails_closed_without_matching_registered_runtime(self):
        powershell = (
            Path(os.environ.get("WINDIR", r"C:\Windows"))
            / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        )
        if not powershell.is_file():
            self.skipTest("Windows PowerShell 5.1 is unavailable")

        setup = (ROOT / "installer" / "Setup.ps1").read_text(encoding="utf-8")
        functions = self._validation_functions(setup)
        with tempfile.TemporaryDirectory(prefix="avs-validation-fail-closed-") as temp:
            root = Path(temp)
            runtime = root / "registered-runtime"
            (runtime / "python_embeded").mkdir(parents=True)
            (runtime / "python_embeded" / "python.exe").write_bytes(b"existing-python")
            (runtime / "ComfyUI").mkdir()
            (runtime / "ComfyUI" / "main.py").write_text("existing", encoding="utf-8")
            (runtime / "ComfyUI" / "comfyui_version.py").write_text(
                '__version__ = "0.36.0"\n', encoding="utf-8"
            )
            payload = root / "payload"
            payload.mkdir()
            target = root / f"avs-validation-{uuid.uuid4().hex}"
            script = root / "validation-fail-closed.ps1"
            script.write_text(
                functions
                + "\n$script:registeredRuntime = " + _ps_quote(str(runtime)) + "\n"
                + "function Get-RegisteredRuntimePath([string]$RegistrationPath) { return $script:registeredRuntime }\n"
                + "function Get-PSDrive { throw 'validation mode must not scan drives' }\n"
                + "function Invoke-ResumableDownload([string]$Url, [string]$Destination) { throw 'validation mode must not download' }\n"
                + "$config = [pscustomobject]@{ runtime = [pscustomobject]@{ version = '0.33.1' } }\n"
                + "try { Invoke-ValidationInstall $config " + _ps_quote(str(payload)) + " "
                + _ps_quote(str(target)) + " 'synthetic-registration'; throw 'mismatched runtime accepted' } catch { if ($_.Exception.Message -notmatch 'stopped without updating or installing a runtime') { throw } }\n"
                + "if (Test-Path -LiteralPath " + _ps_quote(str(target)) + ") { throw 'target created after runtime mismatch' }\n"
                + "$script:registeredRuntime = ''\n"
                + "try { Resolve-ValidationRuntime $config 'synthetic-registration'; throw 'missing registered runtime accepted' } catch { if ($_.Exception.Message -notmatch 'already registered ComfyUI runtime') { throw } }\n"
                + "Write-Output 'PASS'\n",
                encoding="utf-8",
            )
            _require_local_script_policy(self, powershell)
            result = subprocess.run(
                [str(powershell), "-NoLogo", "-NoProfile", "-NonInteractive",
                 "-File", str(script)],
                capture_output=True, text=True, timeout=20,
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            self.assertIn("PASS", result.stdout)

    def test_validation_mode_target_is_confined_and_never_overwritten(self):
        powershell = (
            Path(os.environ.get("WINDIR", r"C:\Windows"))
            / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        )
        if not powershell.is_file():
            self.skipTest("Windows PowerShell 5.1 is unavailable")

        setup = (ROOT / "installer" / "Setup.ps1").read_text(encoding="utf-8")
        functions = self._validation_functions(setup)
        with tempfile.TemporaryDirectory(prefix="avs-validation-target-") as temp:
            root = Path(temp)
            existing = root / f"avs-validation-{uuid.uuid4().hex}"
            existing.mkdir()
            sentinel = existing / "keep.txt"
            sentinel.write_text("preserve", encoding="utf-8")
            outside = ROOT / f"avs-validation-{uuid.uuid4().hex}"
            script = root / "validation-target.ps1"
            script.write_text(
                functions
                + "\n$existing = " + _ps_quote(str(existing)) + "\n"
                + "try { Assert-ValidationTarget $existing; throw 'existing target accepted' } catch { if ($_.Exception.Message -notmatch 'will not overwrite') { throw } }\n"
                + "try { Assert-ValidationTarget " + _ps_quote(str(outside)) + "; throw 'outside target accepted' } catch { if ($_.Exception.Message -notmatch 'inside the system temporary directory') { throw } }\n"
                + "Write-Output 'PASS'\n",
                encoding="utf-8",
            )
            _require_local_script_policy(self, powershell)
            result = subprocess.run(
                [str(powershell), "-NoLogo", "-NoProfile", "-NonInteractive",
                 "-File", str(script)],
                capture_output=True, text=True, timeout=20,
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            self.assertIn("PASS", result.stdout)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve")

    def test_validation_branch_exits_before_runtime_or_registration_mutations(self):
        setup = (ROOT / "installer" / "Setup.ps1").read_text(encoding="utf-8")
        self.assertTrue(setup.lstrip().startswith("param("))
        start = setup.index("if ($ValidationMode)")
        end = setup.index("$defaultRoot =", start)
        branch = setup[start:end]
        for forbidden in (
            "Stop-ExistingDesktopShell", "Stop-ExistingManagedServices",
            "Ensure-Runtime", "Install-H3FrontendBridge",
            "Ensure-H3ModelRootBridge", "Reconcile-H3RuntimeSupport",
            "Register-WindowsApplication", "Start-Process",
        ):
            self.assertNotIn(forbidden, branch)
        self.assertIn("return", branch)
        stage_start = setup.index("function Invoke-ValidationInstall")
        stage_end = setup.index("function Find-ExistingRuntime", stage_start)
        stage = setup[stage_start:stage_end]
        self.assertNotIn("Find-ExistingRuntime", stage)
        self.assertNotIn("Invoke-ResumableDownload", stage)

    def test_setup_script_parses_without_executing_installer(self):
        powershell = (
            Path(os.environ.get("WINDIR", r"C:\Windows"))
            / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        )
        if not powershell.is_file():
            self.skipTest("Windows PowerShell 5.1 is unavailable")
        setup_path = ROOT / "installer" / "Setup.ps1"
        command = (
            "$ErrorActionPreference = 'Stop'; "
            f"[void][scriptblock]::Create((Get-Content -LiteralPath {_ps_quote(str(setup_path))} -Raw)); "
            "Write-Output 'PASS'"
        )
        result = subprocess.run(
            [str(powershell), "-NoLogo", "-NoProfile", "-NonInteractive",
             "-Command", command],
            capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertIn("PASS", result.stdout)

    def test_runtime_version_must_be_proven_and_unknown_target_is_preserved(self):
        powershell = (
            Path(os.environ.get("WINDIR", r"C:\Windows"))
            / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        )
        if not powershell.is_file():
            self.skipTest("Windows PowerShell 5.1 is unavailable")

        setup = (ROOT / "installer" / "Setup.ps1").read_text(encoding="utf-8")
        start = setup.index("function Test-RuntimeLayout")
        end = setup.index("function Find-ExistingRuntime", start)
        functions = setup[start:end]
        ensure_start = setup.index("function Ensure-Runtime")
        ensure_end = setup.index("function Copy-Payload", ensure_start)
        ensure_function = setup[ensure_start:ensure_end]

        with tempfile.TemporaryDirectory(prefix="avs-runtime-version-contract-") as temp:
            root = Path(temp)

            def runtime(name: str, source: str | None, marker: str | None,
                        *, layout: bool = True) -> Path:
                candidate = root / name
                if layout:
                    (candidate / "python_embeded").mkdir(parents=True)
                    (candidate / "python_embeded" / "python.exe").write_bytes(b"fixture")
                    comfy = candidate / "ComfyUI"
                    comfy.mkdir(parents=True)
                    (comfy / "main.py").write_text("fixture", encoding="utf-8")
                    if source is not None:
                        (comfy / "comfyui_version.py").write_text(source, encoding="utf-8")
                if marker is not None:
                    (candidate / "runtime_version.json").write_text(marker, encoding="utf-8")
                return candidate

            runtime("source-only", '__version__ = "0.33.1"\n', None)
            runtime("matching-marker", '__version__ = "0.33.1"\n', '{"comfyui":"0.33.1"}')
            runtime("unknown-source", None, None)
            runtime("marker-only", None, '{"comfyui":"0.33.1"}')
            runtime("wrong-source", '__version__ = "0.34.0"\n', '{"comfyui":"0.33.1"}')
            runtime("wrong-marker", '__version__ = "0.33.1"\n', '{"comfyui":"0.34.0"}')
            runtime("invalid-marker", '__version__ = "0.33.1"\n', '{invalid-json')
            runtime("incomplete", '__version__ = "0.33.1"\n', None, layout=False)

            script = root / "runtime-compatibility-tests.ps1"
            script.write_text(
                functions
                + "\n"
                + ensure_function
                + "\n$root = " + _ps_quote(str(root)) + "\n"
                + "$expected = '0.33.1'\n"
                + "if (-not (Test-RuntimeCompatibility (Join-Path $root 'source-only') $expected)) { throw 'source-only pinned runtime rejected' }\n"
                + "if (-not (Test-RuntimeCompatibility (Join-Path $root 'matching-marker') $expected)) { throw 'matching marker/source rejected' }\n"
                + "foreach ($name in @('unknown-source','marker-only','wrong-source','wrong-marker','invalid-marker','incomplete')) {\n"
                + "  if (Test-RuntimeCompatibility (Join-Path $root $name) $expected) { throw \"unverified runtime accepted: $name\" }\n"
                + "}\nWrite-Output 'PASS'\n",
                encoding="utf-8",
            )
            with script.open("a", encoding="utf-8") as stream:
                stream.write(
                    "\n$script:findExistingCalled = $false\n"
                    "function Find-ExistingRuntime([string]$InstallRoot, [string]$ExpectedVersion, [string]$RegistrationPath, [ref]$AnyRuntimeFound) { $script:findExistingCalled = $true; return $null }\n"
                    "$installRoot = Join-Path $root 'install'\n"
                    "$target = Join-Path $installRoot 'ArchitectVideoStudio_Runtime'\n"
                    "New-Item -ItemType Directory -Force -Path (Join-Path $target 'python_embeded') | Out-Null\n"
                    "New-Item -ItemType Directory -Force -Path (Join-Path $target 'ComfyUI') | Out-Null\n"
                    "Set-Content -LiteralPath (Join-Path $target 'python_embeded\\python.exe') -Value 'fixture'\n"
                    "$targetMain = Join-Path $target 'ComfyUI\\main.py'\n"
                    "Set-Content -LiteralPath $targetMain -Value 'unverified fixture'\n"
                    "$beforeHash = (Get-FileHash -LiteralPath $targetMain -Algorithm SHA256).Hash\n"
                    "$config = [pscustomobject]@{ runtime = [pscustomobject]@{ version = $expected } }\n"
                    "try { Ensure-Runtime $config $installRoot (Join-Path $root 'cache'); throw 'unverified target unexpectedly accepted' } catch { if ($_.Exception.Message -notmatch 'cannot be proven to match the pinned ComfyUI version') { throw } }\n"
                    "if (-not (Test-Path -LiteralPath $targetMain)) { throw 'unverified target was removed' }\n"
                    "if ((Get-FileHash -LiteralPath $targetMain -Algorithm SHA256).Hash -ne $beforeHash) { throw 'unverified target was modified' }\n"
                    "if ($script:findExistingCalled) { throw 'unverified target triggered cross-drive runtime discovery' }\n"
                )
            _require_local_script_policy(self, powershell)
            result = subprocess.run(
                [str(powershell), "-NoLogo", "-NoProfile", "-NonInteractive",
                 "-File", str(script)],
                capture_output=True, text=True, timeout=20,
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            self.assertIn("PASS", result.stdout, f"stdout={result.stdout!r}; stderr={result.stderr!r}")

        ensure_start = setup.index("function Ensure-Runtime")
        ensure_end = setup.index("function Copy-Payload", ensure_start)
        ensure = setup[ensure_start:ensure_end]
        self.assertIn("cannot be proven to match the pinned ComfyUI version", ensure)
        self.assertNotIn("Remove-Item -LiteralPath $runtime", ensure)

    def test_setup_reuses_existing_pinned_runtime_without_download_or_copy(self):
        powershell = (
            Path(os.environ.get("WINDIR", r"C:\Windows"))
            / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        )
        if not powershell.is_file():
            self.skipTest("Windows PowerShell 5.1 is unavailable")

        setup = (ROOT / "installer" / "Setup.ps1").read_text(encoding="utf-8")
        compat_start = setup.index("function Test-RuntimeLayout")
        find_start = setup.index("function Find-ExistingRuntime", compat_start)
        extractor_start = setup.index("function Find-ExistingExtractor", find_start)
        ensure_start = setup.index("function Ensure-Runtime", extractor_start)
        ensure_end = setup.index("function Copy-Payload", ensure_start)
        functions = (
            setup[compat_start:find_start]
            + setup[find_start:extractor_start]
            + setup[ensure_start:ensure_end]
        )

        with tempfile.TemporaryDirectory(prefix="avs-runtime-reuse-contract-") as temp:
            root = Path(temp)
            existing = root / "ArchitectVideoStudio_Runtime"
            python = existing / "python_embeded" / "python.exe"
            main = existing / "ComfyUI" / "main.py"
            version = existing / "ComfyUI" / "comfyui_version.py"
            marker = existing / "runtime_version.json"
            python.parent.mkdir(parents=True)
            main.parent.mkdir(parents=True)
            python.write_bytes(b"synthetic-runtime-python")
            main.write_text("synthetic runtime", encoding="utf-8")
            version.write_text('__version__ = "0.33.1"\n', encoding="utf-8")
            marker.write_text('{"comfyui":"0.33.1","pread":"pread"}', encoding="utf-8")
            original = {path: path.read_bytes() for path in (python, main, version, marker)}

            install_root = root / "fresh-app-install"
            cache = install_root / "userdata" / "cache" / "bootstrap"
            expected = _ps_quote(str(existing))
            config = (
                "[pscustomobject]@{ runtime = [pscustomobject]@{ "
                "version = '0.33.1'; asset = 'must-not-download.7z'; "
                "url = 'https://invalid.example/runtime.7z'; sha256 = 'unused' } }"
            )
            script = root / "reuse-existing-runtime.ps1"
            script.write_text(
                functions
                + "\nfunction Get-RegisteredRuntimePath([string]$RegistrationPath) { return '' }\n"
                + "\n$script:downloadCalled = $false\n"
                + "function Invoke-ResumableDownload([string]$Url, [string]$Destination) { "
                  "$script:downloadCalled = $true; throw 'runtime download was attempted' }\n"
                + "$installRoot = " + _ps_quote(str(install_root)) + "\n"
                + "$cache = " + _ps_quote(str(cache)) + "\n"
                + "$expected = " + expected + "\n"
                + "$config = " + config + "\n"
                + "$result = Ensure-Runtime $config $installRoot $cache\n"
                + "if (-not [string]::Equals([IO.Path]::GetFullPath($result), "
                  "[IO.Path]::GetFullPath($expected), [StringComparison]::OrdinalIgnoreCase)) { "
                  "throw 'existing runtime was not selected' }\n"
                + "if ($script:downloadCalled) { throw 'runtime download was attempted' }\n"
                + "if (Test-Path -LiteralPath $installRoot) { throw 'new runtime/app root was created' }\n"
                + "if (Test-Path -LiteralPath $cache) { throw 'download cache was created' }\n"
                + "Write-Output 'PASS'\n",
                encoding="utf-8",
            )
            _require_local_script_policy(self, powershell)
            result = subprocess.run(
                [str(powershell), "-NoLogo", "-NoProfile", "-NonInteractive",
                 "-File", str(script)],
                capture_output=True, text=True, timeout=20,
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            self.assertIn("PASS", result.stdout)
            self.assertEqual({path: path.read_bytes() for path in original}, original)

    def test_setup_prefers_registered_existing_runtime_without_drive_scan(self):
        powershell = (
            Path(os.environ.get("WINDIR", r"C:\Windows"))
            / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        )
        if not powershell.is_file():
            self.skipTest("Windows PowerShell 5.1 is unavailable")

        setup = (ROOT / "installer" / "Setup.ps1").read_text(encoding="utf-8")
        start = setup.index("function Test-RuntimeLayout")
        end = setup.index("function Find-ExistingExtractor", start)
        functions = setup[start:end]

        with tempfile.TemporaryDirectory(prefix="avs-registered-runtime-contract-") as temp:
            root = Path(temp)
            runtime = root / "shared-runtime" / "ArchitectVideoStudio_Runtime"
            (runtime / "python_embeded").mkdir(parents=True)
            (runtime / "python_embeded" / "python.exe").write_bytes(b"fixture-python")
            comfy = runtime / "ComfyUI"
            comfy.mkdir()
            (comfy / "main.py").write_text("fixture", encoding="utf-8")
            (comfy / "comfyui_version.py").write_text(
                '__version__ = "0.33.1"\n', encoding="utf-8"
            )
            (runtime / "runtime_version.json").write_text(
                '{"comfyui":"0.33.1","pread":"pread"}', encoding="utf-8"
            )

            decoy = root / "ArchitectVideoStudio_Runtime"
            (decoy / "python_embeded").mkdir(parents=True)
            (decoy / "python_embeded" / "python.exe").write_bytes(b"decoy-python")
            (decoy / "ComfyUI" / "custom_nodes" / "ComfyUI_RH_MinMaxH3").mkdir(parents=True)
            (decoy / "ComfyUI" / "custom_nodes" / "ComfyUI-VideoHelperSuite").mkdir()
            (decoy / "ComfyUI" / "main.py").write_text("decoy", encoding="utf-8")
            (decoy / "ComfyUI" / "comfyui_version.py").write_text(
                '__version__ = "0.33.1"\n', encoding="utf-8"
            )
            (decoy / "runtime_version.json").write_text(
                '{"comfyui":"0.33.1","pread":"pread"}', encoding="utf-8"
            )

            registered_app = root / "previous-app"
            registered_app.mkdir()
            (registered_app / "native_env.path").write_text(
                str(runtime), encoding="utf-8"
            )
            install_root = root / "new-app" / "ArchitectVideoStudio"
            registration_path = (
                "HKCU:\\Software\\ArchitectVideoStudioRuntimeTest\\"
                + uuid.uuid4().hex
            )
            script = root / "registered-runtime-tests.ps1"
            script.write_text(
                functions
                + "\n$script:fullDriveScanCalled = $false\n"
                + "function Get-PSDrive { $script:fullDriveScanCalled = $true; throw 'full-drive scan should not run' }\n"
                + "$registrationPath = " + _ps_quote(registration_path) + "\n"
                + "$registeredApp = " + _ps_quote(str(registered_app)) + "\n"
                + "$installRoot = " + _ps_quote(str(install_root)) + "\n"
                + "$anyRuntimeFound = $false\n"
                + "try {\n"
                + "  New-Item -Path $registrationPath -Force | Out-Null\n"
                + "  Set-ItemProperty -Path $registrationPath -Name InstallLocation -Value $registeredApp\n"
                + "  $found = Find-ExistingRuntime $installRoot '0.33.1' $registrationPath ([ref]$anyRuntimeFound)\n"
                + "  if (-not [string]::Equals([IO.Path]::GetFullPath($found), [IO.Path]::GetFullPath(" + _ps_quote(str(runtime)) + "), [StringComparison]::OrdinalIgnoreCase)) { throw 'registered runtime was not selected' }\n"
                + "  if ($script:fullDriveScanCalled) { throw 'runtime discovery performed an unnecessary drive scan' }\n"
                + "  Write-Output 'PASS'\n"
                + "} finally { if (Test-Path -LiteralPath $registrationPath) { Remove-Item -LiteralPath $registrationPath -Recurse -Force } }\n",
                encoding="utf-8",
            )
            _require_local_script_policy(self, powershell)
            result = subprocess.run(
                [str(powershell), "-NoLogo", "-NoProfile", "-NonInteractive",
                 "-File", str(script)],
                capture_output=True, text=True, timeout=20,
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            self.assertIn("PASS", result.stdout, f"stdout={result.stdout!r}; stderr={result.stderr!r}")

    def test_setup_refuses_second_download_when_only_existing_runtime_is_incompatible(self):
        powershell = (
            Path(os.environ.get("WINDIR", r"C:\Windows"))
            / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        )
        if not powershell.is_file():
            self.skipTest("Windows PowerShell 5.1 is unavailable")

        setup = (ROOT / "installer" / "Setup.ps1").read_text(encoding="utf-8")
        start = setup.index("function Test-RuntimeLayout")
        extractor_start = setup.index("function Find-ExistingExtractor", start)
        ensure_start = setup.index("function Ensure-Runtime", extractor_start)
        ensure_end = setup.index("function Copy-Payload", ensure_start)
        functions = setup[start:extractor_start] + setup[ensure_start:ensure_end]

        with tempfile.TemporaryDirectory(prefix="avs-incompatible-runtime-contract-") as temp:
            root = Path(temp)
            install_root = root / "new-app" / "ArchitectVideoStudio"
            incompatible = root / "new-app" / "ArchitectVideoStudio_Runtime"
            python = incompatible / "python_embeded" / "python.exe"
            main = incompatible / "ComfyUI" / "main.py"
            version = incompatible / "ComfyUI" / "comfyui_version.py"
            marker = incompatible / "runtime_version.json"
            python.parent.mkdir(parents=True)
            main.parent.mkdir(parents=True)
            python.write_bytes(b"existing-runtime-python")
            main.write_text("existing runtime", encoding="utf-8")
            version.write_text('__version__ = "0.36.0"\n', encoding="utf-8")
            marker.write_text('{"comfyui":"0.36.0"}', encoding="utf-8")
            original = {path: path.read_bytes() for path in (python, main, version, marker)}
            registration_path = (
                "HKCU:\\Software\\ArchitectVideoStudioRuntimeTest\\"
                + uuid.uuid4().hex
            )
            cache = install_root / "userdata" / "cache" / "bootstrap"
            script = root / "incompatible-runtime-tests.ps1"
            script.write_text(
                functions
                + "\n$script:downloadCalled = $false\n"
                + "$script:fullDriveScanCalled = $false\n"
                + "function Get-PSDrive { $script:fullDriveScanCalled = $true; throw 'full-drive scan should not run when an existing runtime is already identified' }\n"
                + "function Invoke-ResumableDownload([string]$Url, [string]$Destination) { $script:downloadCalled = $true; throw 'runtime download was attempted' }\n"
                + "$config = [pscustomobject]@{ runtime = [pscustomobject]@{ version = '0.33.1'; asset = 'must-not-download.7z'; url = 'https://invalid.example/runtime.7z'; sha256 = 'unused' } }\n"
                + "try { Ensure-Runtime $config " + _ps_quote(str(install_root)) + " " + _ps_quote(str(cache)) + " " + _ps_quote(registration_path) + "; throw 'incompatible runtime unexpectedly accepted' } catch { if ($_.Exception.Message -notmatch 'will not download a second runtime') { throw } }\n"
                + "if ($script:downloadCalled) { throw 'runtime download was attempted' }\n"
                + "if ($script:fullDriveScanCalled) { throw 'full-drive scan ran despite a known existing runtime' }\n"
                + "if (Test-Path -LiteralPath " + _ps_quote(str(install_root)) + ") { throw 'new install root was created' }\n"
                + "if (Test-Path -LiteralPath " + _ps_quote(str(cache)) + ") { throw 'download cache was created' }\n"
                + "Write-Output 'PASS'\n",
                encoding="utf-8",
            )
            _require_local_script_policy(self, powershell)
            result = subprocess.run(
                [str(powershell), "-NoLogo", "-NoProfile", "-NonInteractive",
                 "-File", str(script)],
                capture_output=True, text=True, timeout=20,
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            self.assertIn("PASS", result.stdout)
            self.assertEqual({path: path.read_bytes() for path in original}, original)


if __name__ == "__main__":
    unittest.main()
