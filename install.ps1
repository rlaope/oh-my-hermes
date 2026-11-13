<#
    Native Windows installer for oh-my-hermes.

    This is the PowerShell counterpart of install.sh, not a rewrite of it. It
    reads the same OMH_* environment contract, performs the same ordered steps,
    resolves the package source the same way, and hands `omh setup` the same
    argument list, so the two installers stay one documented interface instead
    of two dialects.

    Requires Windows PowerShell 5.1 (shipped with Windows 10/11) or newer.

    Where it deliberately differs from install.sh, and why:

      * A virtual environment exposes Scripts\python.exe, not bin/python.
      * The command is exposed with an omh.cmd shim. A symlink needs Developer
        Mode or elevation on Windows, which an installer must not require.
      * The default venv/bin locations live under %LOCALAPPDATA%, the Windows
        equivalent of the XDG data directory install.sh defaults to.
      * OMH_ADD_TO_PATH defaults to 1. On POSIX, ~/.local/bin is a convention
        most shells already carry on PATH, so install.sh only prints a hint.
        Windows has no such convention, so a hint-only installer would leave
        every user with a command they cannot run. The change is user-scope,
        additive, announced, and reversible; set OMH_ADD_TO_PATH=0 for
        install.sh's hint-only behavior.
      * OMH_PYTHON is unset by default rather than defaulting to python3, and
        the chosen interpreter is version-probed. `python`/`python3` on Windows
        routinely resolve to the Microsoft Store App Execution Alias stub,
        which is on PATH, runs, installs nothing, and exits non-zero.
      * Installer step labels are English on Windows. OMH_LANG is still
        validated and still forwarded to `omh setup` as --language, so the
        localized surface that carries real content stays localized; this file
        is kept pure ASCII because Windows PowerShell 5.1 decodes a BOM-less
        script as ANSI and would mangle the localized labels.

    Deliberately NOT honored: $env:HOME. Python's ntpath.expanduser resolves ~
    from %USERPROFILE% and ignores HOME on native Windows, so honoring HOME here
    would place the venv somewhere `omh update` and `omh remove` cannot find it.

    Usage:
      irm https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.ps1 | iex

    The omher desktop app (beta), plus Hermes Agent when it is missing:
      & ([scriptblock]::Create((irm https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.ps1))) omher@beta
    `irm | iex` cannot pass an argument, so that form runs the downloaded text
    as a script block with one. Without the argument nothing below changes.

    Remove OMH (install.sh --uninstall's counterpart):
      & ([scriptblock]::Create((irm https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.ps1))) --uninstall [--purge] [--dry-run]
    It finds the installed omh command (PATH first, then the places this
    installer puts it) and runs `omh uninstall`, which owns every removal rule;
    --purge becomes --all. It never downloads or installs anything. A leading
    single dash (-uninstall) is read the same as --uninstall, because that is
    the spelling PowerShell users reach for.
#>

# Pinned rather than `Latest`: this file is fetched from main by URL and run on
# whatever PowerShell the user has, so binding strictness to "newest the host
# knows" would let a future release break an installer nobody edited.
Set-StrictMode -Version 3.0
$ErrorActionPreference = 'Stop'
$global:LASTEXITCODE = 0

if ($PSVersionTable.PSVersion.Major -lt 5) {
    Write-Host 'omh installer: Windows PowerShell 5.1 or newer is required.'
    exit 1
}

# ---------------------------------------------------------------------------
# Environment contract
# ---------------------------------------------------------------------------

function Get-OmhEnv {
    <#  Mirrors sh's ${VAR:-default}: unset and empty both fall back.  #>
    param([string]$Name, [string]$Default = '')
    $value = [Environment]::GetEnvironmentVariable($Name)
    if ([string]::IsNullOrEmpty($value)) { return $Default }
    return $value
}

function Test-OmhEnvSet {
    <#  Mirrors sh's ${VAR+x}: assigned at all, even to the empty string.

        Not IsNullOrEmpty. `OMH_PIP_ARGS=` set to empty is how an operator turns
        OFF the implicit --user in python mode, and `OMH_VENV_DIR=` set to empty
        is how they ask for the explicit "set it and retry" error rather than a
        silent default. Folding empty into unset would take both away.
    #>
    param([string]$Name)
    return $null -ne [Environment]::GetEnvironmentVariable($Name)
}

$OmhRepoArchiveRoot = Get-OmhEnv 'OMH_REPO_ARCHIVE_ROOT' 'https://github.com/rlaope/oh-my-hermes/archive/refs'
$OmhRepoAssetRoot   = Get-OmhEnv 'OMH_REPO_ASSET_ROOT' 'https://github.com/rlaope/oh-my-hermes/releases/download'
$OmhRepoLatestUrl   = Get-OmhEnv 'OMH_REPO_LATEST_URL' 'https://github.com/rlaope/oh-my-hermes/releases/latest'
# Stable installs the ~2.7 MB release wheel; preview installs the ~44 MB branch
# archive, which GitHub generates per request rather than serving from a CDN.
$OmhChannel         = Get-OmhEnv 'OMH_CHANNEL' 'stable'
# What `uv python install` is asked for when it is the last resort, and the
# same floor install.sh uses. Kept beside the other inputs so the two
# installers' constants are read in the same place in both files.
$OmhUvPythonVersion = '3.12'
$script:OmhProvisionTried = $false
$script:OmhRejectedPythons = @()
$OmhVersion         = Get-OmhEnv 'OMH_VERSION'
$OmhPackageUrl      = Get-OmhEnv 'OMH_PACKAGE_URL'
$OmhSourceRef       = Get-OmhEnv 'OMH_SOURCE_REF'
$OmhPipArgsWasSet   = Test-OmhEnvSet 'OMH_PIP_ARGS'
$OmhPipArgs         = Get-OmhEnv 'OMH_PIP_ARGS'
$OmhInstallMode     = Get-OmhEnv 'OMH_INSTALL_MODE' 'venv'
$OmhLinkCommand     = Get-OmhEnv 'OMH_LINK_COMMAND' '1'
$OmhForceLink       = Get-OmhEnv 'OMH_FORCE_LINK' '0'
$OmhAddToPath       = Get-OmhEnv 'OMH_ADD_TO_PATH' '1'
$OmhRunSetup        = Get-OmhEnv 'OMH_RUN_SETUP' '0'
$OmhAutoApply       = Get-OmhEnv 'OMH_AUTO_APPLY' '1'
$OmhRunDoctor       = Get-OmhEnv 'OMH_RUN_DOCTOR' '1'
$OmhWithPlugin      = Get-OmhEnv 'OMH_WITH_PLUGIN' '0'
$OmhWithMcp         = Get-OmhEnv 'OMH_WITH_MCP' '0'
$OmhProfilePacks    = Get-OmhEnv 'OMH_PROFILE_PACKS'
$OmhSetupProfiles   = Get-OmhEnv 'OMH_SETUP_PROFILES'
$OmhDefaultExecutor = Get-OmhEnv 'OMH_DEFAULT_EXECUTOR'
$OmhScope           = Get-OmhEnv 'OMH_SCOPE'
$OmhSetupArgs       = Get-OmhEnv 'OMH_SETUP_ARGS'
# omher@beta only (see the usage note above): OMH_WITH_HERMES=0 skips
# installing Hermes, OMH_WITH_DESKTOP=0 skips the app, OMH_APP_DIR picks the
# app's install folder.
$OmhWithHermes      = Get-OmhEnv 'OMH_WITH_HERMES' '1'
$OmhWithDesktop     = Get-OmhEnv 'OMH_WITH_DESKTOP' '1'
$OmhAppDir          = Get-OmhEnv 'OMH_APP_DIR'
# Taken here, at script scope: inside a function $args is that function's own.
$OmhScriptArgs      = @($args)
$OmhHermesInstallUrl  = 'https://hermes-agent.nousresearch.com/install.ps1'
$OmhOmherReleasesUrl  = 'https://api.github.com/repos/rlaope/oh-my-hermes/releases?per_page=10'
$OmhOmherReleasePages = 5
$OmhOmherSiteUrl      = 'https://omher.app/'
$OmhOmherBetaOneLiner = '& ([scriptblock]::Create((irm https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.ps1))) omher@beta'
$OmhUninstallOneLiner = '& ([scriptblock]::Create((irm https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.ps1))) --uninstall [--purge] [--dry-run]'
$script:OmhUninstall       = $false
$script:OmhUninstallPurge  = $false
$script:OmhUninstallDryRun = $false
$script:OmhOmherBeta     = $false
$script:OmhHadOmh        = $false
$script:OmhHadHermes     = $false
$script:OmhInstallHermes = $false
$script:OmhOmherAppPath  = ''

# %USERPROFILE% is the anchor Python itself uses; see the HOME note in the header.
$OmhHomeDir      = Get-OmhEnv 'USERPROFILE'
$OmhLocalAppData = Get-OmhEnv 'LOCALAPPDATA'
$OmhXdgDataHome  = Get-OmhEnv 'XDG_DATA_HOME'

if (Test-OmhEnvSet 'OMH_VENV_DIR') {
    $OmhVenvDir = Get-OmhEnv 'OMH_VENV_DIR'
} elseif ($OmhXdgDataHome) {
    $OmhVenvDir = Join-Path $OmhXdgDataHome 'omh\venv'
} elseif ($OmhLocalAppData) {
    $OmhVenvDir = Join-Path $OmhLocalAppData 'omh\venv'
} elseif ($OmhHomeDir) {
    $OmhVenvDir = Join-Path $OmhHomeDir '.local\share\omh\venv'
} else {
    $OmhVenvDir = ''
}

if (Test-OmhEnvSet 'OMH_BIN_DIR') {
    $OmhBinDir = Get-OmhEnv 'OMH_BIN_DIR'
} elseif ($OmhLocalAppData) {
    $OmhBinDir = Join-Path $OmhLocalAppData 'omh\bin'
} elseif ($OmhHomeDir) {
    $OmhBinDir = Join-Path $OmhHomeDir '.local\bin'
} else {
    $OmhBinDir = ''
}

$OmhLangRaw = Get-OmhEnv 'OMH_LANG'
if (-not $OmhLangRaw) { $OmhLangRaw = Get-OmhEnv 'OMH_LANGUAGE' }
$OmhLangWasSet = [bool]$OmhLangRaw

# Explicitly script-scoped, because the functions below write them back with
# $script: and the two sides have to name the same scope even when this file is
# dot-sourced or wrapped by a caller.
$script:OmhLang          = 'en'
$script:OmhRuntimePython = ''
$script:OmhCommandHint   = ''
$script:OmhCommandPath   = ''
$script:OmhPathNote      = ''
$script:OmhExitCode      = 1

$OmhInstallStepCount = if ($OmhInstallMode -eq 'python') { 1 } else { 2 }
$OmhExposeStep = $OmhInstallStepCount + 1
$OmhSetupStep  = $OmhExposeStep + 1
$OmhDoctorStep = $OmhSetupStep + 1
# Computed before OMH_RUN_DOCTOR is consulted, exactly as install.sh does: with
# OMH_RUN_SETUP=1 and OMH_RUN_DOCTOR=0 the labels still read /5.
$OmhTotalSteps = if ($OmhRunSetup -eq '1') { $OmhDoctorStep } else { $OmhExposeStep }

# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

# Windows PowerShell 5.1 does not enable ENABLE_VIRTUAL_TERMINAL_PROCESSING on
# the legacy console, so raw ANSI would print as literal escape garbage there.
# Colorize only where VT is known good: PowerShell 7+, or Windows Terminal.
$OmhVtCapable = ($PSVersionTable.PSVersion.Major -ge 6) -or [bool](Get-OmhEnv 'WT_SESSION')
$OmhUseColor = $OmhVtCapable -and (-not (Get-OmhEnv 'NO_COLOR')) -and (-not [Console]::IsOutputRedirected)
$OmhEsc = [char]0x1B

function Write-OmhLine {
    # Write-Host rather than [Console]::Out: the ISE and the VS Code integrated
    # console are not attached to [Console], where this installer would run to
    # completion showing nothing at all -- including its own failure output.
    # Write-Host still keeps these strings out of the success pipeline.
    param([string]$Text = '')
    Write-Host $Text
}

function Get-OmhColor {
    param([string]$Code, [string]$Text)
    if ($OmhUseColor) { return "$OmhEsc[${Code}m$Text$OmhEsc[0m" }
    return $Text
}

function Write-OmhHeader {
    param([string]$Title, [string]$Subtitle = '')
    Write-OmhLine (Get-OmhColor '1;36' $Title)
    if ($Subtitle) { Write-OmhLine $Subtitle }
    Write-OmhLine
}

function Write-OmhStep {
    param([string]$Prefix, [string]$Label)
    Write-OmhLine ((Get-OmhColor '1;36' $Prefix) + ' ' + $Label)
}

function Write-OmhOk   { param([string]$Text) Write-OmhLine ('      ' + (Get-OmhColor '1;32' '[ok]') + ' ' + $Text) }
function Write-OmhNote { param([string]$Text) Write-OmhLine ('      ' + (Get-OmhColor '1;33' '[note]') + ' ' + $Text) }
function Write-OmhFail { param([string]$Text) Write-OmhLine ('      ' + (Get-OmhColor '1;31' '[failed]') + ' ' + $Text) }

function Get-OmhStepLabel {
    param([int]$Index)
    return "[$Index/$OmhTotalSteps]"
}

function Stop-OmhInstall {
    <#  Throw rather than exit.

        Under the documented `irm ... | iex` invocation there is no script scope
        to unwind, so `exit` would terminate the user's shell -- taking the
        diagnostic printed one line earlier with it. The top-level handler
        turns this back into a process exit code when this file is run as a
        script, which is what CI does.
    #>
    param([string[]]$Lines)
    foreach ($line in $Lines) { Write-OmhLine $line }
    throw 'omh installer stopped.'
}

# ---------------------------------------------------------------------------
# Language
# ---------------------------------------------------------------------------

function Get-OmhNormalizedLang {
    <#  Same accepted spellings and same rejection as install.sh.  #>
    param([string]$Raw)
    if ([string]::IsNullOrEmpty($Raw)) { return 'en' }
    switch -Regex ($Raw.ToLowerInvariant()) {
        '^(en|eng|english)$'        { return 'en' }
        '^(ko|kr|kor|korean)$'      { return 'ko' }
        '^(ja|jp|jpn|japanese)$'    { return 'ja' }
        '^(zh|cn|zho|chi|chinese)$' { return 'zh' }
        default {
            Stop-OmhInstall @("omh installer: unsupported OMH_LANG $Raw (expected en, ko, ja, or zh).")
        }
    }
}

# English-only by design; see the OMH_LANG note in the file header.
$OmhMessages = @{
    installer_title      = 'OMH installer'
    installer_subtitle   = 'Install oh-my-hermes without touching system Python packages.'
    channel              = 'Channel'
    mode                 = 'Mode'
    step_create_venv     = 'Create isolated Python environment at'
    step_install_package = 'Install OMH package'
    step_install_python  = 'Install OMH package into selected Python'
    step_expose_command  = 'Expose the omh command'
    step_setup           = 'Set up managed Hermes skills (explicit opt-in)'
    step_doctor          = 'Verify installation'
    done                 = 'done'
    installed            = 'oh-my-hermes is installed.'
    next_path            = "Next: run 'omh setup' to connect OMH to Hermes, then 'omh doctor' to verify."
    next_command_path    = "Next: run '{0} setup' to connect OMH to Hermes, then '{0} doctor' to verify, or add its directory to PATH."
    uninstall_not_found  = 'omh installer: no installed omh command was found, so nothing was removed. Looked in: {0}'
    uninstall_left_over  = 'The OMH home and the Hermes registration may still be there. Manual steps: docs/INSTALLATION.md#uninstall (https://github.com/rlaope/oh-my-hermes/blob/main/docs/INSTALLATION.md#uninstall)'
}

function Get-OmhMessage {
    param([string]$Key, [string]$Arg = '')
    if (-not $OmhMessages.ContainsKey($Key)) { return $Key }
    $text = $OmhMessages[$Key]
    if ($Arg) { return ($text -f $Arg) }
    return $text
}

# ---------------------------------------------------------------------------
# Process helpers
# ---------------------------------------------------------------------------

function Invoke-OmhCapture {
    <#  Run a native command, capture merged stdout+stderr, return exit code.  #>
    param([string]$FilePath, [string[]]$Arguments = @())
    $output = ''
    $code = 0
    # PowerShell 7.3+ turns native stderr into a terminating error under
    # $ErrorActionPreference='Stop' when merged with 2>&1. The assignment below
    # is function-local and discarded on return; it is here to relax the merge,
    # not to protect the caller's value, which never changes.
    $ErrorActionPreference = 'Continue'
    try {
        $output = & $FilePath @Arguments 2>&1 | Out-String
        $code = $LASTEXITCODE
    } catch {
        # A missing executable throws rather than exiting non-zero, and the
        # caller's job is to report a failed step, not to leak a stack trace.
        $code = 1
        $output = $_.Exception.Message
    }
    if ($null -eq $output) { $output = '' }
    if ($null -eq $code) { $code = 0 }
    return [pscustomobject]@{ ExitCode = $code; Output = [string]$output }
}

function Invoke-OmhStep {
    <#  install.sh run_step: capture output, print [ok] or [failed] plus body.  #>
    param([string]$Prefix, [string]$Label, [string]$FilePath, [string[]]$Arguments = @())
    Write-OmhStep $Prefix $Label
    $result = Invoke-OmhCapture -FilePath $FilePath -Arguments $Arguments
    if ($result.ExitCode -eq 0) {
        Write-OmhOk (Get-OmhMessage 'done')
        return
    }
    Write-OmhFail $Label
    if ($result.Output) {
        foreach ($line in ($result.Output -split "`r?`n")) {
            if ($line) { Write-OmhLine ('      ' + $line) }
        }
    }
    throw 'omh installer stopped.'
}

function Invoke-OmhCli {
    <#  install.sh run_omh: always the interpreter, never the exposed shim.  #>
    param([string[]]$Arguments)
    $ErrorActionPreference = 'Continue'
    # Python mode installs into the user site; -I would hide that installation.
    & $OmhRuntimePython -P -E -m omh.cli @Arguments
    $code = $LASTEXITCODE
    if ($code -ne 0) {
        # Propagate omh's own status, the way install.sh's `set -e` does.
        $script:OmhExitCode = $code
        throw "omh exited with status $code."
    }
}

function Split-OmhArgString {
    <#  install.sh leans on shell word splitting for the operator escape hatches.

        The leading commas matter: a bare `return @()` writes an EMPTY
        COLLECTION to the pipeline, which emits nothing, so the caller receives
        $null. `@(...) + $null` then appends a null element, which [string[]]
        turns into '' and PowerShell 7 passes to pip as a literal empty
        argument -- breaking the default install. The comma operator returns the
        array itself instead of enumerating it.
    #>
    param([string]$Value)
    if (-not $Value) { return ,@() }
    return ,@($Value -split '\s+' | Where-Object { $_ })
}

# ---------------------------------------------------------------------------
# Interpreter resolution
# ---------------------------------------------------------------------------

function Resolve-OmhPython {
    <#
        Return a usable Python 3.11+ command, or stop with guidance.

        install.sh probes for the same floor and for the same reason -- a
        candidate that is on PATH is not an interpreter the wheel installs
        into -- but the shape that forces it here is local: on Windows,
        `python` and `python3` routinely resolve to the Microsoft Store App
        Execution Alias stub, which is on PATH, runs, installs nothing, and
        exits non-zero. Without this probe the failure surfaces several steps
        later as an unreadable pip error.
    #>
    $explicit = Get-OmhEnv 'OMH_PYTHON'
    if ($explicit) { $candidates = @($explicit) } else { $candidates = @('py', 'python', 'python3') }
    # omher@beta only: Hermes' own interpreter, last. On a machine that had no
    # Python 3.11+ until Hermes' installer brought one, it is the only candidate.
    if (-not $explicit -and $script:OmhOmherBeta) {
        $hermesPython = Get-OmhHermesPython
        if ($hermesPython) { $candidates += $hermesPython }
    }

    $script:OmhRejectedPythons = @()
    $found = Select-OmhPython $candidates
    if ($found) { return $found }

    # Same last resort install.sh has, honoring the same OMH_PROVISION_PYTHON.
    # uv's own interpreters are asked for by path rather than located by
    # layout, so this needs no knowledge of where uv puts them on Windows.
    $provision = Get-OmhEnv 'OMH_PROVISION_PYTHON' '1'
    if (-not $explicit -and $provision -ne '0' -and (Get-Command uv -ErrorAction SilentlyContinue)) {
        Write-OmhNote "No Python 3.11+ was found. Asking uv, which is already on this machine, for Python $OmhUvPythonVersion."
        Write-OmhNote 'This downloads an interpreter (~66 MB). Decline with OMH_PROVISION_PYTHON=0.'
        $installed = Invoke-OmhCapture -FilePath 'uv' -Arguments @('python', 'install', $OmhUvPythonVersion)
        if ($installed.ExitCode -ne 0) {
            foreach ($line in ($installed.Output -split "`r?`n")) { if ($line.Trim()) { Write-OmhNote $line.Trim() } }
        }
        $found = Select-OmhPython (Get-OmhUvManagedPythons)
        if ($found) { return $found }
        $script:OmhProvisionTried = $true
    }

    if ($explicit -and -not (Get-Command $explicit -ErrorAction SilentlyContinue)) {
        # A typo is the likeliest way this variable goes wrong, and a verdict
        # on the version of a file that is not there sends the reader wrong.
        $lines = @("omh installer: OMH_PYTHON='$explicit' was not found.")
    } elseif ($script:OmhProvisionTried) {
        $lines = @('omh installer: no usable Python 3.11+ was found, and asking uv for one did not produce a usable interpreter.')
    } else {
        $lines = @("omh installer: no usable Python 3.11+ was found (tried: $($candidates -join ', ')).")
    }
    foreach ($reason in $script:OmhRejectedPythons) { $lines += "  $reason" }
    $lines += 'Install Python 3.11+ from https://www.python.org/downloads/windows/ or the Microsoft Store,'
    $lines += 'then set OMH_PYTHON to that executable and retry.'
    Stop-OmhInstall $lines
}

function Get-OmhUvManagedPythons {
    <#
        Absolute paths of uv's own installed interpreters, asked for by uv.

        `uv python find` is deliberately NOT used: it resolves a PROJECT
        environment first and is cwd-dependent, so from a checkout it answers
        that checkout's `.venv` -- which reports a supported version, passes
        the probe, and would become the BASE of OMH's environment. Measured on
        uv 0.12.5, `--managed-python` does not prevent it either. This listing
        is cwd-independent and prints `<key><spaces><path>`; the key never
        contains a space, so everything past the first run of whitespace is
        the path, which may.
    #>
    $listed = Invoke-OmhCapture -FilePath 'uv' -Arguments @('python', 'list', '--managed-python', '--only-installed')
    if ($listed.ExitCode -ne 0) { return @() }
    $paths = @()
    foreach ($line in ($listed.Output -split "`r?`n")) {
        if ($line -match '^\S+\s+(\S.*)$') { $paths += $Matches[1].Trim() }
    }
    return $paths
}

function Select-OmhPython {
    <#  First candidate that reports a version at or above the floor.  #>
    param([string[]]$Candidates)
    foreach ($candidate in $Candidates) {
        if (-not $candidate) { continue }
        if (-not (Test-Path -LiteralPath $candidate) -and -not (Get-Command $candidate -ErrorAction SilentlyContinue)) { continue }
        # Single quotes inside the snippet on purpose: Windows PowerShell 5.1
        # mangles embedded double quotes when building a native command line.
        # `-I` keeps a stray PYTHONPATH or a user site-packages out of the
        # answer, as install.sh's probe does.
        # The second line is the folder a venv made by this interpreter puts
        # python.exe in, asked of the `venv` scheme the venv module itself
        # uses. Windows CPython answers `Scripts`; an MSYS2 or MinGW build
        # answers `bin`, and everything after the venv step looks in Scripts\.
        # Not get_preferred_scheme('prefix'): from inside a venv (Hermes'
        # interpreter, an OMH_PYTHON venv) it answers `venv` on every platform.
        # Interpreters older than 3.11 have no `venv` scheme; they fail the
        # version floor anyway.
        $probe = Invoke-OmhCapture -FilePath $candidate -Arguments @('-I', '-c', 'import sys, os, sysconfig; print(''%d.%d'' % sys.version_info[:2]); print(os.path.basename(sysconfig.get_path(''scripts'', ''venv'', vars={''base'': ''x'', ''platbase'': ''x'', ''installed_base'': ''x'', ''installed_platbase'': ''x''})) if ''venv'' in sysconfig.get_scheme_names() else ''Scripts'')')
        if ($probe.ExitCode -ne 0) { continue }
        # Anchored: this is matched against arbitrary interpreter output, and a
        # wrapper that prints a banner first would otherwise satisfy it.
        if ($probe.Output.Trim() -notmatch '^(\d+)\.(\d+)\r?\n(\w+)$') { continue }
        $major = [int]$Matches[1]
        $minor = [int]$Matches[2]
        $venvScripts = $Matches[3]
        if ($venvScripts -ne 'Scripts') {
            # Keep looking: an MSYS2 python on PATH often sits next to a
            # Windows CPython that `py` or a later slot finds.
            $script:OmhRejectedPythons += "$candidate is an MSYS2/MinGW-style Python (its venvs put python.exe in $venvScripts\, not Windows' Scripts\); use a Windows build from python.org"
            continue
        }
        if ($major -gt 3 -or ($major -eq 3 -and $minor -ge 11)) {
            $script:OmhSelectedPythonVersion = "$major.$minor"
            return $candidate
        }
        # Keep looking rather than stopping here: `py` honors PY_PYTHON and
        # py.ini, so it can land on 3.10 while `python` one slot later is 3.12.
        $script:OmhRejectedPythons += "$candidate is Python $major.$minor"
    }
    return ''
}

# ---------------------------------------------------------------------------
# Command exposure
# ---------------------------------------------------------------------------

# Same probe source install.sh feeds to Python, so both installers agree on
# where a scripts directory can hide.
$OmhProbeSource = @'
import os
import shutil
import site
import sys
import sysconfig

found = shutil.which("omh")
if found:
    print(found)
    raise SystemExit(0)

names = ["omh.exe"] if os.name == "nt" else ["omh"]
schemes = [sysconfig.get_default_scheme()]
schemes.append("nt_user" if os.name == "nt" else "posix_user")

dirs = []
for directory in sys.argv[1:]:
    if directory and directory not in dirs:
        dirs.append(directory)

for scheme in schemes:
    try:
        path = sysconfig.get_path("scripts", scheme)
    except Exception:
        path = ""
    if path and path not in dirs:
        dirs.append(path)

user_base = getattr(site, "USER_BASE", "")
if user_base:
    user_bin = os.path.join(user_base, "Scripts" if os.name == "nt" else "bin")
    if user_bin not in dirs:
        dirs.append(user_bin)

for directory in dirs:
    for name in names:
        candidate = os.path.join(directory, name)
        if os.path.exists(candidate):
            print(candidate)
            raise SystemExit(0)
'@

function Get-OmhCommandOnPath {
    # -CommandType Application and Select -First 1: an `omh` alias or function
    # has an empty Source, and two resolvable executables would return an array
    # that later space-joins into one nonsense path.
    return Get-Command 'omh' -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
}

function Find-OmhCommand {
    if ($OmhCommandHint -and (Test-Path -LiteralPath $OmhCommandHint)) { return $OmhCommandHint }
    $onPath = Get-OmhCommandOnPath
    if ($onPath) { return $onPath.Source }

    # A temp file rather than `python -c`: Windows PowerShell 5.1 mangles
    # multi-line arguments passed to native executables.
    $probeFile = Join-Path ([System.IO.Path]::GetTempPath()) ('omh-probe-' + [guid]::NewGuid().ToString('N') + '.py')
    try {
        [System.IO.File]::WriteAllText($probeFile, $OmhProbeSource)
        $scriptsDir = if ($OmhVenvDir) { Join-Path $OmhVenvDir 'Scripts' } else { '' }
        $result = Invoke-OmhCapture -FilePath $OmhRuntimePython -Arguments @('-I', $probeFile, $OmhBinDir, $scriptsDir)
        if ($result.ExitCode -eq 0) { return $result.Output.Trim() }
        return ''
    } finally {
        Remove-Item -LiteralPath $probeFile -Force -ErrorAction SilentlyContinue
    }
}

function Get-OmhShimEncoding {
    # cmd.exe decodes a batch file with the console OEM code page, so a profile
    # path with non-ASCII characters -- a Hangul or Kanji account name gives one
    # -- is mojibake at execution time in any other encoding.
    try {
        return [System.Text.Encoding]::GetEncoding(
            [System.Globalization.CultureInfo]::CurrentCulture.TextInfo.OEMCodePage)
    } catch {
        return [System.Text.Encoding]::UTF8
    }
}

function Get-OmhShimBody {
    param([string]$Source)
    return "@echo off`r`n`"$Source`" %*`r`n"
}

function New-OmhCommandShim {
    <#
        install.sh's link_omh_command, with a .cmd shim in place of a symlink.
        Creating a symlink on Windows needs Developer Mode or elevation, so an
        installer that used one would fail for most users.
    #>
    if ($OmhLinkCommand -ne '1') { return }
    if (-not $OmhBinDir) {
        Write-OmhLine 'omh installer: OMH_BIN_DIR is not set, so no omh command shim was created.'
        return
    }
    $source = Join-Path $OmhVenvDir 'Scripts\omh.exe'
    if (-not (Test-Path -LiteralPath $source)) { return }

    New-Item -ItemType Directory -Force -Path $OmhBinDir | Out-Null
    $target = Join-Path $OmhBinDir 'omh.cmd'
    $body = Get-OmhShimBody -Source $source
    $encoding = Get-OmhShimEncoding

    if (Test-Path -LiteralPath $target) {
        $existing = ''
        try { $existing = [System.IO.File]::ReadAllText($target, $encoding) } catch { $existing = '' }
        if ($existing -eq $body) {
            $script:OmhCommandHint = $target
            return
        }
        if ($OmhForceLink -eq '1') {
            [System.IO.File]::WriteAllText($target, $body, $encoding)
            $script:OmhCommandHint = $target
            return
        }
        Write-OmhLine "omh installer: $target already exists, so it was not replaced."
        Write-OmhLine "Set OMH_FORCE_LINK=1 to replace it, or use: $source"
        $script:OmhCommandHint = $source
        return
    }

    [System.IO.File]::WriteAllText($target, $body, $encoding)
    $script:OmhCommandHint = $target
}

function Add-OmhBinDirToPath {
    <#
        Append the bin directory to the user-scope PATH when it is missing.

        Through the registry, not [Environment]::SetEnvironmentVariable: that
        call reads the user PATH with every %VAR% already expanded and writes it
        back as REG_SZ, permanently flattening entries other installers wrote as
        %JAVA_HOME%\bin or %LOCALAPPDATA%\... . Adding one directory must not
        silently rewrite the rest of somebody's PATH.

        User scope only, because the machine PATH needs elevation and would
        change other accounts.
    #>
    if ($OmhAddToPath -ne '1') { return }
    if (-not $OmhBinDir) { return }
    if (-not (Test-Path -LiteralPath $OmhBinDir)) { return }

    $key = $null
    try {
        $key = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('Environment', $true)
        if ($null -eq $key) {
            $script:OmhPathNote = 'failed'
            return
        }
        $stored = [string]$key.GetValue(
            'Path', '', [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
        $normalized = $OmhBinDir.TrimEnd('\')
        foreach ($entry in ($stored -split ';' | Where-Object { $_ })) {
            # Compare expanded as well as literal: an existing entry may already
            # be spelled %LOCALAPPDATA%\omh\bin.
            $expanded = [Environment]::ExpandEnvironmentVariables($entry).TrimEnd('\')
            if ($expanded -ieq $normalized -or $entry.TrimEnd('\') -ieq $normalized) {
                $script:OmhPathNote = 'already-present'
                return
            }
        }
        $updated = if ($stored) { $stored.TrimEnd(';') + ';' + $OmhBinDir } else { $OmhBinDir }
        $key.SetValue('Path', $updated, [Microsoft.Win32.RegistryValueKind]::ExpandString)
    } catch {
        $script:OmhPathNote = 'failed'
        return
    } finally {
        # Close(), not Dispose(): a public RegistryKey.Dispose() only arrived in
        # .NET Framework 4.6, and a missing-method error raised here would mask
        # whatever actually happened above.
        if ($key) { $key.Close() }
    }
    $env:PATH = $env:PATH.TrimEnd(';') + ';' + $OmhBinDir
    $script:OmhPathNote = 'added'
}

# ---------------------------------------------------------------------------
# Install modes
# ---------------------------------------------------------------------------

function Get-OmhPipArguments {
    param([string[]]$Extra = @())
    # The default does not apply when $null is passed explicitly, and
    # <array> + $null appends a null element that reaches pip as ''.
    if ($null -eq $Extra) { $Extra = @() }
    return ,(@('install', '--disable-pip-version-check', '-q', '--no-cache-dir', '--force-reinstall') +
        $Extra + @('--upgrade', $OmhPackageUrl))
}

function Install-OmhIntoVenv {
    if (-not $OmhVenvDir) {
        Stop-OmhInstall @(
            'omh installer: USERPROFILE, LOCALAPPDATA, or XDG_DATA_HOME is required for default venv install.',
            'Set OMH_VENV_DIR to an explicit directory and retry.'
        )
    }
    $createLabel = (Get-OmhMessage 'step_create_venv') + ' ' + $OmhVenvDir
    Invoke-OmhStep -Prefix (Get-OmhStepLabel 1) -Label $createLabel -FilePath $OmhRuntimePython -Arguments @('-I', '-m', 'venv', $OmhVenvDir)

    $script:OmhRuntimePython = Join-Path $OmhVenvDir 'Scripts\python.exe'
    $env:PIP_DISABLE_PIP_VERSION_CHECK = '1'
    Invoke-OmhStep -Prefix (Get-OmhStepLabel 2) -Label (Get-OmhMessage 'step_install_package') `
        -FilePath $OmhRuntimePython -Arguments (@('-I', '-m', 'pip') + (Get-OmhPipArguments -Extra (Split-OmhArgString $OmhPipArgs)))

    $script:OmhCommandHint = Join-Path $OmhVenvDir 'Scripts\omh.exe'
    New-OmhCommandShim
    Add-OmhBinDirToPath
}

function Install-OmhIntoPython {
    $extra = Split-OmhArgString $OmhPipArgs
    if (-not $OmhPipArgsWasSet) { $extra = @('--user') }
    $env:PIP_DISABLE_PIP_VERSION_CHECK = '1'
    # -I disables the user site and breaks pip --user; exclude cwd/PYTHONPATH only.
    Invoke-OmhStep -Prefix (Get-OmhStepLabel 1) -Label (Get-OmhMessage 'step_install_python') `
        -FilePath $OmhRuntimePython -Arguments (@('-P', '-E', '-m', 'pip') + (Get-OmhPipArguments -Extra $extra))
}

function Get-OmhNormalizedTag {
    param([string]$Version)
    if ($Version.StartsWith('v')) { return $Version }
    return "v$Version"
}

function Get-OmhRedirectLocation {
    # Invoke-WebRequest exposes different header object types by PowerShell
    # version and whether the redirect was returned or raised as an error.
    param([object]$Response)
    if ($null -eq $Response) { return '' }

    $OmhHeadersProperty = $Response.PSObject.Properties['Headers']
    if (-not $OmhHeadersProperty) { return '' }
    try {
        $OmhHeaders = $OmhHeadersProperty.Value
    } catch {
        return ''
    }
    if ($null -eq $OmhHeaders) { return '' }

    # PowerShell 7's HttpResponseHeaders exposes Location as a Uri property.
    $OmhLocationProperty = $OmhHeaders.PSObject.Properties['Location']
    if ($OmhLocationProperty) {
        try {
            $OmhLocation = $OmhLocationProperty.Value
            foreach ($OmhLocationValue in $OmhLocation) {
                if ($null -ne $OmhLocationValue) { return [string]$OmhLocationValue }
            }
        } catch {}
    }

    # HttpResponseHeaders also provides TryGetValues; dictionaries do not.
    $OmhTryGetValues = $OmhHeaders.PSObject.Methods['TryGetValues']
    if ($OmhTryGetValues) {
        try {
            $OmhLocationValues = $null
            if ($OmhHeaders.TryGetValues('Location', [ref]$OmhLocationValues)) {
                foreach ($OmhLocationValue in $OmhLocationValues) {
                    if ($null -ne $OmhLocationValue) { return [string]$OmhLocationValue }
                }
            }
        } catch {}
    }

    # Windows PowerShell's WebHeaderCollection and response dictionaries use
    # an indexer. Keep it isolated because HttpResponseHeaders has none.
    try {
        $OmhLocation = $OmhHeaders['Location']
        foreach ($OmhLocationValue in $OmhLocation) {
            if ($null -ne $OmhLocationValue) { return [string]$OmhLocationValue }
        }
    } catch {}
    return ''
}

function Get-OmhPropertyValue {
    # StrictMode 3.0 makes reading an absent property a terminating error, and
    # what Invoke-WebRequest returns or throws differs by PowerShell version:
    # Windows PowerShell 5.1 can throw a NullReferenceException, which has no
    # Response at all (#1953).
    param([object]$Object, [string]$Name)
    if ($null -eq $Object) { return $null }
    $OmhProperty = $Object.PSObject.Properties[$Name]
    if (-not $OmhProperty) { return $null }
    try {
        return $OmhProperty.Value
    } catch {
        return $null
    }
}

function Get-OmhFinalResponseUri {
    # Where a followed redirect ended. Windows PowerShell 5.1's HttpWebResponse
    # carries it as ResponseUri; PowerShell 7's HttpResponseMessage carries it
    # on the request it finally sent.
    param([object]$Response)
    $OmhBaseResponse = Get-OmhPropertyValue $Response 'BaseResponse'
    $OmhFinalUri = Get-OmhPropertyValue $OmhBaseResponse 'ResponseUri'
    if ($null -eq $OmhFinalUri) {
        $OmhFinalUri = Get-OmhPropertyValue (Get-OmhPropertyValue $OmhBaseResponse 'RequestMessage') 'RequestUri'
    }
    if ($null -eq $OmhFinalUri) { return '' }
    return [string]$OmhFinalUri
}

function Resolve-OmhLatestReleaseLocation {
    # GitHub answers /releases/latest with a 302 whose Location carries the
    # newest tag, so "latest" costs one header read and no API token. Only the
    # redirect target is fetched. Returns '' when no path produced a URL.
    param([string]$Url)
    $OmhLocation = ''
    try {
        $OmhResponse = Invoke-WebRequest -Uri $Url -Method Head -MaximumRedirection 0 -UseBasicParsing -ErrorAction Stop
        $OmhLocation = Get-OmhRedirectLocation $OmhResponse
    } catch {
        $OmhLocation = Get-OmhRedirectLocation (Get-OmhPropertyValue $_.Exception 'Response')
    }
    if ($OmhLocation) { return $OmhLocation }

    # Windows PowerShell 5.1 can fail the no-redirect request without handing
    # back the 302, so follow the redirect and read where it landed: the same
    # URL and the same tag shape, without the API's anonymous rate limit.
    try {
        $OmhResponse = Invoke-WebRequest -Uri $Url -Method Head -UseBasicParsing -ErrorAction Stop
        return Get-OmhFinalResponseUri $OmhResponse
    } catch {
        return ''
    }
}

# ---------------------------------------------------------------------------
# omher@beta: Hermes when missing, then the omher desktop app
# ---------------------------------------------------------------------------

function Read-OmhInstallerArgs {
    <#  $true for omher@beta, $false otherwise. Also sets the --uninstall,
        --purge and --dry-run switches. Anything else, and any combination the
        installer does not offer, stops with the usage before any work and exit
        code 2, the code install.sh uses for a usage refusal.  #>
    param([object[]]$Arguments = @())
    $beta = $false
    $script:OmhUninstall = $false
    $script:OmhUninstallPurge = $false
    $script:OmhUninstallDryRun = $false
    foreach ($argument in @($Arguments)) {
        $text = [string]$argument
        if ($text -eq 'omher@beta') { $beta = $true; continue }
        if ($text -match '^--?uninstall$') { $script:OmhUninstall = $true; continue }
        if ($text -match '^--?purge$') { $script:OmhUninstallPurge = $true; continue }
        if ($text -match '^--?dry-run$') { $script:OmhUninstallDryRun = $true; continue }
        $script:OmhExitCode = 2
        Stop-OmhInstall @(
            "omh installer: unknown argument '$argument'. The arguments are omher@beta (adds Hermes when missing, and the omher desktop app) and --uninstall [--purge] [--dry-run] (removes OMH):",
            "  $OmhOmherBetaOneLiner",
            "  $OmhUninstallOneLiner"
        )
    }
    $refusal = ''
    if ($script:OmhUninstall -and $beta) { $refusal = '--uninstall cannot be combined with omher@beta.' }
    elseif (-not $script:OmhUninstall -and $script:OmhUninstallPurge) { $refusal = '--purge only works together with --uninstall.' }
    elseif (-not $script:OmhUninstall -and $script:OmhUninstallDryRun) { $refusal = '--dry-run only works together with --uninstall.' }
    if ($refusal) {
        $script:OmhExitCode = 2
        Stop-OmhInstall @(
            "omh installer: $refusal",
            "  $OmhOmherBetaOneLiner",
            "  $OmhUninstallOneLiner"
        )
    }
    return $beta
}

# ---------------------------------------------------------------------------
# --uninstall: hand over to `omh uninstall`
# ---------------------------------------------------------------------------

function Get-OmhUninstallCandidates {
    <#  Where this installer puts the command, in the order install.sh --uninstall
        looks: the bin dir, the active generation's venv under the managed root,
        the installer's own venv. PATH is checked by the caller first.  #>
    param([string]$BinDir, [string]$ManagedRoot, [string]$VenvDir)
    $candidates = @()
    if ($BinDir) {
        $candidates += Join-Path $BinDir 'omh.cmd'
        $candidates += Join-Path $BinDir 'omh.exe'
    }
    if ($ManagedRoot) {
        $candidates += Join-Path $ManagedRoot 'current\venv\Scripts\omh.exe'
    }
    if ($VenvDir) {
        $candidates += Join-Path $VenvDir 'Scripts\omh.exe'
    }
    return $candidates
}

function Get-OmhUninstallArguments {
    param([bool]$Purge, [bool]$DryRun, [string]$Language = '')
    $argv = @('uninstall')
    if ($Purge) { $argv += '--all' }
    if ($DryRun) { $argv += '--dry-run' }
    if ($Language) { $argv += @('--language', $Language) }
    return $argv
}

function Invoke-OmhUninstall {
    <#  Returns the exit code to leave behind: omh's own, or 1 when no command
        was found. Nothing is downloaded or installed on any path.  #>
    $command = ''
    $looked = @('PATH')
    $onPath = Get-OmhCommandOnPath
    if ($onPath) {
        $command = [string]$onPath.Source
    } else {
        $managedRoot = ''
        if ($OmhXdgDataHome) { $managedRoot = Join-Path $OmhXdgDataHome 'omh' }
        elseif ($OmhLocalAppData) { $managedRoot = Join-Path $OmhLocalAppData 'omh' }
        elseif ($OmhHomeDir) { $managedRoot = Join-Path $OmhHomeDir '.local\share\omh' }
        foreach ($candidate in (Get-OmhUninstallCandidates -BinDir $OmhBinDir -ManagedRoot $managedRoot -VenvDir $OmhVenvDir)) {
            $looked += $candidate
            if (Test-Path -LiteralPath $candidate -PathType Leaf) { $command = $candidate; break }
        }
    }
    if (-not $command) {
        Write-OmhLine (Get-OmhMessage 'uninstall_not_found' ($looked -join ', '))
        Write-OmhLine (Get-OmhMessage 'uninstall_left_over')
        return 1
    }
    $language = if ($OmhLangWasSet) { $script:OmhLang } else { '' }
    $argv = Get-OmhUninstallArguments -Purge $script:OmhUninstallPurge -DryRun $script:OmhUninstallDryRun -Language $language
    $ErrorActionPreference = 'Continue'
    $global:LASTEXITCODE = 0
    & $command @argv | Out-Host
    $code = $LASTEXITCODE
    if ($null -eq $code) { $code = 0 }
    return [int]$code
}

function Get-OmhHermesRoot {
    <#
        Hermes runs a profile with HERMES_HOME=<root>\profiles\<name>, and its
        venv lives under <root>. A home whose parent is `profiles` and whose root
        holds its own config.yaml resolves to that root; the omher bridge reads
        it the same way (hermes_root_of).
    #>
    param([string]$HermesHome)
    if (-not $HermesHome) { return $HermesHome }
    $trimmed = $HermesHome.TrimEnd('\', '/')
    $parent = Split-Path -Parent $trimmed
    if ($parent -and (Split-Path -Leaf $parent) -eq 'profiles') {
        $root = Split-Path -Parent $parent
        if ($root -and (Test-Path -LiteralPath (Join-Path $root 'config.yaml') -PathType Leaf)) { return $root }
    }
    return $HermesHome
}

function Get-OmhHermesHome {
    $hermesHome = Get-OmhEnv 'HERMES_HOME'
    if ($hermesHome) { return (Get-OmhHermesRoot $hermesHome) }
    if ($OmhLocalAppData) { return (Join-Path $OmhLocalAppData 'hermes') }
    if ($OmhHomeDir) { return (Join-Path $OmhHomeDir 'AppData\Local\hermes') }
    return ''
}

function Get-OmhHermesPython {
    <#  Hermes' own Python, where Hermes' installer puts it; the omher app looks in the same places.  #>
    $hermesHome = Get-OmhHermesHome
    if (-not $hermesHome) { return '' }
    foreach ($venv in @('venv', '.venv')) {
        $candidate = Join-Path $hermesHome "hermes-agent\$venv\Scripts\python.exe"
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    }
    return ''
}

function Test-OmhHermesPresent {
    if (Get-Command hermes -ErrorAction SilentlyContinue) { return $true }
    return [bool](Get-OmhHermesPython)
}

function Test-OmhOmhPresent {
    if ($OmhVenvDir -and (Test-Path -LiteralPath (Join-Path $OmhVenvDir 'Scripts\omh.exe') -PathType Leaf)) { return $true }
    return [bool](Get-OmhCommandOnPath)
}

function Write-OmhOmherBetaPlan {
    if ($script:OmhHadOmh -and $script:OmhHadHermes) {
        Write-OmhNote 'omher@beta: found Hermes and OMH. Upgrading OMH, then adding the omher app.'
    } elseif ($script:OmhHadHermes) {
        Write-OmhNote "omher@beta: found Hermes without OMH. Installing OMH, connecting it with 'omh setup', then adding the omher app."
    } elseif ($script:OmhInstallHermes -and $script:OmhHadOmh) {
        Write-OmhNote "omher@beta: found OMH without Hermes. Installing Hermes, upgrading OMH, connecting them with 'omh setup', then adding the omher app."
    } elseif ($script:OmhInstallHermes) {
        Write-OmhNote "omher@beta: found neither Hermes nor OMH. Installing Hermes first, then OMH, 'omh setup', and the omher app."
    } else {
        Write-OmhNote "omher@beta: Hermes is not installed and OMH_WITH_HERMES=0 skips it. Install Hermes yourself, then run 'omh setup'."
    }
    if ($OmhWithDesktop -eq '0') {
        Write-OmhNote 'omher@beta: OMH_WITH_DESKTOP=0, so the omher app is not installed.'
    }
}

function Get-OmhPowerShellExe {
    <#  The running host's own executable (powershell.exe 5.1 or pwsh 7).  #>
    try {
        $path = (Get-Process -Id $PID).Path
        if ($path) { return $path }
    } catch {}
    return 'powershell.exe'
}

function New-OmhTempDir {
    $dir = Join-Path ([System.IO.Path]::GetTempPath()) ('omh-install-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
    return $dir
}

function Install-OmhHermes {
    Write-OmhStep '[hermes]' 'Install Hermes Agent with its official installer (non-interactive)'
    $tmp = New-OmhTempDir
    $script = Join-Path $tmp 'hermes-install.ps1'
    try {
        try {
            Invoke-WebRequest -Uri $OmhHermesInstallUrl -OutFile $script -UseBasicParsing -ErrorAction Stop
        } catch {
            Write-OmhFail "Could not download $OmhHermesInstallUrl"
            throw 'omh installer stopped.'
        }
        # A child PowerShell, so Hermes' installer owns its own scope, strict
        # mode and exit code instead of sharing this one.
        & (Get-OmhPowerShellExe) -NoProfile -ExecutionPolicy Bypass -File $script -NonInteractive
        if ($LASTEXITCODE -ne 0) {
            Write-OmhFail "Hermes' installer failed (exit $LASTEXITCODE; its output is above)."
            throw 'omh installer stopped.'
        }
    } finally {
        Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
    }
    if (-not (Test-OmhHermesPresent)) {
        Write-OmhFail "Hermes' installer finished, but no Hermes was found under $(Get-OmhHermesHome)."
        throw 'omh installer stopped.'
    }
    Write-OmhOk 'Hermes Agent'
}

function Select-OmherAssetUrl {
    <#
        The download URL of the newest omher release's asset whose name ends in
        $Suffix. Releases come newest first from the API. Only tags starting
        with omher-v count: the repository's other releases (vX.Y.Z) are the
        Python package, and omher releases are published with --latest=false,
        so /releases/latest never names one.
    #>
    param([object[]]$Releases = @(), [string]$Suffix)
    foreach ($release in @($Releases)) {
        $tag = [string](Get-OmhPropertyValue $release 'tag_name')
        if (-not $tag.StartsWith('omher-v')) { continue }
        foreach ($asset in @(Get-OmhPropertyValue $release 'assets')) {
            $name = [string](Get-OmhPropertyValue $asset 'name')
            if ($name -like "omher-*-$Suffix") {
                return [string](Get-OmhPropertyValue $asset 'browser_download_url')
            }
        }
    }
    return ''
}

function Get-OmhHttpStatus {
    <#  The HTTP status a failed Invoke-RestMethod carried, or 0 when there was no answer.  #>
    param([object]$ErrorRecord)
    $response = Get-OmhPropertyValue (Get-OmhPropertyValue $ErrorRecord 'Exception') 'Response'
    $status = Get-OmhPropertyValue $response 'StatusCode'
    if ($null -eq $status) { return 0 }
    try { return [int]$status } catch { return 0 }
}

function Find-OmherAssetUrl {
    <#
        Pages through /releases ten at a time, newest first, and stops at the
        first omher-v* release with the asset, so one install normally reads
        one small page. GITHUB_TOKEN is sent when set. Returns
        @{ Url; Status } with Status 'found', 'none', 'rate-limited' or 'no-answer'.
    #>
    param([string]$Suffix)
    $headers = @{ Accept = 'application/vnd.github+json' }
    $token = Get-OmhEnv 'GITHUB_TOKEN'
    if ($token) { $headers['Authorization'] = "Bearer $token" }
    for ($page = 1; $page -le $OmhOmherReleasePages; $page++) {
        try {
            $releases = @(Invoke-RestMethod -Uri "$OmhOmherReleasesUrl&page=$page" -Headers $headers -UseBasicParsing -ErrorAction Stop)
        } catch {
            $status = Get-OmhHttpStatus $_
            if ($status -eq 403 -or $status -eq 429) { return @{ Url = ''; Status = 'rate-limited' } }
            return @{ Url = ''; Status = 'no-answer' }
        }
        # Windows PowerShell 5.1 hands a JSON array back as one object holding it.
        if ($releases.Count -eq 1 -and $releases[0] -is [System.Array]) { $releases = @($releases[0]) }
        $url = Select-OmherAssetUrl -Releases $releases -Suffix $Suffix
        if ($url) { return @{ Url = $url; Status = 'found' } }
        if ($releases.Count -lt 10) { break }
    }
    return @{ Url = ''; Status = 'none' }
}

function Get-OmherExpectedSha256 {
    <#  The SHA-256 SHA256SUMS.txt lists for $Name (sha256sum format), or ''.  #>
    param([string]$Sums, [string]$Name)
    foreach ($line in ($Sums -split "`n")) {
        $parts = @($line.Trim() -split '\s+')
        if ($parts.Count -ge 2 -and ($parts[1] -eq $Name -or $parts[1] -eq "*$Name")) { return $parts[0].ToLowerInvariant() }
    }
    return ''
}

