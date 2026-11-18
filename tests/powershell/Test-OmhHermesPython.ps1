# Behavioural coverage for install.ps1's Hermes lookup. Like the other files
# here it parses install.ps1 and evaluates only the function definitions, so no
# installer flow runs and nothing leaves the host.
#   Get-OmhLauncherPython : the interpreter a hermes.exe (distlib launcher) or
#                           hermes.cmd names, read from the file, never run
#   Get-OmhHermesPython   : a packaged Hermes (launcher, no venv) is found, as
#                           the omher app finds it; a venv install still is
# Hermes' packaged installer leaves no venv; a lookup that only knew
# `hermes-agent\venv\Scripts\python.exe` reported "no Hermes was found" right
# after installing it. -InjectRegression swaps in that venv-only lookup; the
# packaged cases must catch it.
param([switch]$InjectRegression)

Set-StrictMode -Version 3.0
$ErrorActionPreference = 'Stop'
$script:OmhFailures = @()

function Assert-Omh {
    param([string]$Name, [object]$Actual, [object]$Expected)
    if ("$Actual" -ne "$Expected") {
        $script:OmhFailures += "$Name : expected '$Expected', got '$Actual'"
    }
}

# A distlib-shaped launcher: a stub ending in NUL bytes, "#!<python> -I", then
# a zip whose own entry text holds another "#!" line that must not be read.
function New-OmhExeLauncher {
    param([string]$Path, [string]$Python)
    $stub = [byte[]](0x4D, 0x5A, 0x90, 0x00, 0x03, 0x00, 0x00, 0x00)
    $shebang = [System.Text.Encoding]::UTF8.GetBytes("#!$Python -I`r`n")
    $zipPath = Join-Path ([System.IO.Path]::GetDirectoryName($Path)) 'payload.zip'
    $src = Join-Path ([System.IO.Path]::GetDirectoryName($Path)) 'payload'
    New-Item -ItemType Directory -Force -Path $src | Out-Null
    Set-Content -LiteralPath (Join-Path $src '__main__.py') -Value "#!C:\decoy\python.exe -I`nimport sys" -NoNewline
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    if (Test-Path -LiteralPath $zipPath) { Remove-Item -LiteralPath $zipPath -Force }
    [System.IO.Compression.ZipFile]::CreateFromDirectory($src, $zipPath)
    $zip = [System.IO.File]::ReadAllBytes($zipPath)
    [System.IO.File]::WriteAllBytes($Path, [byte[]]($stub + $shebang + $zip))
    Remove-Item -LiteralPath $zipPath, $src -Recurse -Force
}

