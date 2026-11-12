# Behavioural coverage for install.ps1's --uninstall path. Like the other files
# here it parses install.ps1 and evaluates only the function definitions, so no
# installer flow runs and nothing is downloaded or installed on the host.
#   Read-OmhInstallerArgs        : --uninstall / --purge / --dry-run, and every refused combination
#   Get-OmhUninstallArguments    : --purge becomes --all, --dry-run passes through, --language only when set
#   Get-OmhUninstallCandidates   : the places the installer puts the command, never PATH alone
#   the run                      : install.ps1 --uninstall with a stub omh.cmd in a private bin dir
#                                  runs it, leaves its exit code behind, and with no command found
#                                  exits non-zero and creates nothing
# -InjectRegression swaps in an argument reader that treats --purge as a plain
# no-op flag; the "--purge alone is refused" case must catch it.
param([switch]$InjectRegression)

Set-StrictMode -Version 3.0
$ErrorActionPreference = 'Stop'
$script:OmhFailures = @()
$script:OmhLines = @()
$script:OmhUninstall = $false
$script:OmhUninstallPurge = $false
$script:OmhUninstallDryRun = $false

function Write-OmhLine { param([string]$Text = '') $script:OmhLines += $Text }
$OmhOmherBetaOneLiner = '& ([scriptblock]::Create((irm https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.ps1))) omher@beta'
$OmhUninstallOneLiner = '& ([scriptblock]::Create((irm https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.ps1))) --uninstall [--purge] [--dry-run]'

function Stop-OmhInstall {
    param([string[]]$Lines)
    foreach ($line in $Lines) { Write-OmhLine $line }
    throw 'omh installer stopped.'
}

function Assert-Omh {
    param([string]$Name, [object]$Actual, [object]$Expected)
    if ("$Actual" -ne "$Expected") {
        $script:OmhFailures += "$Name : expected '$Expected', got '$Actual'"
    }
}

function Test-Refused {
    param([string[]]$Arguments)
    $script:OmhLines = @()
    $refused = $false
    try { Read-OmhInstallerArgs $Arguments | Out-Null } catch { $refused = $true }
    return $refused
}