function Get-OmherInstallerArguments {
    <#  NSIS silent install; /D= must come last and unquoted.  #>
    param([string]$Directory = '')
    $arguments = @('/S')
    if ($Directory) { $arguments += "/D=$Directory" }
    return ,$arguments
}

function Stop-OmherApp {
    param([string]$Message)
    Write-OmhFail $Message
    Write-OmhNote "Hermes and OMH are installed; only the app step failed. Download omher from $OmhOmherSiteUrl"
    throw 'omh installer stopped.'
}

function Install-OmherApp {
    if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
        Write-OmhStep '[omher]' 'Install the omher desktop app'
        Write-OmhNote 'install.ps1 installs the Windows build only. On macOS, use install.sh with omher@beta.'
        return
    }
    Write-OmhStep '[omher]' 'Install the omher desktop app (Windows x64)'
    $lookup = Find-OmherAssetUrl -Suffix 'windows-x64-setup.exe'
    switch ($lookup.Status) {
        'none' {
            Write-OmhNote 'No omher release was found on GitHub yet.'
            Write-OmhNote "Hermes and OMH are installed. Get the app from $OmhOmherSiteUrl when it is out."
            return
        }
        'rate-limited' {
            Stop-OmherApp "GitHub's API rate limit was reached (60 requests an hour per network without a token). Wait an hour, or set GITHUB_TOKEN, and run this again."
        }
        'no-answer' {
            Stop-OmherApp "GitHub's API did not answer, so the omher release could not be looked up."
        }
    }
    $url = $lookup.Url
    Write-OmhNote "omher installer: $url"
    $tmp = New-OmhTempDir
    $name = $url.Substring($url.LastIndexOf('/') + 1)
    $setup = Join-Path $tmp $name
    try {
        try {
            Invoke-WebRequest -Uri $url -OutFile $setup -UseBasicParsing -ErrorAction Stop
        } catch {
            Stop-OmherApp "Could not download $url"
        }
        # Checked against the release's SHA256SUMS.txt before it runs.
        $sumsUrl = $url.Substring(0, $url.LastIndexOf('/')) + '/SHA256SUMS.txt'
        $sumsFile = Join-Path $tmp 'SHA256SUMS.txt'
        try {
            Invoke-WebRequest -Uri $sumsUrl -OutFile $sumsFile -UseBasicParsing -ErrorAction Stop
        } catch {
            Stop-OmherApp "Could not download $sumsUrl to check the installer."
        }
        $want = Get-OmherExpectedSha256 -Sums ([System.IO.File]::ReadAllText($sumsFile)) -Name $name
        $got = (Get-FileHash -LiteralPath $setup -Algorithm SHA256).Hash.ToLowerInvariant()
        if (-not $want -or $want -ne $got) {
            Stop-OmherApp "The downloaded installer does not match SHA256SUMS.txt (expected $(if ($want) { $want } else { "no entry for $name" }), got $got)."
        }
        Write-OmhOk "SHA-256 matches SHA256SUMS.txt ($name)"
        # The installer is unsigned. Run silently and per user (no admin), which
        # is how the release is built (nsis installMode currentUser).
        $process = Start-Process -FilePath $setup -ArgumentList (Get-OmherInstallerArguments $OmhAppDir) -Wait -PassThru
        if ($process.ExitCode -ne 0) {
            Stop-OmherApp "The omher installer exited with $($process.ExitCode)."
        }
    } finally {
        Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
    }
    if ($OmhAppDir) { $script:OmhOmherAppPath = $OmhAppDir }
    elseif ($OmhLocalAppData) { $script:OmhOmherAppPath = Join-Path $OmhLocalAppData 'omher' }
    else { $script:OmhOmherAppPath = 'the Start menu' }
    Write-OmhOk $script:OmhOmherAppPath
}

