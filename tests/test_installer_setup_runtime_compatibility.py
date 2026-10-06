"""Windows Setup runtime-adoption contract tests using synthetic folders only."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


class TestSetupRuntimeCompatibility(unittest.TestCase):
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
                    "function Find-ExistingRuntime([string]$InstallRoot, [string]$ExpectedVersion) { $script:findExistingCalled = $true; return $null }\n"
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
            result = subprocess.run(
                [str(powershell), "-NoLogo", "-NoProfile", "-NonInteractive",
                 "-ExecutionPolicy", "Bypass", "-File", str(script)],
                capture_output=True, text=True, timeout=20,
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            self.assertIn("PASS", result.stdout)

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
            result = subprocess.run(
                [str(powershell), "-NoLogo", "-NoProfile", "-NonInteractive",
                 "-ExecutionPolicy", "Bypass", "-File", str(script)],
                capture_output=True, text=True, timeout=20,
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            self.assertIn("PASS", result.stdout)
            self.assertEqual({path: path.read_bytes() for path in original}, original)


if __name__ == "__main__":
    unittest.main()
