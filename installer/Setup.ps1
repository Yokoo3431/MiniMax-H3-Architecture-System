param(
    [switch]$ValidationMode,
    [switch]$AppOnly,
    [string]$TargetRoot,
    [string]$BootstrapPythonPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Read-BootstrapConfig {
    $archive = Join-Path $PSScriptRoot "payload.zip"
    if ((-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot "payload"))) -and (Test-Path -LiteralPath $archive)) {
        Expand-Archive -LiteralPath $archive -DestinationPath (Join-Path $PSScriptRoot "payload") -Force
    }
    $path = Join-Path $PSScriptRoot "payload\configs\installer_bootstrap.json"
    if (-not (Test-Path -LiteralPath $path)) { throw "Installer bootstrap manifest is missing." }
    return Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
}

function Invoke-ResumableDownload([string]$Url, [string]$Destination) {
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Destination) | Out-Null
    $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
    if ($curl) {
        & $curl.Source --fail --location --retry 3 --continue-at - --output $Destination $Url
        if ($LASTEXITCODE -ne 0) { throw "Download failed: $Url" }
        return
    }
    Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Destination
}

function Assert-Sha256([string]$Path, [string]$Expected) {
    $actual = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $Expected.ToLowerInvariant()) {
        throw "Checksum mismatch for $Path. Expected $Expected, got $actual."
    }
}

function Test-RuntimeLayout([string]$Root) {
    return (Test-Path -LiteralPath (Join-Path $Root "python_embeded\python.exe")) -and
        (Test-Path -LiteralPath (Join-Path $Root "ComfyUI\main.py"))
}

function Test-RuntimeCompatibility([string]$Root, [string]$ExpectedVersion) {
    if (-not (Test-RuntimeLayout $Root)) { return $false }
    $versionFile = Join-Path $Root "runtime_version.json"
    if (Test-Path -LiteralPath $versionFile) {
        try {
            $version = Get-Content -LiteralPath $versionFile -Raw | ConvertFrom-Json
            if ([string]$version.comfyui -ne [string]$ExpectedVersion) { return $false }
        } catch {
            return $false
        }
    }

    # Never adopt a runtime based only on its directory layout. The marker can
    # be absent on manually supplied runtimes, so independently verify the
    # pinned ComfyUI source version before considering it compatible.
    $sourceVersionFile = Join-Path $Root "ComfyUI\comfyui_version.py"
    if (-not (Test-Path -LiteralPath $sourceVersionFile)) { return $false }
    try {
        $source = Get-Content -LiteralPath $sourceVersionFile -Raw
        $match = [regex]::Match($source, '__version__\s*=\s*["'']([^"'']+)["'']')
        return $match.Success -and ([string]$match.Groups[1].Value -eq [string]$ExpectedVersion)
    } catch {
        return $false
    }
}

function Get-RegisteredRuntimePath(
    [string]$RegistrationPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\ArchitectVideoStudio") {
    if (-not (Test-Path -LiteralPath $RegistrationPath)) { return "" }
    try {
        $registration = Get-ItemProperty -Path $RegistrationPath -Name InstallLocation -ErrorAction Stop
        $registeredInstallRoot = [string]$registration.InstallLocation
        if ([string]::IsNullOrWhiteSpace($registeredInstallRoot)) { return "" }
        $runtimeConfig = Join-Path $registeredInstallRoot "native_env.path"
        if (-not (Test-Path -LiteralPath $runtimeConfig -PathType Leaf)) { return "" }
        $runtime = (Get-Content -LiteralPath $runtimeConfig -Raw -ErrorAction Stop).Trim()
        if ([string]::IsNullOrWhiteSpace($runtime) -or
            -not (Test-Path -LiteralPath $runtime -PathType Container)) { return "" }
        return [IO.Path]::GetFullPath($runtime)
    } catch {
        return ""
    }
}

function Resolve-ValidationRuntime($Config,
                                  [string]$RegistrationPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\ArchitectVideoStudio") {
    # Validation mode is deliberately narrower than normal Setup discovery:
    # use only the runtime already recorded by the installed application.
    # It must never scan drives, download, extract, or create another runtime.
    $runtime = Get-RegisteredRuntimePath $RegistrationPath
    if (-not $runtime) {
        throw "Validation requires an already registered ComfyUI runtime. No runtime was installed or downloaded."
    }
    if (-not (Test-RuntimeCompatibility $runtime ([string]$Config.runtime.version))) {
        throw "The registered ComfyUI runtime does not match the package pin. Validation stopped without updating or installing a runtime."
    }
    return $runtime
}

function Assert-ValidationTarget([string]$Path) {
    if ([string]::IsNullOrWhiteSpace($Path)) {
        throw "Validation mode requires an explicit temporary target folder."
    }
    $target = [IO.Path]::GetFullPath($Path)
    $tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd([char]0x5c, [char]0x2f)
    $tempPrefix = $tempRoot + [IO.Path]::DirectorySeparatorChar
    if (-not $target.StartsWith($tempPrefix, [StringComparison]::OrdinalIgnoreCase) -or
        (Split-Path -Leaf $target) -notmatch '^avs-validation-[A-Fa-f0-9-]{8,}$') {
        throw "Validation target must be a uniquely named avs-validation-* folder inside the system temporary directory."
    }
    if (Test-Path -LiteralPath $target) {
        throw "Validation target already exists; Setup will not overwrite it."
    }
    return $target
}

function Invoke-ValidationInstall($Config, [string]$PayloadRoot, [string]$TargetRoot,
                                  [string]$RegistrationPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\ArchitectVideoStudio") {
    $target = Assert-ValidationTarget $TargetRoot
    $runtime = Resolve-ValidationRuntime $Config $RegistrationPath
    if (-not (Test-Path -LiteralPath $PayloadRoot -PathType Container)) {
        throw "Validation payload is missing."
    }
    $payload = [IO.Path]::GetFullPath($PayloadRoot)
    $targetPrefix = $target.TrimEnd([char]0x5c, [char]0x2f) + [IO.Path]::DirectorySeparatorChar
    if ($payload.StartsWith($targetPrefix, [StringComparison]::OrdinalIgnoreCase) -or
        $target.StartsWith($payload.TrimEnd([char]0x5c, [char]0x2f) + [IO.Path]::DirectorySeparatorChar,
                           [StringComparison]::OrdinalIgnoreCase)) {
        throw "Validation payload and target must be separate folders."
    }

    New-Item -ItemType Directory -Path $target | Out-Null
    Copy-Payload $payload $target
    Set-Content -LiteralPath (Join-Path $target "native_env.path") -Value $runtime -Encoding UTF8
    return [pscustomobject]@{
        InstallRoot = $target
        RuntimeRoot = $runtime
        RuntimeVersion = [string]$Config.runtime.version
        Mode = "VALIDATION_PAYLOAD_ONLY"
    }
}