# ---------------------------------------------------------------------------
# Main flow
# ---------------------------------------------------------------------------

$OmhInstallFailed = $false
try {
    $script:OmhLang = Get-OmhNormalizedLang $OmhLangRaw
    $script:OmhOmherBeta = Read-OmhInstallerArgs $OmhScriptArgs
    if ($script:OmhUninstall) {
        # Before the header, the interpreter and every network step: a removal
        # never installs anything. The sentinel ends the flow without the
        # failure report below; a nonzero result is carried in the exit code.
        $script:OmhExitCode = Invoke-OmhUninstall
        if ($script:OmhExitCode -ne 0) { $OmhInstallFailed = $true }
        throw 'omh uninstall finished.'
    }
    if ($script:OmhOmherBeta) {
        $script:OmhHadOmh = Test-OmhOmhPresent
        $script:OmhHadHermes = Test-OmhHermesPresent
        $script:OmhInstallHermes = (-not $script:OmhHadHermes) -and $OmhWithHermes -ne '0'
        # Connect OMH to Hermes when either side is new here. An existing OMH
        # on an existing Hermes is only upgraded, as a plain install upgrades it.
        if ((-not $script:OmhHadOmh -or $script:OmhInstallHermes) -and ($script:OmhHadHermes -or $script:OmhInstallHermes)) {
            $OmhRunSetup = '1'
            $OmhTotalSteps = $OmhDoctorStep
        }
    }
    # Header, then the interpreter, then any network work: the order
    # install.sh uses, so a failed release lookup never prints above it.
    Write-OmhHeader (Get-OmhMessage 'installer_title') (Get-OmhMessage 'installer_subtitle')
    if ($script:OmhOmherBeta) {
        Write-OmhOmherBetaPlan
        if ($script:OmhInstallHermes) { Install-OmhHermes }
    }
    $script:OmhRuntimePython = Resolve-OmhPython
    Write-OmhNote "Python: $OmhRuntimePython ($OmhSelectedPythonVersion)"

    if (-not $OmhPackageUrl) {
        switch ($OmhChannel) {
            'preview' {
                $OmhPackageUrl = "$OmhRepoArchiveRoot/heads/main.zip"
                if (-not $OmhSourceRef) { $OmhSourceRef = 'main' }
            }
            'stable' {
                if (-not $OmhVersion) {
                    $OmhLatestLocation = Resolve-OmhLatestReleaseLocation $OmhRepoLatestUrl
                    if ($OmhLatestLocation -match '/releases/tag/v([0-9]+\.[0-9]+\.[0-9]+)/?$') {
                        $OmhVersion = $Matches[1]
                    } else {
                        Stop-OmhInstall @(
                            "omh installer: could not resolve the latest release from $OmhRepoLatestUrl.",
                            'omh installer: set OMH_VERSION to pin one, or OMH_CHANNEL=preview to track main.'
                        )
                    }
                }
                $OmhTag = Get-OmhNormalizedTag $OmhVersion
                # The release workflow only accepts a vX.Y.Z tag and uploads a
                # wheel named from that version, so the asset URL is
                # predictable. It is ~2.7 MB against ~44 MB for the tag
                # archive, which carries assets, tests, and site that nothing
                # needs to run omh. A version outside that shape has no
                # published asset to name, so it keeps the archive.
                $OmhReleaseVersion = $OmhTag.Substring(1)
                if ($OmhReleaseVersion -match '^[0-9]+\.[0-9]+\.[0-9]+$') {
                    $OmhPackageUrl = "$OmhRepoAssetRoot/$OmhTag/oh_my_hermes-$OmhReleaseVersion-py3-none-any.whl"
                } else {
                    $OmhPackageUrl = "$OmhRepoArchiveRoot/tags/$OmhTag.zip"
                }
                if (-not $OmhSourceRef) { $OmhSourceRef = $OmhTag }
            }
            'local' {
                Stop-OmhInstall @('omh installer: OMH_CHANNEL=local requires OMH_PACKAGE_URL to point at a local archive or path accepted by pip.')
            }
            default {
                Stop-OmhInstall @("omh installer: unsupported OMH_CHANNEL '$OmhChannel' (expected preview, stable, or local).")
            }
        }
    } elseif (-not $OmhSourceRef) {
        switch ($OmhChannel) {
            'local'   { $OmhSourceRef = 'local' }
            'stable'  { $OmhSourceRef = if ($OmhVersion) { Get-OmhNormalizedTag $OmhVersion } else { 'custom-url' } }
            'preview' { $OmhSourceRef = 'main' }
            default   { $OmhSourceRef = 'custom-url' }
        }
    }

    Write-OmhNote ((Get-OmhMessage 'channel') + ': ' + $OmhChannel)
    Write-OmhNote "Source ref: $OmhSourceRef"
    Write-OmhNote ((Get-OmhMessage 'mode') + ': ' + $OmhInstallMode)

    switch ($OmhInstallMode) {
        'venv'   { Install-OmhIntoVenv }
        'python' { Install-OmhIntoPython }
        default  {
            Stop-OmhInstall @("omh installer: unsupported OMH_INSTALL_MODE '$OmhInstallMode' (expected venv or python).")
        }
    }

    $script:OmhCommandPath = Find-OmhCommand
    if ($OmhCommandPath) {
        Write-OmhStep (Get-OmhStepLabel $OmhExposeStep) (Get-OmhMessage 'step_expose_command')
        Write-OmhOk $OmhCommandPath
        if ($OmhPathNote -eq 'added') {
            Write-OmhNote "Added '$OmhBinDir' to your user PATH."
            Write-OmhNote 'This shell has it now; other shells pick it up after you sign out and back in.'
            Write-OmhNote 'Set OMH_ADD_TO_PATH=0 to skip this next time.'
        } elseif ($OmhPathNote -eq 'failed') {
            Write-OmhNote "Could not update the user PATH. Add '$OmhBinDir' to it manually."
        }
        if (-not (Get-OmhCommandOnPath)) {
            $OmhCommandDir = Split-Path -Parent $OmhCommandPath
            Write-OmhNote "'$OmhCommandDir' is not on PATH for this shell."
            Write-OmhNote "Add it with: `$env:PATH = `"$OmhCommandDir;`$env:PATH`""
            Write-OmhNote "Until then, use: $OmhCommandPath setup"
        }
    } else {
        Write-OmhLine 'omh installer: installed the package, but could not locate the omh command.'
        Write-OmhLine "Use '$OmhRuntimePython -P -E -m omh.cli setup' as a fallback and check the selected Python scripts directory."
    }

    if ($OmhRunSetup -eq '1') {
        $OmhSetupArgv = @('setup', '--channel', $OmhChannel, '--package-url', $OmhPackageUrl, '--source-ref', $OmhSourceRef, '--command-package-updated')

        if ($OmhLangWasSet) { $OmhSetupArgv += @('--language', $OmhLang) }
        if ($OmhChannel -eq 'local' -and (Test-Path -LiteralPath $OmhPackageUrl -PathType Container)) {
            $OmhSetupArgv += @('--source', $OmhPackageUrl)
        }
        if ($OmhAutoApply -eq '0')  { $OmhSetupArgv += '--skip-apply' }
        if ($OmhVersion)            { $OmhSetupArgv += @('--version', $OmhVersion) }
        if ($OmhWithPlugin -eq '1') { $OmhSetupArgv += '--with-plugin' }
        if ($OmhWithMcp -eq '1')    { $OmhSetupArgv += '--with-mcp' }
        if ($OmhScope)              { $OmhSetupArgv += @('--scope', $OmhScope) }
        foreach ($OmhProfilePack in ($OmhProfilePacks -split ',' | Where-Object { $_ })) {
            $OmhSetupArgv += @('--profile-pack', $OmhProfilePack)
        }
        foreach ($OmhSetupProfile in ($OmhSetupProfiles -split ',' | Where-Object { $_ })) {
            $OmhSetupArgv += @('--profile', $OmhSetupProfile)
        }
        if ($OmhDefaultExecutor) { $OmhSetupArgv += @('--default-executor', $OmhDefaultExecutor) }
        $OmhSetupArgv += (Split-OmhArgString $OmhSetupArgs)

        Write-OmhStep (Get-OmhStepLabel $OmhSetupStep) (Get-OmhMessage 'step_setup')
        Invoke-OmhCli $OmhSetupArgv

        if ($OmhRunDoctor -eq '0') {
            Write-OmhNote 'Skipped doctor check because OMH_RUN_DOCTOR=0.'
        } else {
            Write-OmhStep (Get-OmhStepLabel $OmhDoctorStep) (Get-OmhMessage 'step_doctor')
            try {
                if ($OmhScope) { Invoke-OmhCli @('--scope', $OmhScope, 'doctor') } else { Invoke-OmhCli @('doctor') }
            } catch {
                if (-not $script:OmhOmherBeta) { throw }
                # A Hermes installed a minute ago has no model chosen yet, and
                # doctor says so. That is the person's next step, not a reason
                # to stop before the app.
                Write-OmhNote 'omh doctor reported problems (above). Fix them after the install; continuing with the omher app.'
            }
        }
    } elseif ($OmhAutoApply -eq '0' -or $OmhWithPlugin -eq '1' -or $OmhWithMcp -eq '1' -or $OmhScope -or
              $OmhProfilePacks -or $OmhSetupProfiles -or $OmhDefaultExecutor -or $OmhSetupArgs -or $OmhRunDoctor -eq '0') {
        Write-OmhNote 'Setup options were not applied because install.ps1 installs the command only by default.'
        Write-OmhNote "Run 'omh setup' with those choices explicitly, or set OMH_RUN_SETUP=1 for advanced one-shot bootstrap."
    }

    if ($script:OmhOmherBeta) {
        if ($OmhWithDesktop -eq '0') {
            Write-OmhNote 'Skipped the omher app because OMH_WITH_DESKTOP=0.'
        } else {
            Install-OmherApp
        }
    }

    Write-OmhLine
    Write-OmhLine (Get-OmhColor '1;36' (Get-OmhMessage 'installed'))
    if (Get-OmhCommandOnPath) {
        Write-OmhLine (Get-OmhMessage 'next_path')
    } elseif ($OmhCommandPath) {
        Write-OmhLine (Get-OmhMessage 'next_command_path' $OmhCommandPath)
    } else {
        Write-OmhLine "Next: run '$OmhRuntimePython -P -E -m omh.cli setup' to connect OMH to Hermes, then '$OmhRuntimePython -P -E -m omh.cli doctor' to verify."
    }
    if ($script:OmhOmherBeta) {
        if ($script:OmhInstallHermes) {
            # With the app (installed now, or the app that runs this with
            # OMH_WITH_DESKTOP=0), the model is picked in the app, not in a terminal.
            if ($script:OmhOmherAppPath -or $OmhWithDesktop -eq '0') {
                Write-OmhLine 'Hermes was installed without its setup wizard. Open omher and pick a model from the model menu at the top of the chat.'
            } else {
                Write-OmhLine "Hermes was installed without its setup wizard: run 'hermes setup' to choose a model."
            }
        }
        if ($script:OmhOmherAppPath) {
            Write-OmhLine 'omher is installed. Open it from the Start menu.'
        }
    }
} catch {
    if ($_.Exception.Message -ne 'omh uninstall finished.') {
        Write-OmhLine $_.Exception.Message
        $OmhInstallFailed = $true
    }
}

# `exit` only when this file was run as a script, which is what CI does. Under
# `irm ... | iex` there is no script scope, so exiting would close the user's
# shell on top of the diagnostic they still need to read.
$OmhInvocationPath = ''
$OmhInvocationCommand = $MyInvocation.MyCommand
if ($OmhInvocationCommand) {
    $OmhInvocationPathProperty = $OmhInvocationCommand.PSObject.Properties['Path']
    if ($OmhInvocationPathProperty) { $OmhInvocationPath = [string]$OmhInvocationPathProperty.Value }
}
if ($OmhInstallFailed -and $OmhInvocationPath) { exit $OmhExitCode }
# Run as a script block (the omher@beta form, and the omher app's Install button) there is no file,
# so the `exit` above never runs. Leave the result in $LASTEXITCODE instead, which a caller ending
# with `; exit $LASTEXITCODE` turns into the process exit code; a native probe earlier in the run
# must not leave a stale non-zero there after a clean install.
if ($OmhInstallFailed) { $global:LASTEXITCODE = $OmhExitCode } else { $global:LASTEXITCODE = 0 }
