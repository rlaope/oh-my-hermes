# Behavioural coverage for install.ps1's Select-OmhPython. Like the other files
# here it parses install.ps1 and evaluates only the function definitions, so no
# installer flow runs. Each interpreter is a .cmd stub that answers the probe.
#   MSYS2/MinGW python : its venvs put python.exe in bin\, and the installer then
#                        stopped with "Scripts\python.exe is not recognized".
#                        It is rejected with a reason, and the next candidate wins.
#   Windows python     : venvs use Scripts\, 3.11+, chosen.
#   venv python        : Hermes' own interpreter or an OMH_PYTHON venv; it lives
#                        in a venv and its venvs use Scripts\, so it is chosen.
#   old python         : rejected by version, as before.
# -InjectRegression evaluates the pre-fix selector (version only); the MSYS2 case
# must catch it.
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

function New-OmhStubPython {
    param([string]$Dir, [string]$Name, [string]$Version, [string]$VenvScripts)
    $path = Join-Path $Dir "$Name.cmd"
    [System.IO.File]::WriteAllText($path, "@echo off`r`necho $Version`r`necho $VenvScripts`r`n")
    return $path
}

$stubDir = Join-Path ([System.IO.Path]::GetTempPath()) ("omh-pysel-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $stubDir | Out-Null
try {
    $errors = $null
    $installerPath = (Resolve-Path (Join-Path $PSScriptRoot '..\..\install.ps1')).ProviderPath
    $installerText = [System.IO.File]::ReadAllText($installerPath)
    if ($InjectRegression) {
        # The selector as it was: the scheme line is never read.
        $installerText = $installerText.Replace("if (`$venvScripts -ne 'Scripts') {", "if (`$false) {")
    }
    $installerAst = [System.Management.Automation.Language.Parser]::ParseInput($installerText, [ref]$null, [ref]$errors)
    if ($errors) { throw "install.ps1 does not parse: $($errors[0].Message)" }
    foreach ($functionName in @('Invoke-OmhCapture', 'Select-OmhPython')) {
        $definition = @($installerAst.FindAll({
            param($node)
            $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $functionName
        }, $true))[0]
        if ($null -eq $definition) { throw "install.ps1 does not define $functionName." }
        Invoke-Expression $definition.Extent.Text
    }

    $msys = New-OmhStubPython $stubDir 'msys-python' '3.14' 'bin'
    $windows = New-OmhStubPython $stubDir 'win-python' '3.12' 'Scripts'
    $venvPython = New-OmhStubPython $stubDir 'venv-python' '3.11' 'Scripts'
    $old = New-OmhStubPython $stubDir 'old-python' '3.9' 'Scripts'

    $script:OmhRejectedPythons = @()
    $chosen = Select-OmhPython @($msys, $windows)
    Assert-Omh 'an MSYS2 python first on the list is skipped for a Windows one' $chosen $windows
    Assert-Omh 'the skip names the MSYS2 python and its layout' ([bool]($script:OmhRejectedPythons -match 'MSYS2/MinGW-style Python \(its venvs put python\.exe in bin\\')) $true

    $script:OmhRejectedPythons = @()
    $chosen = Select-OmhPython @($msys)
    Assert-Omh 'an MSYS2 python alone is not chosen' $chosen ''

    $script:OmhRejectedPythons = @()
    $chosen = Select-OmhPython @($msys, $venvPython)
    Assert-Omh 'a python running from a venv (Hermes'' own) is chosen' $chosen $venvPython

    $script:OmhRejectedPythons = @()
    $chosen = Select-OmhPython @($old, $windows)
    Assert-Omh 'an old python is still skipped' $chosen $windows
    Assert-Omh 'the old python is named by version' ([bool]($script:OmhRejectedPythons -match 'is Python 3\.9')) $true

    if ($InjectRegression) {
        if (-not ($script:OmhFailures -match 'MSYS2 python')) {
            throw 'the version-only selector was not caught.'
        }
        Write-Host "PASS: version-only selector caught ($($script:OmhFailures.Count) failing case(s))."
    } elseif ($script:OmhFailures.Count -gt 0) {
        throw ($script:OmhFailures -join "`n")
    } else {
        Write-Host 'PASS: python selection cases'
    }
} catch {
    [Console]::Error.WriteLine("FAIL: $($_.Exception.Message)")
    exit 1
} finally {
    Remove-Item -Recurse -Force $stubDir -ErrorAction SilentlyContinue
}