function Find-ExistingRuntime([string]$InstallRoot, [string]$ExpectedVersion,
                              [string]$RegistrationPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\ArchitectVideoStudio",
                              [ref]$AnyRuntimeFound) {
    if ($AnyRuntimeFound) { $AnyRuntimeFound.Value = $false }
    $parent = Split-Path -Parent $InstallRoot
    $registeredRuntime = Get-RegisteredRuntimePath $RegistrationPath
    if ($registeredRuntime -and (Test-RuntimeCompatibility $registeredRuntime $ExpectedVersion)) {
        Write-Host "Using the compatible ComfyUI Runtime configured by the existing Architect Video Studio installation."
        if ($AnyRuntimeFound) { $AnyRuntimeFound.Value = $true }
        return $registeredRuntime
    }
    $candidates = @(
        $registeredRuntime,
        (Join-Path $InstallRoot "ArchitectVideoStudio_Runtime"),
        (Join-Path $InstallRoot "runtime\native"),
        (Join-Path $parent "ArchitectVideoStudio_Runtime"),
        (Join-Path $parent "runtime\native"),
        (Join-Path $parent "ComfyUI")
    )
    $comfyFamily = Join-Path $parent "ComfyUI"
    if (Test-Path -LiteralPath $comfyFamily) {
        $candidates += Get-ChildItem -LiteralPath $comfyFamily -Directory -ErrorAction SilentlyContinue |
            ForEach-Object { $_.FullName }
    }

    # Once an existing ComfyUI layout is present in the registered or bounded
    # locations, do not recursively scan every drive looking for another copy.
    # Reuse a compatible candidate or fail closed; never turn discovery into a
    # long disk walk or an implicit second-runtime installation.
    $knownRuntimeFound = @($candidates | Where-Object {
        $_ -and (Test-RuntimeLayout $_)
    }).Count -gt 0
    if ($AnyRuntimeFound -and $knownRuntimeFound) {
        $AnyRuntimeFound.Value = $true
    }

    # Last-resort cross-drive discovery is only needed when none of the bounded
    # known locations contains a ComfyUI layout.  Existing installations are
    # therefore reused or rejected promptly instead of silently scanning every
    # local drive.
    $directCompatible = @($candidates | Where-Object {
        $_ -and (Test-RuntimeCompatibility $_ $ExpectedVersion)
    })
    if ($directCompatible.Count -eq 0 -and -not $knownRuntimeFound) {
        Write-Host "Scanning local drives for an existing compatible ComfyUI Runtime..."
        $runtimeNames = @("ArchitectVideoStudio_Runtime")
        foreach ($drive in (Get-PSDrive -PSProvider FileSystem -ErrorAction SilentlyContinue)) {
            try {
                $candidates += Get-ChildItem -LiteralPath $drive.Root -Directory -Force -Recurse -Depth 5 -ErrorAction SilentlyContinue |
                    Where-Object { $runtimeNames -contains $_.Name -or (Test-RuntimeLayout $_.FullName) } |
                    ForEach-Object { $_.FullName }
            } catch { }
        }
    }

    $seen = @{}
    $valid = @()
    foreach ($candidate in $candidates) {
        if (-not $candidate -or $seen.ContainsKey($candidate)) { continue }
        $seen[$candidate] = $true
        if ($AnyRuntimeFound -and (Test-RuntimeLayout $candidate)) {
            $AnyRuntimeFound.Value = $true
        }
        if (-not (Test-RuntimeCompatibility $candidate $ExpectedVersion)) { continue }
        $versionFile = Join-Path $candidate "runtime_version.json"
        $versionMatch = $false
        $preadMatch = $false
        if (Test-Path -LiteralPath $versionFile) {
            try {
                $version = Get-Content -LiteralPath $versionFile -Raw | ConvertFrom-Json
                $versionMatch = ([string]$version.comfyui -eq [string]$ExpectedVersion)
                $preadMatch = ([string]$version.pread -eq "pread")
            } catch {
                $versionMatch = $false
            }
        }
        $h3Present = Test-Path -LiteralPath (Join-Path $candidate "ComfyUI\custom_nodes\ComfyUI_RH_MinMaxH3")
        $vhsPresent = Test-Path -LiteralPath (Join-Path $candidate "ComfyUI\custom_nodes\ComfyUI-VideoHelperSuite")
        $valid += [pscustomobject]@{
            Root = $candidate
            Score = ([int]$versionMatch * 4) + ([int]$preadMatch * 2) +
                ([int]$h3Present) + ([int]$vhsPresent)
        }
    }
    return $valid | Sort-Object Score -Descending | Select-Object -First 1 | ForEach-Object { $_.Root }
}

function Find-ExistingExtractor($Config, [string]$InstallRoot, [string]$Cache, [string]$Runtime) {
    $destination = Join-Path $Cache $Config.extractor.filename
    if (Test-Path -LiteralPath $destination) { return $destination }

    $parent = Split-Path -Parent $InstallRoot
    $candidates = @(
        (Join-Path $Runtime $Config.extractor.filename),
        (Join-Path $InstallRoot $Config.extractor.filename),
        (Join-Path $parent "7zr.exe"),
        (Join-Path $parent "ComfyUI\7zr.exe")
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) | Out-Null
            Copy-Item -LiteralPath $candidate -Destination $destination -Force
            Write-Host "Using existing archive extractor: $candidate"
            return $destination
        }
    }
    return $destination
}