try {
    $errors = $null
    $installerPath = (Resolve-Path (Join-Path $PSScriptRoot '..\..\install.ps1')).ProviderPath
    $installerAst = [System.Management.Automation.Language.Parser]::ParseFile($installerPath, [ref]$null, [ref]$errors)
    if ($errors) { throw "install.ps1 does not parse: $($errors[0].Message)" }
    foreach ($functionName in @('Read-OmhInstallerArgs', 'Get-OmhUninstallArguments', 'Get-OmhUninstallCandidates')) {
        $definition = @($installerAst.FindAll({
            param($node)
            $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $functionName
        }, $true))[0]
        if ($null -eq $definition) { throw "install.ps1 does not define $functionName." }
        Invoke-Expression $definition.Extent.Text
    }

    if ($InjectRegression) {
        function Read-OmhInstallerArgs {
            param([object[]]$Arguments = @())
            $beta = $false
            foreach ($argument in @($Arguments)) {
                $text = [string]$argument
                if ($text -eq 'omher@beta') { $beta = $true; continue }
                if ($text -match '^--?uninstall$') { $script:OmhUninstall = $true; continue }
                if ($text -match '^--?purge$') { $script:OmhUninstallPurge = $true; continue }
                if ($text -match '^--?dry-run$') { $script:OmhUninstallDryRun = $true; continue }
                Stop-OmhInstall @("omh installer: unknown argument '$argument'.")
            }
            return $beta
        }
    }

    # -- arguments ---------------------------------------------------------------------------
    Assert-Omh 'no argument is the plain install' (Read-OmhInstallerArgs @()) $false
    Assert-Omh 'no argument leaves uninstall off' $script:OmhUninstall $false
    Assert-Omh 'omher@beta still opts in' (Read-OmhInstallerArgs @('omher@beta')) $true

    Read-OmhInstallerArgs @('--uninstall') | Out-Null
    Assert-Omh '--uninstall sets uninstall' $script:OmhUninstall $true
    Assert-Omh '--uninstall alone is not a purge' $script:OmhUninstallPurge $false
    Assert-Omh '--uninstall alone is not a dry run' $script:OmhUninstallDryRun $false

    Read-OmhInstallerArgs @('--uninstall', '--purge', '--dry-run') | Out-Null
    Assert-Omh 'purge is read' $script:OmhUninstallPurge $true
    Assert-Omh 'dry run is read' $script:OmhUninstallDryRun $true

    Read-OmhInstallerArgs @('-uninstall', '-dry-run') | Out-Null
    Assert-Omh 'a single dash is read the same' $script:OmhUninstall $true
    Assert-Omh 'a single dash dry run' $script:OmhUninstallDryRun $true

    Read-OmhInstallerArgs @() | Out-Null
    Assert-Omh 'a later call starts clean' $script:OmhUninstall $false

    foreach ($case in @(
            @('--purge'),
            @('--dry-run'),
            @('--purge', '--dry-run'),
            @('--uninstall', 'omher@beta'),
            @('omher@beta', '--uninstall'),
            @('--uninstall', '--force'),
            @('--uninstall', '--all'),
            @('--unknown'))) {
        Assert-Omh ("refused: " + ($case -join ' ')) (Test-Refused $case) $true
    }
    Test-Refused @('--unknown') | Out-Null
    Assert-Omh 'the refusal names the argument' ([bool]($script:OmhLines -match "unknown argument '--unknown'")) $true
    Assert-Omh 'the refusal shows the install form' ([bool]($script:OmhLines -match [regex]::Escape($OmhOmherBetaOneLiner))) $true
    Assert-Omh 'the refusal shows the remove form' ([bool]($script:OmhLines -match [regex]::Escape($OmhUninstallOneLiner))) $true

    # -- what omh uninstall is asked ---------------------------------------------------------
    Assert-Omh 'plain' ((Get-OmhUninstallArguments -Purge $false -DryRun $false) -join ' ') 'uninstall'
    Assert-Omh 'purge maps to --all' ((Get-OmhUninstallArguments -Purge $true -DryRun $false) -join ' ') 'uninstall --all'
    Assert-Omh 'dry run passes through' ((Get-OmhUninstallArguments -Purge $false -DryRun $true) -join ' ') 'uninstall --dry-run'
    Assert-Omh 'both' ((Get-OmhUninstallArguments -Purge $true -DryRun $true) -join ' ') 'uninstall --all --dry-run'
    Assert-Omh 'language when set' ((Get-OmhUninstallArguments -Purge $false -DryRun $false -Language 'ko') -join ' ') 'uninstall --language ko'
    Assert-Omh 'never --force' ([bool]((Get-OmhUninstallArguments -Purge $true -DryRun $true -Language 'en') -contains '--force')) $false

    # -- where the command is looked for -------------------------------------------------------
    $candidates = @(Get-OmhUninstallCandidates -BinDir 'C:\b' -ManagedRoot 'C:\m' -VenvDir 'C:\v')
    Assert-Omh 'bin dir shim first' $candidates[0] (Join-Path 'C:\b' 'omh.cmd')
    Assert-Omh 'then the bin dir exe' $candidates[1] (Join-Path 'C:\b' 'omh.exe')
    Assert-Omh 'then the current generation' $candidates[2] (Join-Path 'C:\m' 'current\venv\Scripts\omh.exe')
    Assert-Omh 'then the installer venv' $candidates[3] (Join-Path 'C:\v' 'Scripts\omh.exe')
    Assert-Omh 'nothing set, nothing to look in' (@(Get-OmhUninstallCandidates -BinDir '' -ManagedRoot '' -VenvDir '').Count) 0

    # -- the run, end to end ------------------------------------------------------------------
    # install.ps1 as a script with a private bin dir (OMH_BIN_DIR) holding a stub omh.cmd. USERPROFILE,
    # LOCALAPPDATA and PATH point into the test's own folders, so the real command is never seen.
    $hostExe = (Get-Process -Id $PID).Path
    $work = Join-Path ([System.IO.Path]::GetTempPath()) ('omh-uninstall-' + [guid]::NewGuid().ToString('N'))
    try {
        $profileDir = Join-Path $work 'profile'
        $binDir = Join-Path $work 'bin'
        $logFile = Join-Path $work 'argv.log'
        New-Item -ItemType Directory -Path $profileDir, $binDir -Force | Out-Null
        $stub = "@echo off`r`necho stub omh %*>> `"$logFile`"`r`necho stub omh ran`r`nexit /b %OMH_STUB_STATUS%`r`n"
        [System.IO.File]::WriteAllText((Join-Path $binDir 'omh.cmd'), $stub)

        function Invoke-Installer {
            param([string[]]$InstallerArguments, [string]$Status = '0', [string]$BinDirectory = $binDir)
            $saved = @{}
            foreach ($name in 'USERPROFILE', 'LOCALAPPDATA', 'OMH_BIN_DIR', 'OMH_STUB_STATUS', 'XDG_DATA_HOME', 'OMH_VENV_DIR', 'OMH_LANG') {
                $saved[$name] = [Environment]::GetEnvironmentVariable($name)
            }
            try {
                [Environment]::SetEnvironmentVariable('USERPROFILE', $profileDir)
                [Environment]::SetEnvironmentVariable('LOCALAPPDATA', (Join-Path $work 'local'))
                [Environment]::SetEnvironmentVariable('OMH_BIN_DIR', $BinDirectory)
                [Environment]::SetEnvironmentVariable('OMH_VENV_DIR', (Join-Path $work 'venv'))
                [Environment]::SetEnvironmentVariable('XDG_DATA_HOME', $null)
                [Environment]::SetEnvironmentVariable('OMH_LANG', $null)
                [Environment]::SetEnvironmentVariable('OMH_STUB_STATUS', $Status)
                $output = & $hostExe -NoProfile -ExecutionPolicy Bypass -File $installerPath @InstallerArguments 2>&1 | Out-String
                $code = $LASTEXITCODE
                $global:LASTEXITCODE = 0
                return [pscustomobject]@{ Code = $code; Output = $output }
            } finally {
                foreach ($name in $saved.Keys) { [Environment]::SetEnvironmentVariable($name, $saved[$name]) }
            }
        }

        $run = Invoke-Installer @('--uninstall', '--purge', '--dry-run')
        Assert-Omh 'a found command exits 0' $run.Code 0
        Assert-Omh 'its output is shown' ([bool]($run.Output -match 'stub omh ran')) $true
        $logged = if (Test-Path -LiteralPath $logFile) { [System.IO.File]::ReadAllText($logFile) } else { '' }
        Assert-Omh 'it was run as omh uninstall --all --dry-run' ([bool]($logged -match 'uninstall --all --dry-run')) $true
        Assert-Omh 'no installer header was printed' ([bool]($run.Output -match 'OMH installer')) $false

        $run = Invoke-Installer @('--uninstall') -Status '3'
        Assert-Omh 'the stub exit code is the script exit code' $run.Code 3

        $emptyBin = Join-Path $work 'empty-bin'
        New-Item -ItemType Directory -Path $emptyBin -Force | Out-Null
        $before = @(Get-ChildItem -LiteralPath $work -Recurse -Force | ForEach-Object { $_.FullName }).Count
        $run = Invoke-Installer @('--uninstall') -BinDirectory $emptyBin
        Assert-Omh 'nothing found is non-zero' ($run.Code -ne 0) $true
        Assert-Omh 'nothing found says so' ([bool]($run.Output -match 'no installed omh command was found')) $true
        Assert-Omh 'nothing found points at the manual steps' ([bool]($run.Output -match 'docs/INSTALLATION.md#uninstall')) $true
        Assert-Omh 'nothing found creates nothing' (@(Get-ChildItem -LiteralPath $work -Recurse -Force | ForEach-Object { $_.FullName }).Count) $before

        $run = Invoke-Installer @('--purge')
        Assert-Omh '--purge alone exits non-zero' ($run.Code -ne 0) $true
        Assert-Omh '--purge alone says why' ([bool]($run.Output -match '--purge only works together with --uninstall')) $true
    } finally {
        Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
    }

    if ($InjectRegression) {
        if (-not ($script:OmhFailures -match 'refused: --purge')) {
            throw 'the injected reader that accepts --purge alone was not caught.'
        }
        Write-Host "PASS: injected reader caught ($($script:OmhFailures.Count) failing case(s))."
    } elseif ($script:OmhFailures.Count -gt 0) {
        throw ($script:OmhFailures -join "`n")
    } else {
        Write-Host 'PASS: --uninstall cases'
    }
} catch {
    [Console]::Error.WriteLine("FAIL: $($_.Exception.Message)")
    exit 1
}
