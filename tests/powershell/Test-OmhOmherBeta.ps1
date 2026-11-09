# Behavioural coverage for install.ps1's omher@beta helpers. Like the other
# files here it parses install.ps1 and evaluates only the function
# definitions, so no installer flow runs and no request leaves the host.
#   Read-OmhInstallerArgs  : no argument, omher@beta, and a refused unknown one
#   Select-OmherAssetUrl   : newest omher-v* release only, never the OMH package
#   Get-OmherInstallerArguments : the NSIS silent switches
# -InjectRegression swaps in a picker that ignores the tag prefix; the
# "package release listed first" case must catch it.
param([switch]$InjectRegression)

Set-StrictMode -Version 3.0
$ErrorActionPreference = 'Stop'
$script:OmhFailures = @()

function Write-OmhLine { param([string]$Text = '') $script:OmhLines += $Text }
$script:OmhLines = @()
$OmhOmherBetaOneLiner = '& ([scriptblock]::Create((irm https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.ps1))) omher@beta'

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

function New-OmhRelease {
    param([string]$Tag, [string[]]$Names)
    $assets = @()
    foreach ($n in $Names) {
        $assets += [pscustomobject]@{
            name = $n
            browser_download_url = "https://github.com/rlaope/oh-my-hermes/releases/download/$Tag/$n"
        }
    }
    return [pscustomobject]@{ tag_name = $Tag; assets = $assets }
}

try {
    $errors = $null
    $installerPath = (Resolve-Path (Join-Path $PSScriptRoot '..\..\install.ps1')).ProviderPath
    $installerAst = [System.Management.Automation.Language.Parser]::ParseFile($installerPath, [ref]$null, [ref]$errors)
    if ($errors) { throw "install.ps1 does not parse: $($errors[0].Message)" }
    foreach ($functionName in @('Get-OmhPropertyValue', 'Read-OmhInstallerArgs', 'Select-OmherAssetUrl', 'Get-OmherInstallerArguments')) {
        $definition = @($installerAst.FindAll({
            param($node)
            $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $functionName
        }, $true))[0]
        if ($null -eq $definition) { throw "install.ps1 does not define $functionName." }
        Invoke-Expression $definition.Extent.Text
    }

    if ($InjectRegression) {
        function Select-OmherAssetUrl {
            param([object[]]$Releases = @(), [string]$Suffix)
            foreach ($release in @($Releases)) {
                foreach ($asset in @($release.assets)) {
                    if ($asset.name -like "*$Suffix" -or $asset.name -like '*.whl') { return [string]$asset.browser_download_url }
                }
            }
            return ''
        }
    }

    # -- arguments ---------------------------------------------------------------------------
    Assert-Omh 'no argument keeps the plain install' (Read-OmhInstallerArgs @()) $false
    Assert-Omh 'omher@beta opts in' (Read-OmhInstallerArgs @('omher@beta')) $true
    $refused = $false
    try { Read-OmhInstallerArgs @('omher@stable') | Out-Null } catch { $refused = $true }
    Assert-Omh 'an unknown argument is refused' $refused $true
    Assert-Omh 'the refusal names the argument' ([bool]($script:OmhLines -match "unknown argument 'omher@stable'")) $true
    Assert-Omh 'the refusal shows the one-liner' ([bool]($script:OmhLines -match [regex]::Escape($OmhOmherBetaOneLiner))) $true

    # -- the scriptblock form really hands the argument over ----------------------------------
    $probe = [scriptblock]::Create('return @($args)')
    $seen = & $probe omher@beta
    Assert-Omh 'scriptblock form passes omher@beta' ($seen -join ',') 'omher@beta'

    # -- asset selection ---------------------------------------------------------------------
    $app = New-OmhRelease 'omher-v0.1.0' @('omher-0.1.0-macos-arm64.dmg', 'omher-0.1.0-windows-x64-setup.exe', 'omher-0.1.0-windows-x64.msi')
    $newer = New-OmhRelease 'omher-v0.2.0' @('omher-0.2.0-windows-x64-setup.exe')
    $pkg = New-OmhRelease 'v4.0.7' @('oh_my_hermes-4.0.7-py3-none-any.whl', 'omher-9.9.9-windows-x64-setup.exe')
    Assert-Omh 'package release listed first is skipped' (Select-OmherAssetUrl -Releases @($pkg, $app) -Suffix 'windows-x64-setup.exe') `
        'https://github.com/rlaope/oh-my-hermes/releases/download/omher-v0.1.0/omher-0.1.0-windows-x64-setup.exe'
    Assert-Omh 'the newest omher release wins' (Select-OmherAssetUrl -Releases @($newer, $app) -Suffix 'windows-x64-setup.exe') `
        'https://github.com/rlaope/oh-my-hermes/releases/download/omher-v0.2.0/omher-0.2.0-windows-x64-setup.exe'
    Assert-Omh 'no omher release yet' (Select-OmherAssetUrl -Releases @($pkg) -Suffix 'windows-x64-setup.exe') ''
    Assert-Omh 'an empty list' (Select-OmherAssetUrl -Releases @() -Suffix 'windows-x64-setup.exe') ''

    # -- NSIS switches -----------------------------------------------------------------------
    Assert-Omh 'silent by default' ((Get-OmherInstallerArguments '') -join ' ') '/S'
    Assert-Omh 'a folder goes last as /D=' ((Get-OmherInstallerArguments 'C:\Apps\omher') -join ' ') '/S /D=C:\Apps\omher'

    if ($InjectRegression) {
        if (-not ($script:OmhFailures -match 'package release listed first')) {
            throw 'the injected tag-blind picker was not caught.'
        }
        Write-Host "PASS: injected picker caught ($($script:OmhFailures.Count) failing case(s))."
    } elseif ($script:OmhFailures.Count -gt 0) {
        throw ($script:OmhFailures -join "`n")
    } else {
        Write-Host 'PASS: omher@beta helper cases'
    }
} catch {
    [Console]::Error.WriteLine("FAIL: $($_.Exception.Message)")
    exit 1
}