function Get-ModelCandidates([string]$InstallRoot, [string]$Runtime,
                              [switch]$AllowFullDriveScan) {
    $parent = Split-Path -Parent $InstallRoot
    $runtimeParent = Split-Path -Parent $Runtime
    $candidates = @(
        (Join-Path $Runtime "ComfyUI\models"),
        (Join-Path $InstallRoot "Models"),
        (Join-Path $InstallRoot "models"),
        (Join-Path $InstallRoot "runtime\native\ComfyUI\models"),
        (Join-Path $runtimeParent "models"),
        (Join-Path $parent "models")
    )
    foreach ($variable in @("H3_MODELS_ROOT", "MINIMAX_H3_MODEL_ROOTS", "MINIMAX_H3_WEIGHTS_ROOTS")) {
        $value = [Environment]::GetEnvironmentVariable($variable)
        if ($value) {
            $candidates += ($value -split [IO.Path]::PathSeparator)
        }
    }

    $comfyFamily = Join-Path $parent "ComfyUI"
    if (Test-Path -LiteralPath $comfyFamily) {
        $candidates += (Join-Path $comfyFamily "models")
        $candidates += Get-ChildItem -LiteralPath $comfyFamily -Directory -ErrorAction SilentlyContinue |
            ForEach-Object { Join-Path $_.FullName "ComfyUI\models" }
    }
    if ($AllowFullDriveScan) {
        Write-Host "Scanning local drives for an existing MiniMax-H3 model root..."
        foreach ($drive in (Get-PSDrive -PSProvider FileSystem -ErrorAction SilentlyContinue)) {
            try {
                $candidates += Get-ChildItem -LiteralPath $drive.Root -Directory -Force -Recurse -Depth 5 -ErrorAction SilentlyContinue |
                    Where-Object {
                        $_.Name -in @("models", "models_root", "MiniMax-H3") -or
                        (Test-Path (Join-Path $_.FullName "diffusion_models")) -or
                        (Test-Path (Join-Path $_.FullName "text_encoders")) -or
                        (Test-Path (Join-Path $_.FullName "vae"))
                    } |
                    ForEach-Object { $_.FullName }
            } catch { }
        }
    }
    return $candidates
}

function Find-ExistingModelsRoot([string]$InstallRoot, [string]$Runtime) {
    $manifestPath = Join-Path $InstallRoot "models\manifest.json"
    if (-not (Test-Path -LiteralPath $manifestPath)) {
        return (Join-Path (Split-Path -Parent $Runtime) "Models")
    }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    $seen = @{}
    $valid = @()
    foreach ($raw in (Get-ModelCandidates $InstallRoot $Runtime)) {
        if (-not $raw) { continue }
        try { $candidate = [IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables([string]$raw)) }
        catch { continue }
        if ($seen.ContainsKey($candidate) -or -not (Test-Path -LiteralPath $candidate)) { continue }
        $seen[$candidate] = $true
        $present = 0
        $expected = 0
        foreach ($property in $manifest.models.PSObject.Properties) {
            $spec = $property.Value
            if (-not $spec.target_subdir -or -not $spec.filename) { continue }
            $expected++
            $file = Join-Path (Join-Path $candidate ([string]$spec.target_subdir)) ([string]$spec.filename)
            if (Test-Path -LiteralPath $file -PathType Leaf) { $present++ }
        }
        $sidecar = Join-Path $candidate "diffusers\MiniMax-H3\FL2VA"
        $sidecarPresent = if (Test-Path -LiteralPath $sidecar) {
            @(Get-ChildItem -LiteralPath $sidecar -File -Recurse -ErrorAction SilentlyContinue).Count
        } else { 0 }
        $valid += [pscustomobject]@{
            Root = $candidate
            Present = $present
            Expected = $expected
            Sidecar = $sidecarPresent
            Score = ($present * 100) + $sidecarPresent
        }
    }
    $best = $valid | Sort-Object Score, Present, Sidecar -Descending | Select-Object -First 1
    if (-not $best -or $best.Present -eq 0) {
        # A full-drive scan is intentionally a fallback, not the normal update
        # path.  Healthy configured/shared model roots must make installation
        # finish promptly and without a silent recursive scan.
        $valid = @()
        foreach ($raw in (Get-ModelCandidates $InstallRoot $Runtime -AllowFullDriveScan)) {
            if (-not $raw) { continue }
            try { $candidate = [IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables([string]$raw)) }
            catch { continue }
            if ($seen.ContainsKey($candidate)) { continue }
            $seen[$candidate] = $true
            if (-not (Test-Path -LiteralPath $candidate)) { continue }
            $present = 0
            $expected = 0
            foreach ($property in $manifest.models.PSObject.Properties) {
                $spec = $property.Value
                if (-not $spec.target_subdir -or -not $spec.filename) { continue }
                $expected++
                $file = Join-Path (Join-Path $candidate ([string]$spec.target_subdir)) ([string]$spec.filename)
                if (Test-Path -LiteralPath $file -PathType Leaf) { $present++ }
            }
            $sidecar = Join-Path $candidate "diffusers\MiniMax-H3\FL2VA"
            $sidecarPresent = if (Test-Path -LiteralPath $sidecar) {
                @(Get-ChildItem -LiteralPath $sidecar -File -Recurse -ErrorAction SilentlyContinue).Count
            } else { 0 }
            $valid += [pscustomobject]@{
                Root = $candidate; Present = $present; Expected = $expected;
                Sidecar = $sidecarPresent; Score = ($present * 100) + $sidecarPresent
            }
        }
        $best = $valid | Sort-Object Score, Present, Sidecar -Descending | Select-Object -First 1
    }
    if ($best -and $best.Present -gt 0) {
        Write-Host "Using existing/shared model root: $($best.Root) ($($best.Present)/$($best.Expected) model files present)"
        return $best.Root
    }
    $fallback = Join-Path (Split-Path -Parent $Runtime) "Models"
    Write-Host "No existing model files were found in known locations; using independent Models root: $fallback"
    return $fallback
}