try {
    $errors = $null
    $installerPath = (Resolve-Path (Join-Path $PSScriptRoot '..\..\install.ps1')).ProviderPath
    $installerAst = [System.Management.Automation.Language.Parser]::ParseFile($installerPath, [ref]$null, [ref]$errors)
    if ($errors) { throw "install.ps1 does not parse: $($errors[0].Message)" }
    foreach ($functionName in @('Get-OmhEnv', 'Get-OmhHermesRoot', 'Get-OmhHermesHome', 'Get-OmhLauncherPython', 'Get-OmhHermesPython')) {
        $definition = @($installerAst.FindAll({
            param($node)
            $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $functionName
        }, $true))[0]
        if ($null -eq $definition) { throw "install.ps1 does not define $functionName." }
        Invoke-Expression $definition.Extent.Text
    }

    if ($InjectRegression) {
        function Get-OmhHermesPython {
            $hermesHome = Get-OmhHermesHome
            if (-not $hermesHome) { return '' }
            foreach ($venv in @('venv', '.venv')) {
                $candidate = Join-Path $hermesHome "hermes-agent\$venv\Scripts\python.exe"
                if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
            }
            return ''
        }
    }

    $root = Join-Path ([System.IO.Path]::GetTempPath()) ("omh-hermes-python-" + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Force -Path $root | Out-Null
    # Windows paths are what the launchers name; the reader only checks the shape, and
    # Get-OmhHermesPython checks the file exists, so the store Python lives at a path
    # that is both a real file here and written in the launcher as it is.
    $sep = [System.IO.Path]::DirectorySeparatorChar
    try {
        # -- reading a launcher ---------------------------------------------------------------
        $exe = Join-Path $root 'hermes.exe'
        New-OmhExeLauncher -Path $exe -Python 'C:\Users\a b\AppData\Local\hermes\tools\python-3.14\python.exe'
        Assert-Omh 'hermes.exe names its store Python (a space in the path too)' (Get-OmhLauncherPython $exe) 'C:\Users\a b\AppData\Local\hermes\tools\python-3.14\python.exe'

        $cmd = Join-Path $root 'hermes.cmd'
        [System.IO.File]::WriteAllText($cmd, "@echo off`r`n`r`n`"C:\Hermes Store\python.exe`" -I -c `"import sys`" %*`r`n")
        Assert-Omh 'hermes.cmd names its quoted Python past a blank line' (Get-OmhLauncherPython $cmd) 'C:\Hermes Store\python.exe'

        $notLauncher = Join-Path $root 'other.cmd'
        [System.IO.File]::WriteAllText($notLauncher, "echo hi`r`n")
        Assert-Omh 'a .cmd without @echo off is not a launcher' (Get-OmhLauncherPython $notLauncher) ''
        Assert-Omh 'a missing launcher names nothing' (Get-OmhLauncherPython (Join-Path $root 'absent.exe')) ''

        $relative = Join-Path $root 'rel.cmd'
        [System.IO.File]::WriteAllText($relative, "@echo off`r`npython.exe -I -c `"x`" %*`r`n")
        Assert-Omh 'a relative interpreter is not taken' (Get-OmhLauncherPython $relative) ''

        # -- the lookup over a Hermes home ----------------------------------------------------
        # On a non-Windows test host the store Python is a real file at a Unix path, which
        # is not a Windows absolute path; the lookup is then exercised with a stand-in
        # reader that returns that real path, after the shape check above proved the reader.
        $hermes = Join-Path $root 'hermes'
        $bin = Join-Path $hermes 'hermes-agent\.hermes\bin'
        New-Item -ItemType Directory -Force -Path $bin | Out-Null
        $store = Join-Path $hermes 'tools\python-3.14'
        New-Item -ItemType Directory -Force -Path $store | Out-Null
        $python = Join-Path $store 'python.exe'
        Set-Content -LiteralPath $python -Value '' -NoNewline
        $env:HERMES_HOME = $hermes
        if ($sep -eq '\') {
            New-OmhExeLauncher -Path (Join-Path $bin 'hermes.exe') -Python $python
        } else {
            Set-Content -LiteralPath (Join-Path $bin 'hermes.exe') -Value 'launcher' -NoNewline
            $script:OmhStandInPython = $python
            if (-not $InjectRegression) {
                function Get-OmhLauncherPython { param([string]$Path) if ($Path -like '*hermes.exe' -and (Test-Path -LiteralPath $Path)) { return $script:OmhStandInPython } return '' }
            }
        }
        Assert-Omh 'a packaged Hermes (launcher, no venv) is found' (Get-OmhHermesPython) $python

        $packaged = Join-Path $root 'hermes-venv'
        $venvPython = Join-Path $packaged 'hermes-agent\venv\Scripts\python.exe'
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $venvPython) | Out-Null
        Set-Content -LiteralPath $venvPython -Value '' -NoNewline
        $env:HERMES_HOME = $packaged
        Assert-Omh 'a venv install is still found' (Get-OmhHermesPython) $venvPython
    } finally {
        Remove-Item Env:\HERMES_HOME -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue
    }
} catch {
    $script:OmhFailures += "harness: $($_.Exception.Message)"
}

if ($InjectRegression) {
    if ($script:OmhFailures.Count -eq 0) {
        Write-Error 'The venv-only Hermes lookup passed every case; the packaged-install case no longer guards it.'
        exit 1
    }
    Write-Host "Injected regression caught ($($script:OmhFailures.Count) failure(s))."
    exit 0
}
if ($script:OmhFailures.Count -gt 0) {
    $script:OmhFailures | ForEach-Object { Write-Error $_ -ErrorAction Continue }
    exit 1
}
Write-Host "install.ps1 Hermes lookup: all cases passed on $($PSVersionTable.PSVersion)"
