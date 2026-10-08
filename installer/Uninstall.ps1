[CmdletBinding()]
param(
    [string]$InstallRoot,
    [switch]$CleanupOnly,
    [switch]$PlanOnly,
    [switch]$TestFixture,
    [int]$WaitForPid = 0
)

$ErrorActionPreference = "Stop"

function Resolve-InstallRoot([string]$Value) {
    if ([string]::IsNullOrWhiteSpace($Value)) {
        throw "The installation folder could not be identified. No files were changed."
    }
    $root = [IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables($Value.Trim('"')))
    $volumeRoot = [IO.Path]::GetPathRoot($root)
    if ([string]::Equals($root.TrimEnd('\', '/'), $volumeRoot.TrimEnd('\', '/'),
            [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to uninstall from a drive root. No files were changed."
    }
    if (-not (Test-Path -LiteralPath (Join-Path $root 'launcher\launcher.py') -PathType Leaf) -and
        -not (Test-Path -LiteralPath (Join-Path $root 'launcher\ArchitectVideoStudioDesktop.exe') -PathType Leaf)) {
        throw "This folder does not contain a recognized Architect Video Studio installation. No files were changed."
    }
    if ((Get-Item -LiteralPath $root -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw "The installation folder is a link or junction. No files were changed."
    }
    return $root.TrimEnd('\', '/')
}

function Test-PathWithin([string]$Path, [string]$Root) {
    $full = [IO.Path]::GetFullPath($Path).TrimEnd('\', '/')
    $base = [IO.Path]::GetFullPath($Root).TrimEnd('\', '/')
    return [string]::Equals($full, $base, [StringComparison]::OrdinalIgnoreCase) -or
        $full.StartsWith($base + [IO.Path]::DirectorySeparatorChar,
            [StringComparison]::OrdinalIgnoreCase)
}

function Get-PreservedRoots([string]$Root) {
    $preserved = New-Object 'System.Collections.Generic.List[string]'
    foreach ($relative in @('userdata', 'Models', 'models',
            'ArchitectVideoStudio_Runtime\ComfyUI\models')) {
        $candidate = Join-Path $Root $relative
        if (Test-Path -LiteralPath $candidate) {
            $preserved.Add([IO.Path]::GetFullPath($candidate).TrimEnd('\', '/'))
        }
    }

    $modelConfig = Join-Path $Root 'models_env.path'
    if (Test-Path -LiteralPath $modelConfig -PathType Leaf) {
        $raw = (Get-Content -LiteralPath $modelConfig -Raw).Trim().Trim('"')
        foreach ($value in ($raw -split [regex]::Escape([IO.Path]::PathSeparator))) {
            if ([string]::IsNullOrWhiteSpace($value)) { continue }
            $candidate = [IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables($value.Trim().Trim('"')))
            if ((Test-Path -LiteralPath $candidate) -and (Test-PathWithin $candidate $Root)) {
                $preserved.Add($candidate.TrimEnd('\', '/'))
            }
        }
    }

    $runtimeConfig = Join-Path $Root 'native_env.path'
    if (Test-Path -LiteralPath $runtimeConfig -PathType Leaf) {
        $runtime = (Get-Content -LiteralPath $runtimeConfig -Raw).Trim().Trim('"')
        if (-not [string]::IsNullOrWhiteSpace($runtime)) {
            $candidate = Join-Path ([Environment]::ExpandEnvironmentVariables($runtime)) 'ComfyUI\models'
            if ((Test-Path -LiteralPath $candidate) -and (Test-PathWithin $candidate $Root)) {
                $preserved.Add([IO.Path]::GetFullPath($candidate).TrimEnd('\', '/'))
            }
        }
    }
    return @($preserved | Sort-Object -Unique)
}

function Test-PreservedOrAncestor([string]$Path, [string[]]$Preserved) {
    $full = [IO.Path]::GetFullPath($Path).TrimEnd('\', '/')
    foreach ($protected in $Preserved) {
        if ([string]::Equals($full, $protected, [StringComparison]::OrdinalIgnoreCase) -or
            $protected.StartsWith($full + [IO.Path]::DirectorySeparatorChar,
                [StringComparison]::OrdinalIgnoreCase)) {
            return $true
        }
    }
    return $false
}

function Test-ExactPreservedPath([string]$Path, [string[]]$Preserved) {
    $full = [IO.Path]::GetFullPath($Path).TrimEnd('\', '/')
    foreach ($protected in $Preserved) {
        if ([string]::Equals($full, $protected, [StringComparison]::OrdinalIgnoreCase)) { return $true }
    }
    return $false
}

function Get-RemovalPlan([string]$Root, [string[]]$Preserved) {
    $items = New-Object 'System.Collections.Generic.List[string]'
    function Visit([string]$Path) {
        if (Test-PreservedOrAncestor $Path $Preserved) {
            if (Test-ExactPreservedPath $Path $Preserved) { return }
            $item = Get-Item -LiteralPath $Path -Force
            if ($item.PSIsContainer -and -not ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
                foreach ($child in Get-ChildItem -LiteralPath $Path -Force) { Visit $child.FullName }
            }
            return
        }
        $item = Get-Item -LiteralPath $Path -Force
        if ($item.PSIsContainer -and -not ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            foreach ($child in Get-ChildItem -LiteralPath $Path -Force) { Visit $child.FullName }
        }
        $items.Add($Path.Substring($Root.Length).TrimStart('\', '/'))
    }
    foreach ($entry in Get-ChildItem -LiteralPath $Root -Force) { Visit $entry.FullName }
    return @($items)
}

function Remove-ManagedEntry([string]$Path, [string[]]$Preserved) {
    if (Test-PreservedOrAncestor $Path $Preserved) {
        if (Test-ExactPreservedPath $Path $Preserved) { return }
        $item = Get-Item -LiteralPath $Path -Force
        if (-not $item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) { return }
        foreach ($child in Get-ChildItem -LiteralPath $Path -Force) { Remove-ManagedEntry $child.FullName $Preserved }
        return
    }

    $item = Get-Item -LiteralPath $Path -Force
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        if ($item.PSIsContainer) { [IO.Directory]::Delete($Path, $false) }
        else { [IO.File]::Delete($Path) }
        return
    }
    if ($item.PSIsContainer) {
        foreach ($child in Get-ChildItem -LiteralPath $Path -Force) { Remove-ManagedEntry $child.FullName $Preserved }
        if (@(Get-ChildItem -LiteralPath $Path -Force -ErrorAction SilentlyContinue).Count -eq 0) {
            [IO.Directory]::Delete($Path, $false)
        }
    } else {
        [IO.File]::Delete($Path)
    }
}

function Remove-Registration {
    $shortcut = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Architect Video Studio.lnk'
    Remove-Item -LiteralPath $shortcut -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath 'HKCU:\Software\Microsoft\Windows\CurrentVersion\App Paths\ArchitectVideoStudio.exe' `
        -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\ArchitectVideoStudio' `
        -Recurse -Force -ErrorAction SilentlyContinue
}

$root = Resolve-InstallRoot $InstallRoot
$preservedRoots = Get-PreservedRoots $root

if ($PlanOnly) {
    $plan = Get-RemovalPlan $root $preservedRoots
    $preservedLabels = @($preservedRoots | ForEach-Object {
        $_.Substring($root.Length).TrimStart('\', '/') -replace '\\', '/'
    })
    [pscustomobject]@{
        status = 'PLAN_ONLY'
        app_entries_to_remove = $plan.Count
        preserved_roots = $preservedLabels
        user_data_preserved = ($preservedLabels -contains 'userdata')
        absolute_paths_emitted = $false
    } | ConvertTo-Json -Compress
    exit 0
}

if ($CleanupOnly) {
    if ((Test-PathWithin $PSCommandPath $root) -or -not (Test-Path -LiteralPath $PSCommandPath -PathType Leaf)) {
        throw "The cleanup worker is not isolated from the installation folder. No files were changed."
    }
    if ($TestFixture) {
        $tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\', '/')
        if (-not (Test-PathWithin $root $tempRoot) -or
            -not ([IO.Path]::GetFileName($root).StartsWith('avs-uninstall-contract-', [StringComparison]::OrdinalIgnoreCase))) {
            throw "The test cleanup target is outside its dedicated temporary fixture. No files were changed."
        }
    }
    if ($WaitForPid -gt 0) {
        $deadline = [DateTime]::UtcNow.AddSeconds(45)
        while ([DateTime]::UtcNow -lt $deadline) {
            $parent = Get-Process -Id $WaitForPid -ErrorAction SilentlyContinue
            if (-not $parent) { break }
            Start-Sleep -Milliseconds 250
        }
        if (Get-Process -Id $WaitForPid -ErrorAction SilentlyContinue) {
            throw "The uninstaller did not release the application files. No files were changed."
        }
    }
    foreach ($entry in Get-ChildItem -LiteralPath $root -Force) { Remove-ManagedEntry $entry.FullName $preservedRoots }
    if (@(Get-ChildItem -LiteralPath $root -Force -ErrorAction SilentlyContinue).Count -eq 0) {
        [IO.Directory]::Delete($root, $false)
    }
    if (-not $TestFixture) { Remove-Registration }
    if (-not $TestFixture) {
        try { Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue } catch { }
    }
    exit 0
}

if (-not (Test-PathWithin $PSCommandPath $root)) {
    throw "The uninstaller is not running from the selected installation folder. No files were changed."
}

$busy = @()
try {
    $busy = @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
        $_.ProcessId -ne $PID -and $_.CommandLine -and
        $_.CommandLine.IndexOf($root, [StringComparison]::OrdinalIgnoreCase) -ge 0
    })
} catch {
    throw "Could not verify that Architect Video Studio is closed. Close Studio and ComfyUI, then retry. No files were changed."
}
if ($busy.Count -gt 0) {
    Add-Type -AssemblyName System.Windows.Forms
    [Windows.Forms.MessageBox]::Show(
        'Studio or its ComfyUI runtime is still running. Close the application and retry. No files were changed.',
        'Architect Video Studio', 'OK', 'Warning') | Out-Null
    exit 1
}

Add-Type -AssemblyName System.Windows.Forms
$answer = [Windows.Forms.MessageBox]::Show(
    'Remove Architect Video Studio program files? Projects, settings, and detected model directories will be preserved on disk.',
    'Uninstall Architect Video Studio', 'YesNo', 'Warning')
if ($answer -ne [Windows.Forms.DialogResult]::Yes) { exit 0 }

$workerPath = Join-Path $env:TEMP ('ArchitectVideoStudio-Uninstall-' + [guid]::NewGuid().ToString('N') + '.ps1')
Copy-Item -LiteralPath $PSCommandPath -Destination $workerPath
$powershell = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
if (-not (Test-Path -LiteralPath $powershell)) { $powershell = 'powershell.exe' }
$arguments = '-NoProfile -File "{0}" -InstallRoot "{1}" -CleanupOnly -WaitForPid {2}' -f `
    $workerPath, $root, $PID
Start-Process -FilePath $powershell -ArgumentList $arguments -WindowStyle Hidden | Out-Null
[Windows.Forms.MessageBox]::Show(
    'Uninstall started. Your projects, settings, and detected model files are being kept.',
    'Architect Video Studio', 'OK', 'Information') | Out-Null