function Ensure-H3ModelRootBridge([string]$Runtime, [string]$ModelsRoot) {
    # The pinned H3 node has a private MiniMax-H3 root resolver. Keep one
    # physical model library and expose it at the resolver's Runtime-local
    # fallback without copying any model weights.
    $source = Join-Path $ModelsRoot "MiniMax-H3"
    $target = Join-Path $Runtime "ComfyUI\models\MiniMax-H3"
    if (-not (Test-Path -LiteralPath $source -PathType Container)) {
        Write-Host "MiniMax-H3 model root is not present yet: $source"
        return $false
    }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
    if (Test-Path -LiteralPath $target) {
        try {
            $sourceResolved = [IO.Path]::GetFullPath((Resolve-Path -LiteralPath $source).Path).TrimEnd([char]0x5c, [char]0x2f)
            $targetItem = Get-Item -LiteralPath $target -Force
            # Resolve-Path returns the junction's logical path on Windows,
            # not its destination. Inspect the reparse-point Target instead.
            $linkTarget = [string]$targetItem.Target
            $targetResolved = if ($targetItem.LinkType -eq "Junction" -and $linkTarget) {
                [IO.Path]::GetFullPath($linkTarget).TrimEnd([char]0x5c, [char]0x2f)
            } else { "" }
            if ($targetItem.LinkType -eq "Junction" -and
                [string]::Equals($sourceResolved, $targetResolved, [StringComparison]::OrdinalIgnoreCase)) {
                Write-Host "Keeping existing MiniMax-H3 Runtime bridge: $target -> $source"
                return $true
            }
            # A previous installation may leave a junction pointing at an old
            # Models Root. Removing the link itself is safe and does not touch
            # the destination model files; rebuild it against the selected
            # root instead of reporting a false conflict.
            if ($targetItem.LinkType -in @("Junction", "SymbolicLink")) {
                Write-Host "Repairing existing MiniMax-H3 Runtime bridge: $target"
                Remove-Item -LiteralPath $target -Force
            } elseif ($targetItem.PSIsContainer -and
                      @(Get-ChildItem -LiteralPath $target -Force -ErrorAction SilentlyContinue).Count -eq 0) {
                # An empty placeholder directory is not a model library.
                # Convert it to the canonical bridge without deleting data.
                Remove-Item -LiteralPath $target -Force
            } else {
                throw "MiniMax-H3 Runtime bridge conflicts with an existing non-link path: $target. Existing files were preserved."
            }
        } catch { }
        if (Test-Path -LiteralPath $target) {
            throw "MiniMax-H3 Runtime bridge conflicts with an existing path: $target"
        }
    }
    New-Item -ItemType Junction -Path $target -Target $source | Out-Null
    $sourceResolved = [IO.Path]::GetFullPath((Resolve-Path -LiteralPath $source).Path).TrimEnd([char]0x5c, [char]0x2f)
    $targetItem = Get-Item -LiteralPath $target -Force
    $targetResolved = [IO.Path]::GetFullPath([string]$targetItem.Target).TrimEnd([char]0x5c, [char]0x2f)
    if ($targetItem.LinkType -ne "Junction" -or
        -not [string]::Equals($sourceResolved, $targetResolved, [StringComparison]::OrdinalIgnoreCase)) {
        throw "MiniMax-H3 Runtime bridge verification failed: $target"
    }
    Write-Host "Created MiniMax-H3 Runtime bridge: $target -> $source"
    return $true
}

function Reconcile-H3RuntimeSupport([string]$Runtime, [string]$InstallRoot) {
    $script = Join-Path $InstallRoot "scripts\reconcile_h3_runtime_unification.py"
    $python = Join-Path $Runtime "python_embeded\python.exe"
    $h3 = Join-Path $Runtime "ComfyUI\custom_nodes\ComfyUI_RH_MinMaxH3"
    $lock = Join-Path $Runtime "ComfyUI\custom_nodes\support_layer.lock.json"
    if (-not (Test-Path -LiteralPath $script) -or -not (Test-Path -LiteralPath $python) -or
        -not (Test-Path -LiteralPath $h3) -or -not (Test-Path -LiteralPath $lock)) {
        Write-Host "Managed H3 support reconcile deferred until the H3 node is installed."
        return
    }
    Write-Host "Reconciling Managed H3 NVFP4/VAE support layer (CPU/static only)..."
    & $python $script --runtime-root $Runtime --repo-root $InstallRoot | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "Managed H3 support reconciliation failed." }
}

function Install-H3FrontendBridge([string]$Runtime, [string]$InstallRoot) {
    $source = Join-Path $InstallRoot "runtime\native_shim\architect_video_studio_h3_bridge"
    $target = Join-Path $Runtime "ComfyUI\custom_nodes\architect_video_studio_h3_bridge"
    if (-not (Test-Path -LiteralPath $source)) {
        throw "AVS H3 frontend bridge payload is missing."
    }
    New-Item -ItemType Directory -Force -Path $target | Out-Null
    Copy-Payload $source $target
    Write-Host "Installed AVS H3 frontend bridge: $target"
}

function Ensure-Extractor($Config, [string]$Cache, [string]$InstallRoot, [string]$Runtime) {
    $path = Join-Path $Cache $Config.extractor.filename
    if (-not (Test-Path -LiteralPath $path)) {
        $existing = Find-ExistingExtractor $Config $InstallRoot $Cache $Runtime
        if (-not (Test-Path -LiteralPath $existing)) {
            Write-Host "Downloading the small archive extractor..."
            Invoke-ResumableDownload $Config.extractor.url $path
        }
    }
    if (-not (Test-Path -LiteralPath $path)) { throw "7-Zip extractor was not downloaded." }
    return $path
}

function Ensure-Runtime($Config, [string]$InstallRoot, [string]$Cache,
                        [string]$RegistrationPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\ArchitectVideoStudio") {
    $runtime = Join-Path $InstallRoot "ArchitectVideoStudio_Runtime"
    if (Test-RuntimeCompatibility $runtime $Config.runtime.version) { return $runtime }

    if (Test-Path -LiteralPath $runtime) {
        throw "The runtime at the selected install target cannot be proven to match the pinned ComfyUI version. It was preserved; choose a clean install folder or verify the runtime first."
    }

    $anyExistingRuntime = $false
    $existing = Find-ExistingRuntime $InstallRoot $Config.runtime.version $RegistrationPath ([ref]$anyExistingRuntime)
    if ($existing) {
        Write-Host "Using existing compatible ComfyUI Runtime: $existing"
        return $existing
    }

    if ($anyExistingRuntime) {
        throw "An existing ComfyUI Runtime was found, but none matches the pinned version $($Config.runtime.version). Setup will not download a second runtime; the existing runtime was preserved and requires a separately validated in-place update."
    }

    Write-Host "No compatible existing ComfyUI Runtime was found; downloading the pinned runtime..."
    $archive = Join-Path $Cache $Config.runtime.asset
    if (-not (Test-Path -LiteralPath $archive)) {
        Write-Host "Downloading the pinned ComfyUI Windows runtime. This is large and resumable."
        Invoke-ResumableDownload $Config.runtime.url $archive
    }
    Assert-Sha256 $archive $Config.runtime.sha256
    $extractor = Ensure-Extractor $Config $Cache $InstallRoot $runtime
    $stage = Join-Path $InstallRoot "ArchitectVideoStudio_Runtime.installing"
    if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $stage | Out-Null
    & $extractor x $archive ("-o" + $stage) -y | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "Pinned ComfyUI archive extraction failed." }

    $candidate = Get-ChildItem -LiteralPath $stage -Directory -Recurse |
        Where-Object { (Test-Path (Join-Path $_.FullName "python_embeded\python.exe")) -and
                       (Test-Path (Join-Path $_.FullName "ComfyUI\main.py")) } |
        Select-Object -First 1
    if (-not $candidate) { throw "The runtime archive has no embedded Python layout." }
    if (-not (Test-RuntimeCompatibility $candidate.FullName $Config.runtime.version)) {
        Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue
        throw "The pinned runtime archive did not expose the expected ComfyUI source version. Staging files were removed."
    }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $runtime) | Out-Null
    Move-Item -LiteralPath $candidate.FullName -Destination $runtime
    Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue

    $shimSource = Join-Path $InstallRoot "runtime\native_shim\windows_safe_load.py"
    $shimTarget = Join-Path $runtime "ComfyUI\custom_nodes\windows_safe_load\__init__.py"
    if (Test-Path -LiteralPath $shimSource) {
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $shimTarget) | Out-Null
        Copy-Item -LiteralPath $shimSource -Destination $shimTarget -Force
    }
    @{ comfyui = $Config.runtime.version; pread = "pread"; installed_by = "ArchitectVideoStudio-Setup" } |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $runtime "runtime_version.json") -Encoding UTF8
    return $runtime
}

