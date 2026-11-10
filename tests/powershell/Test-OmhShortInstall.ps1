# Behavioural coverage for site/install.ps1, served as https://omher.app/install.ps1.
# A local Invoke-RestMethod shadows the cmdlet and answers with a stub installer,
# so no request leaves the host:
#   the URL      : only install.ps1 on main is fetched
#   no argument  : `irm https://omher.app/install.ps1 | iex` runs the installer with none,
#                  exactly like `irm <install.ps1> | iex`
#   arguments    : the scriptblock form forwards the caller's own, adding nothing
#   exit status  : a failed install leaves its code in $LASTEXITCODE, and the wrapper
#                  never calls exit (the user's window stays open)
# -InjectRegression runs a wrapper that adds omher@beta; the no-argument case must catch it.
param([switch]$InjectRegression)

Set-StrictMode -Version 3.0
$ErrorActionPreference = 'Stop'
$script:OmhFailures = @()
$OmhInstallPs1Url = 'https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.ps1'

function Assert-Omh {
    param([string]$Name, [object]$Actual, [object]$Expected)
    if ("$Actual" -ne "$Expected") {
        $script:OmhFailures += "$Name : expected '$Expected', got '$Actual'"
    }
}

$global:OmhShortUrls = @()
$global:OmhShortArgs = $null
function Invoke-RestMethod {
    param([Parameter(Position = 0)][string]$Uri)
    $global:OmhShortUrls += $Uri
    # The stub installer: records its arguments, then sets the exit code the test asks for.
    return '$global:OmhShortArgs = @($args); $global:LASTEXITCODE = [int]$env:OMH_FAKE_RC'
}

try {
    $wrapperPath = (Resolve-Path (Join-Path $PSScriptRoot '..\..\site\install.ps1')).ProviderPath
    $wrapperText = [System.IO.File]::ReadAllText($wrapperPath)
    if ($InjectRegression) { $wrapperText = $wrapperText.Replace(') @args', ') omher@beta @args') }
    $errors = $null
    [void][System.Management.Automation.Language.Parser]::ParseInput($wrapperText, [ref]$null, [ref]$errors)
    if ($errors) { throw "site/install.ps1 does not parse: $($errors[0].Message)" }
    $wrapper = [scriptblock]::Create($wrapperText)

    # `irm https://omher.app/install.ps1 | iex`: iex gets the text and no arguments.
    $env:OMH_FAKE_RC = '0'
    Invoke-Expression $wrapperText
    Assert-Omh 'irm | iex passes no argument' (@($global:OmhShortArgs).Count) 0
    Assert-Omh 'only install.ps1 on main is fetched' ($global:OmhShortUrls -join ',') $OmhInstallPs1Url
    Assert-Omh 'a clean install leaves LASTEXITCODE 0' $LASTEXITCODE 0

    # The scriptblock form forwards the caller's own arguments.
    & $wrapper omher@beta 'two words'
    Assert-Omh 'arguments are forwarded as given' ($global:OmhShortArgs -join '|') 'omher@beta|two words'

    # A failed install: its code stays in $LASTEXITCODE and this script keeps running,
    # which it would not if the wrapper called exit.
    $env:OMH_FAKE_RC = '3'
    Invoke-Expression $wrapperText
    $code = $LASTEXITCODE
    # The failure was on purpose. Clear it: GitHub's pwsh shell ends every step with
    # `exit $LASTEXITCODE`, which would otherwise fail this passing test.
    $global:LASTEXITCODE = 0
    Assert-Omh 'a failed install leaves its exit code' $code 3
    Assert-Omh 'the wrapper never calls exit' ([bool]($wrapperText -match '(?m)^[^#]*\bexit\b')) $false

    if ($InjectRegression) {
        if (-not ($script:OmhFailures -match 'irm \| iex passes no argument')) {
            throw 'the injected omher@beta argument was not caught.'
        }
        Write-Host "PASS: injected argument caught ($($script:OmhFailures.Count) failing case(s))."
    } elseif ($script:OmhFailures.Count -gt 0) {
        throw ($script:OmhFailures -join "`n")
    } else {
        Write-Host 'PASS: short install wrapper cases'
    }
} catch {
    [Console]::Error.WriteLine("FAIL: $($_.Exception.Message)")
    exit 1
} finally {
    Remove-Item Env:\OMH_FAKE_RC -ErrorAction SilentlyContinue
}