function Copy-Payload([string]$Source, [string]$Destination, [switch]$AppOnly) {
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    Get-ChildItem -LiteralPath $Source -Force | ForEach-Object {
        if ($AppOnly -and $_.Name -in @("Models", "models")) { return }
        if ($AppOnly -and $_.Name -in @("ComfyUI", "ArchitectVideoStudio_Runtime")) {
            throw "The App-only payload contains a ComfyUI runtime directory and was rejected."
        }
        try {
            Copy-Item -LiteralPath $_.FullName -Destination $Destination -Recurse -Force -ErrorAction Stop
        } catch {
            throw "Failed to copy installer payload '$($_.FullName)' to '$Destination'. The destination may be locked by another process. $($_.Exception.Message)"
        }
    }
}

function Test-InstallPathWithin([string]$Path, [string]$Root) {
    $fullPath = [IO.Path]::GetFullPath($Path).TrimEnd([char]0x5c, [char]0x2f)
    $fullRoot = [IO.Path]::GetFullPath($Root).TrimEnd([char]0x5c, [char]0x2f)
    return [string]::Equals($fullPath, $fullRoot, [StringComparison]::OrdinalIgnoreCase) -or
        $fullPath.StartsWith($fullRoot + [IO.Path]::DirectorySeparatorChar,
            [StringComparison]::OrdinalIgnoreCase)
}

function Resolve-AppOnlyPython([string]$RequestedPath) {
    $candidate = $RequestedPath
    if ([string]::IsNullOrWhiteSpace($candidate)) { $candidate = $env:H3_BOOTSTRAP_PYTHON }
    if ([string]::IsNullOrWhiteSpace($candidate)) {
        $command = Get-Command python.exe -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($command) { $candidate = $command.Source }
    }
    if ([string]::IsNullOrWhiteSpace($candidate)) {
        throw "App-only installation requires an existing Python 3.10+ interpreter. No software will be downloaded."
    }
    try { $candidate = [IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables($candidate.Trim().Trim('"'))) }
    catch { throw "The selected Python interpreter path is invalid." }
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf) -or
        $candidate -notmatch '(?i)\.exe$' -or
        $candidate -match '(?i)\\WindowsApps\\') {
        throw "The selected Python interpreter is missing or is a Windows app-execution alias. Select an existing python.exe."
    }
    $versionOutput = @(& $candidate -I -B -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])' 2>&1)
    if ($LASTEXITCODE -ne 0 -or $versionOutput.Count -eq 0) {
        throw "The selected Python interpreter could not be started. No installation changes were made."
    }
    $versionText = ([string]$versionOutput[-1]).Trim()
    $version = $null
    if (-not [Version]::TryParse($versionText, [ref]$version) -or $version -lt [Version]"3.10") {
        throw "App-only installation requires an existing Python 3.10 or later interpreter; no Python will be installed."
    }
    return [pscustomobject]@{ Path = $candidate; Version = $version.ToString() }
}

function Assert-AppOnlyTarget([string]$InstallRoot, [string]$PayloadRoot) {
    if ([string]::IsNullOrWhiteSpace($InstallRoot)) { throw "App-only installation requires an explicit target folder." }
    $target = [IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables($InstallRoot.Trim('"')))
    $volumeRoot = [IO.Path]::GetPathRoot($target)
    if ([string]::Equals($target.TrimEnd([char]0x5c, [char]0x2f),
            $volumeRoot.TrimEnd([char]0x5c, [char]0x2f), [StringComparison]::OrdinalIgnoreCase)) {
        throw "The application cannot be installed to a drive root."
    }
    $payload = [IO.Path]::GetFullPath($PayloadRoot)
    if ((Test-InstallPathWithin $target $payload) -or (Test-InstallPathWithin $payload $target)) {
        throw "The application target and installer payload must be separate folders."
    }
    if (Test-Path -LiteralPath (Join-Path $payload "ArchitectVideoStudio_Runtime")) {
        throw "The App-only payload contains a runtime directory and was rejected."
    }
    if (Test-Path -LiteralPath (Join-Path $payload "ComfyUI")) {
        throw "The App-only payload contains a ComfyUI directory and was rejected."
    }

    # Reject junctions/symlinks in every existing target ancestor. This keeps
    # Copy-Payload from escaping the selected installation location.
    $current = $target
    while ($current) {
        if (Test-Path -LiteralPath $current) {
            $item = Get-Item -LiteralPath $current -Force
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw "The application target contains a link or junction. Choose a regular folder."
            }
        }
        $parent = Split-Path -Parent $current
        if ([string]::IsNullOrWhiteSpace($parent) -or $parent -eq $current) { break }
        $current = $parent
    }

    if (Test-Path -LiteralPath $target -PathType Container) {
        $entries = @(Get-ChildItem -LiteralPath $target -Force)
        $recognized = (Test-Path -LiteralPath (Join-Path $target "launcher\launcher.py") -PathType Leaf) -or
            (Test-Path -LiteralPath (Join-Path $target "launcher\ArchitectVideoStudioDesktop.exe") -PathType Leaf)
        if ($entries.Count -gt 0 -and -not $recognized) {
            throw "The selected folder is not empty and is not a recognized Architect Video Studio installation. Nothing was overwritten."
        }
    }

    $knownRuntimes = @()
    if ($env:H3_NATIVE_ROOT) { $knownRuntimes += $env:H3_NATIVE_ROOT }
    foreach ($variable in @("H3_MODELS_ROOT", "MINIMAX_H3_MODEL_ROOTS", "MINIMAX_H3_WEIGHTS_ROOTS")) {
        $value = [Environment]::GetEnvironmentVariable($variable)
        if ($value) { $knownRuntimes += ($value -split [IO.Path]::PathSeparator) }
    }
    $registered = Get-RegisteredRuntimePath
    if ($registered) { $knownRuntimes += $registered }
    $existingPointer = Join-Path $target "native_env.path"
    if (Test-Path -LiteralPath $existingPointer -PathType Leaf) {
        $value = (Get-Content -LiteralPath $existingPointer -Raw).Trim().Trim('"')
        if ($value) { $knownRuntimes += [Environment]::ExpandEnvironmentVariables($value) }
    }
    foreach ($runtimeRoot in $knownRuntimes) {
        if ([string]::IsNullOrWhiteSpace([string]$runtimeRoot)) { continue }
        try { $runtimeRoot = [IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables([string]$runtimeRoot)) }
        catch { continue }
        if (Test-InstallPathWithin $target $runtimeRoot) {
            throw "The selected App-only target is inside a known ComfyUI runtime. Choose a separate application folder."
        }
    }
    return $target
}

function Assert-AppOnlyRegistrationTarget([string]$InstallRoot) {
    $target = [IO.Path]::GetFullPath($InstallRoot).TrimEnd([char]0x5c, [char]0x2f)
    $uninstallKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\ArchitectVideoStudio"
    if (Test-Path -LiteralPath $uninstallKey) {
        try {
            $registered = [string](Get-ItemProperty -LiteralPath $uninstallKey -Name InstallLocation -ErrorAction Stop).InstallLocation
        } catch {
            throw "The existing Studio registration could not be safely verified. App-only setup stopped without changing it."
        }
        if ([string]::IsNullOrWhiteSpace($registered)) {
            throw "The existing Studio registration has no installation identity."
        }
        $registered = [IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables($registered)).TrimEnd([char]0x5c, [char]0x2f)
        if (-not [string]::Equals($registered, $target, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Another Architect Video Studio installation is registered. App-only setup will not overwrite its registration."
        }
    }

    $expectedExe = [IO.Path]::GetFullPath((Join-Path $target "launcher\ArchitectVideoStudioDesktop.exe"))
    $appPathKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\App Paths\ArchitectVideoStudio.exe"
    if (Test-Path -LiteralPath $appPathKey) {
        try {
            $registeredExe = [string](Get-ItemProperty -LiteralPath $appPathKey -Name '(Default)' -ErrorAction Stop).'(Default)'
        } catch {
            throw "The existing Studio executable registration could not be safely verified. App-only setup stopped without changing it."
        }
        if ([string]::IsNullOrWhiteSpace($registeredExe) -or
            -not [string]::Equals([IO.Path]::GetFullPath($registeredExe), $expectedExe,
                [StringComparison]::OrdinalIgnoreCase)) {
            throw "Another Studio executable is registered. App-only setup will not overwrite it."
        }
    }

    $shortcut = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Architect Video Studio.lnk"
    if (Test-Path -LiteralPath $shortcut -PathType Leaf) {
        try {
            $shell = New-Object -ComObject WScript.Shell
            $registeredTarget = [string]$shell.CreateShortcut($shortcut).TargetPath
        } catch {
            throw "The existing Studio shortcut could not be safely verified. App-only setup stopped without changing it."
        }
        if ([string]::IsNullOrWhiteSpace($registeredTarget) -or
            -not [string]::Equals([IO.Path]::GetFullPath($registeredTarget), $expectedExe,
                [StringComparison]::OrdinalIgnoreCase)) {
            throw "Another Studio shortcut is registered. App-only setup will not overwrite it."
        }
    }
}

function Write-AppOnlyState([string]$InstallRoot) {
    $statePath = Join-Path $InstallRoot "userdata\system\setup_state.json"
    $state = $null
    if (Test-Path -LiteralPath $statePath -PathType Leaf) {
        try { $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json }
        catch { throw "Existing application setup state is invalid; it was preserved and not overwritten." }
    } else {
        $state = [pscustomobject]@{
            schema_version = 1
            setup_completed = $false
            native_root = ""
            models_root = ""
            last_validation = ""
            environment_status = "SETUP_REQUIRED"
            skill_status = "UNKNOWN"
        }
    }
    $state | Add-Member -MemberType NoteProperty -Name install_mode -Value "app_only" -Force
    $binding = if (-not [string]::IsNullOrWhiteSpace([string]$state.native_root)) { "bound" } else { "unbound" }
    $state | Add-Member -MemberType NoteProperty -Name runtime_binding -Value $binding -Force
    $statePathParent = Split-Path -Parent $statePath
    New-Item -ItemType Directory -Force -Path $statePathParent | Out-Null
    $encoding = New-Object System.Text.UTF8Encoding($false)
    [IO.File]::WriteAllText($statePath, ($state | ConvertTo-Json -Depth 8), $encoding)
}

function Invoke-AppOnlyInstall([string]$PayloadRoot, [string]$InstallRoot,
                               [string]$RequestedPythonPath) {
    $target = Assert-AppOnlyTarget $InstallRoot $PayloadRoot
    Assert-AppOnlyRegistrationTarget $target
    $python = Resolve-AppOnlyPython $RequestedPythonPath
    foreach ($relative in @("launcher\launcher.py", "apps\architect_video_studio\mock_api\server.py",
                            "Start_ArchitectVideoStudio.bat")) {
        if (-not (Test-Path -LiteralPath (Join-Path $PayloadRoot $relative) -PathType Leaf)) {
            throw "The App-only payload is incomplete; missing required application files."
        }
    }
    New-Item -ItemType Directory -Path $target -Force | Out-Null
    Stop-ExistingDesktopShell $target
    Stop-ExistingManagedServices $target
    Copy-Payload $PayloadRoot $target -AppOnly
    [IO.File]::WriteAllText((Join-Path $target "bootstrap_python.path"), $python.Path,
        (New-Object System.Text.UTF8Encoding($false)))
    Write-AppOnlyState $target

    $env:H3_PROJECT_ROOT = $target
    $env:H3_STUDIO_DATA = Join-Path $target "userdata\studio"
    $env:H3_BOOTSTRAP_PYTHON = $python.Path
    $env:PYTHONNOUSERSITE = "1"
    Register-WindowsApplication $target
    $desktopShell = Join-Path $target "launcher\ArchitectVideoStudioDesktop.exe"
    if (Test-Path -LiteralPath $desktopShell -PathType Leaf) {
        Start-Process -FilePath $desktopShell -WorkingDirectory $target | Out-Null
    } else {
        $launcherScript = Join-Path $target "launcher\launcher.py"
        Start-Process -FilePath $python.Path -ArgumentList @("`"$launcherScript`"", "start", "--no-browser") `
            -WorkingDirectory $target -WindowStyle Hidden | Out-Null
    }
    Write-Host "App-only install complete. Python $($python.Version) is reused; ComfyUI, models, and runtime support were not provisioned."
    Write-Host "The application is available in setup mode until a compatible ComfyUI runtime is explicitly bound."
}

function Stop-ExistingDesktopShell([string]$InstallRoot) {
    $target = [IO.Path]::GetFullPath((Join-Path $InstallRoot "launcher\ArchitectVideoStudioDesktop.exe"))
    $seen = @{}
    $processes = @()
    try {
        $processes = @(Get-CimInstance Win32_Process -Filter "Name = 'ArchitectVideoStudioDesktop.exe'" -ErrorAction Stop)
    } catch {
        # Fall back to the local process list when CIM is unavailable.
        $processes = @()
    }

    foreach ($record in $processes) {
        $path = $record.ExecutablePath
        if ([string]::IsNullOrWhiteSpace($path)) {
            try { $path = (Get-Process -Id $record.ProcessId -ErrorAction Stop).MainModule.FileName } catch { $path = $null }
        }
        if ([string]::IsNullOrWhiteSpace($path)) { continue }
        try { $path = [IO.Path]::GetFullPath($path) } catch { continue }
        if ($path -ine $target) { continue }
        if ($seen.ContainsKey([int]$record.ProcessId)) { continue }
        $seen[[int]$record.ProcessId] = $true

        Write-Host "An existing Architect Video Studio desktop shell is using the selected installation folder. Closing it before update."
        $process = $null
        try { $process = Get-Process -Id $record.ProcessId -ErrorAction Stop } catch { continue }
        try { $process.CloseMainWindow() | Out-Null } catch { }
        if (-not $process.WaitForExit(5000)) {
            Write-Host "The existing desktop shell did not close in time; stopping only that exact application process."
            try { $process.Kill() } catch { throw "Could not close the existing desktop shell at '$target'. Close it manually and run Setup again." }
            if (-not $process.WaitForExit(5000)) { throw "Could not close the existing desktop shell at '$target'. Close it manually and run Setup again." }
        }
    }
}

function Stop-ExistingManagedServices([string]$InstallRoot) {
    # An update must not leave the old Python launcher/backend serving the old
    # Environment Center after its files have been replaced.  Match only
    # recognizable Architect Video Studio command lines rooted at this exact
    # install directory; unrelated ComfyUI/Python processes are untouched.
    $target = [IO.Path]::GetFullPath($InstallRoot).TrimEnd([char]0x5c, [char]0x2f)
    try {
        $records = @(Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction Stop)
    } catch { $records = @() }
    foreach ($record in $records) {
        $command = [string]$record.CommandLine
        if ([string]::IsNullOrWhiteSpace($command) -or
            $command.IndexOf($target, [StringComparison]::OrdinalIgnoreCase) -lt 0 -or
            $command -notmatch '(launcher\\launcher\.py|run_prototype\.py|run_architect_video_studio\.py)') {
            continue
        }
        try {
            $process = Get-Process -Id $record.ProcessId -ErrorAction Stop
            Write-Host "Stopping the existing Architect Video Studio service process $($record.ProcessId) before update."
            $process.Kill()
            $process.WaitForExit(5000) | Out-Null
        } catch {
            throw "Could not stop the existing Architect Video Studio service process $($record.ProcessId). Close the old application and run Setup again."
        }
    }
}

function Register-WindowsApplication([string]$InstallRoot, [string]$Version = "0.8.0-rc1") {
    $exe = Join-Path $InstallRoot "launcher\ArchitectVideoStudioDesktop.exe"
    if (-not (Test-Path -LiteralPath $exe)) { return }
    $startMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
    New-Item -ItemType Directory -Force -Path $startMenu | Out-Null
    $shortcut = Join-Path $startMenu "Architect Video Studio.lnk"
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut($shortcut)
    $link.TargetPath = $exe
    $link.WorkingDirectory = $InstallRoot
    $link.IconLocation = "$exe,0"
    $link.Description = "Architect Video Studio"
    $link.Save()
    $appPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\App Paths\ArchitectVideoStudio.exe"
    New-Item -Path $appPath -Force | Out-Null
    Set-ItemProperty -Path $appPath -Name '(Default)' -Value $exe
    Set-ItemProperty -Path $appPath -Name 'Path' -Value (Split-Path -Parent $exe)
    $uninstall = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\ArchitectVideoStudio"
    New-Item -Path $uninstall -Force | Out-Null
    Set-ItemProperty -Path $uninstall -Name 'DisplayName' -Value 'Architect Video Studio'
    Set-ItemProperty -Path $uninstall -Name 'DisplayVersion' -Value $Version
    Set-ItemProperty -Path $uninstall -Name 'Publisher' -Value 'Architect Video Studio'
    Set-ItemProperty -Path $uninstall -Name 'InstallLocation' -Value $InstallRoot
    Set-ItemProperty -Path $uninstall -Name 'DisplayIcon' -Value $exe
    $uninstaller = Join-Path $InstallRoot 'installer\Uninstall.ps1'
    $powershell = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
    if (-not (Test-Path -LiteralPath $powershell)) { $powershell = 'powershell.exe' }
    $uninstallCommand = '"{0}" -NoProfile -File "{1}" -InstallRoot "{2}"' -f `
        $powershell, $uninstaller, $InstallRoot
    Set-ItemProperty -Path $uninstall -Name 'UninstallString' -Value $uninstallCommand
    Write-Host "Registered Architect Video Studio in Start Menu and Installed apps."
}

function Select-InstallRoot([string]$DefaultRoot) {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing

    $form = New-Object System.Windows.Forms.Form
    $form.Text = "Architect Video Studio Setup"
    $form.Width = 720
    $form.Height = 175
    $form.StartPosition = "CenterScreen"
    $form.FormBorderStyle = "FixedDialog"
    $form.MaximizeBox = $false
    $form.MinimizeBox = $false

    $label = New-Object System.Windows.Forms.Label
    $label.Text = "Choose the installation folder:"
    $label.AutoSize = $true
    $label.Location = New-Object System.Drawing.Point(18, 18)
    $form.Controls.Add($label)

    $box = New-Object System.Windows.Forms.TextBox
    $box.Text = $DefaultRoot
    $box.Location = New-Object System.Drawing.Point(18, 48)
    $box.Width = 560
    $form.Controls.Add($box)

    $browse = New-Object System.Windows.Forms.Button
    $browse.Text = "Browse..."
    $browse.Location = New-Object System.Drawing.Point(590, 46)
    $browse.Width = 90
    $browse.Add_Click({
        $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
        $dialog.Description = "Select the Architect Video Studio installation folder"
        $dialog.ShowNewFolderButton = $true
        $parent = Split-Path -Parent $box.Text
        if ($parent -and (Test-Path -LiteralPath $parent)) {
            $dialog.SelectedPath = $parent
        }
        if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
            $box.Text = $dialog.SelectedPath
        }
        $dialog.Dispose()
    })
    $form.Controls.Add($browse)

    $ok = New-Object System.Windows.Forms.Button
    $ok.Text = "Install"
    $ok.DialogResult = [System.Windows.Forms.DialogResult]::OK
    $ok.Location = New-Object System.Drawing.Point(500, 92)
    $ok.Width = 85
    $form.Controls.Add($ok)

    $cancel = New-Object System.Windows.Forms.Button
    $cancel.Text = "Cancel"
    $cancel.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
    $cancel.Location = New-Object System.Drawing.Point(595, 92)
    $cancel.Width = 85
    $form.Controls.Add($cancel)
    $form.AcceptButton = $ok
    $form.CancelButton = $cancel

    $result = $form.ShowDialog()
    $selected = $box.Text.Trim()
    $form.Dispose()
    if ($result -ne [System.Windows.Forms.DialogResult]::OK) { return "" }
    return $selected
}

$config = Read-BootstrapConfig
$payload = Join-Path $PSScriptRoot "payload"
if (-not (Test-Path -LiteralPath $payload)) { throw "Installer payload is missing." }
if ($ValidationMode) {
    $validation = Invoke-ValidationInstall $config $payload $TargetRoot
    Write-Host "Validation payload staged using the existing registered ComfyUI runtime."
    Write-Host "No ComfyUI files, models, runtime support, Windows registration, or running services were changed."
    return
}

if ($AppOnly) {
    $requested = $TargetRoot
    if (-not $requested) { $requested = $env:ARCHITECT_VIDEO_STUDIO_INSTALL_ROOT }
    if (-not $requested) {
        $defaultRoot = [Environment]::ExpandEnvironmentVariables($config.policy.default_install_root)
        try { $requested = Select-InstallRoot $defaultRoot }
        catch { $requested = Read-Host "Install Architect Video Studio to [$defaultRoot] (press Enter to accept)" }
        if (-not $requested) { $requested = $defaultRoot }
    }
    Invoke-AppOnlyInstall $payload ([Environment]::ExpandEnvironmentVariables($requested.Trim('"'))) $BootstrapPythonPath
    return
}

$defaultRoot = [Environment]::ExpandEnvironmentVariables($config.policy.default_install_root)
$requested = $TargetRoot
if (-not $requested) { $requested = $env:ARCHITECT_VIDEO_STUDIO_INSTALL_ROOT }
if (-not $requested) {
    try {
        $requested = Select-InstallRoot $defaultRoot
    } catch {
        $requested = Read-Host "Install Architect Video Studio to [$defaultRoot] (press Enter to accept)"
    }
}
if ([string]::IsNullOrWhiteSpace($requested)) { throw "Installation canceled." }
$installRoot = if ([string]::IsNullOrWhiteSpace($requested)) { $defaultRoot } else { [Environment]::ExpandEnvironmentVariables($requested.Trim('"')) }
$installRoot = [IO.Path]::GetFullPath($installRoot)
$cache = Join-Path $installRoot "userdata\cache\bootstrap"

Write-Host "Installing Architect Video Studio to $installRoot"
Stop-ExistingDesktopShell $installRoot
Stop-ExistingManagedServices $installRoot
Copy-Payload $payload $installRoot
$runtime = Ensure-Runtime $config $installRoot $cache
Install-H3FrontendBridge $runtime $installRoot
Set-Content -LiteralPath (Join-Path $installRoot "native_env.path") -Value $runtime -Encoding UTF8
$modelsRoot = Find-ExistingModelsRoot $installRoot $runtime
Set-Content -LiteralPath (Join-Path $installRoot "models_env.path") -Value $modelsRoot -Encoding UTF8
Ensure-H3ModelRootBridge $runtime $modelsRoot | Out-Null
Reconcile-H3RuntimeSupport $runtime $installRoot
$env:H3_PROJECT_ROOT = $installRoot
$env:H3_NATIVE_ROOT = $runtime
$env:H3_MODELS_ROOT = $modelsRoot
$env:H3_WINDOWS_SAFE_LOAD = "pread"
$start = Join-Path $installRoot "Start_ArchitectVideoStudio.bat"
if (-not (Test-Path -LiteralPath $start)) { throw "Installed application entry point is missing." }
$launcherPython = Join-Path $runtime "python_embeded\python.exe"
$launcherScript = Join-Path $installRoot "launcher\launcher.py"
$desktopShell = Join-Path $installRoot "launcher\ArchitectVideoStudioDesktop.exe"
Register-WindowsApplication $installRoot
if (Test-Path -LiteralPath $desktopShell) {
    Write-Host "Runtime installed. Starting the desktop control center without a console window."
    Start-Process -FilePath $desktopShell -WorkingDirectory $installRoot | Out-Null
} elseif ((Test-Path -LiteralPath $launcherPython) -and (Test-Path -LiteralPath $launcherScript)) {
    Write-Host "Runtime installed. Starting Environment Center without a console window."
    Start-Process -FilePath $launcherPython -ArgumentList @(
        "`"$launcherScript`"", "start"
    ) -WorkingDirectory $installRoot -WindowStyle Hidden | Out-Null
} else {
    # Compatibility fallback for a manually supplied runtime that does not
    # expose the managed launcher layout yet.
    Write-Host "Managed launcher was not found; starting the compatibility entry point."
    Start-Process -FilePath $start -WorkingDirectory $installRoot -WindowStyle Hidden | Out-Null
}
Write-Host "Setup complete. Continue in Environment Center to install H3 components and models."
