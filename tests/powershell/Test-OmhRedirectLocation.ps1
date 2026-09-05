# Behavioural coverage for Get-OmhRedirectLocation. This deliberately parses
# install.ps1 and evaluates only the function definition: dot-sourcing the
# installer would execute its top-level installation flow.
param([switch]$InjectRegression)

Set-StrictMode -Version 3.0
$ErrorActionPreference = 'Stop'
$script:OmhMutationFailures = @()

function Get-OmhHeaderCapabilityProfile {
    param([object]$Headers)

    $hasLocation = $false
    $hasTryGetValues = $false
    $hasItem = $false
    if ($null -ne $Headers) {
        $hasLocation = $null -ne $Headers.PSObject.Properties['Location']
        $hasTryGetValues = $null -ne $Headers.PSObject.Methods['TryGetValues']
        $hasItem = $null -ne $Headers.PSObject.Properties['Item']
    }
    return "Location=$hasLocation; TryGetValues=$hasTryGetValues; Item=$hasItem"
}

function Assert-OmhRedirectLocation {
    param(
        [string]$Name,
        [object]$Response,
        [string]$Expected,
        [object]$Headers = $null
    )

    try {
        $actual = Get-OmhRedirectLocation $Response
    } catch {
        $message = "$Name threw $($_.Exception.Message)"
        if ($InjectRegression) {
            # The injected accessor can only fail by reading a missing Headers
            # property or by indexing an object without an indexer. Do not let
            # unrelated exceptions turn the mutation check green.
            if ($_.Exception.Message -notmatch '(?i)index|headers') {
                throw "Unexpected injected-accessor failure: $message"
            }
            $script:OmhMutationFailures += [pscustomobject]@{ Name = $Name; Message = $message }
            Write-Host "REGRESSION DETECTED: $message"
            return
        }
        throw $message
    }

    if ($actual -ne $Expected) {
        $message = "$Name returned '$actual'; expected '$Expected'."
        if ($InjectRegression) {
            $script:OmhMutationFailures += [pscustomobject]@{ Name = $Name; Message = $message }
            Write-Host "REGRESSION DETECTED: $message"
            return
        }
        throw $message
    }

    Write-Host ('PASS: {0} ({1})' -f $Name, (Get-OmhHeaderCapabilityProfile $Headers))
}

try {
    if ($InjectRegression) {
        # Issue #1350 pre-fix implementation. It assumes every header object
        # has an indexer, which PowerShell 7 error responses do not.
        function Get-OmhRedirectLocation { param([object]$Response) return [string]$Response.Headers['Location'] }
        Write-Host 'Injecting the pre-fix redirect-header accessor.'
    } else {
        $errors = $null
        $installerPath = (Resolve-Path (Join-Path $PSScriptRoot '..\..\install.ps1')).ProviderPath
        $installerAst = [System.Management.Automation.Language.Parser]::ParseFile(
            $installerPath, [ref]$null, [ref]$errors)
        if ($errors) {
            $errors | ForEach-Object {
                throw "install.ps1($($_.Extent.StartLineNumber),$($_.Extent.StartColumnNumber)): $($_.Message)"
            }
        }

        $accessor = @($installerAst.FindAll({
            param($node)
            $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
                $node.Name -eq 'Get-OmhRedirectLocation'
        }, $true))[0]
        if ($null -eq $accessor) {
            throw 'install.ps1 does not define Get-OmhRedirectLocation.'
        }

        # The AST extent contains just the function definition, not installer code.
        Invoke-Expression $accessor.Extent.Text
    }

    # The parenthesised PASS profile is the authority for each branch; comments follow it.
    # PowerShell 7 successful Invoke-WebRequest responses expose a dictionary
    # from header name to a collection of strings. The observed profile takes
    # the indexer branch.
    $ps7SuccessHeaders = New-Object 'System.Collections.Generic.Dictionary[string,System.Collections.Generic.IEnumerable[string]]'
    $ps7SuccessHeaders.Add('Location', [string[]]@('https://example.test/ps7-success'))
    Assert-OmhRedirectLocation 'PowerShell 7 success dictionary' ([pscustomobject]@{
        Headers = $ps7SuccessHeaders
    }) 'https://example.test/ps7-success' -Headers $ps7SuccessHeaders

    # PowerShell 7 error responses expose a Uri Location property and
    # TryGetValues, but no indexer. It alone takes the Location property branch.
    $ps7ErrorHeaders = [pscustomobject]@{
        Location = [uri]'https://example.test/ps7-error'
    }
    $ps7ErrorHeaders | Add-Member -MemberType ScriptMethod -Name TryGetValues -Value {
        param([string]$Name, [ref]$Values)
        if ($Name -eq 'Location') {
            $Values.Value = [string[]]@('https://example.test/ps7-error')
            return $true
        }
        return $false
    }
    Assert-OmhRedirectLocation 'PowerShell 7 error response without indexer' ([pscustomobject]@{
        Headers = $ps7ErrorHeaders
    }) 'https://example.test/ps7-error' -Headers $ps7ErrorHeaders

    # This PSCustomObject has only TryGetValues: no Location adapted property
    # and no Item indexer. The observed profile takes the TryGetValues branch.
    $tryGetValuesOnlyHeaders = [pscustomobject]@{}
    $tryGetValuesOnlyHeaders | Add-Member -MemberType ScriptMethod -Name TryGetValues -Value {
        param([string]$Name, [ref]$Values)
        if ($Name -eq 'Location') {
            $Values.Value = [string[]]@('https://example.test/try-get-values')
            return $true
        }
        return $false
    }
    $tryGetValuesOnlyProfile = Get-OmhHeaderCapabilityProfile $tryGetValuesOnlyHeaders
    if ($tryGetValuesOnlyHeaders.PSObject.Properties['Location'] -or
        $tryGetValuesOnlyHeaders.PSObject.Properties['Item']) {
        throw "TryGetValues-only fake observed $tryGetValuesOnlyProfile."
    }
    Assert-OmhRedirectLocation 'TryGetValues-only header fallback' ([pscustomobject]@{
        Headers = $tryGetValuesOnlyHeaders
    }) 'https://example.test/try-get-values' -Headers $tryGetValuesOnlyHeaders

    # Windows PowerShell 5.1 successful requests provide a plain dictionary.
    # The observed profile takes the indexer branch.
    $ps51SuccessHeaders = New-Object 'System.Collections.Generic.Dictionary[string,string]'
    $ps51SuccessHeaders.Add('Location', 'https://example.test/ps51-success')
    Assert-OmhRedirectLocation 'Windows PowerShell 5.1 success dictionary' ([pscustomobject]@{
        Headers = $ps51SuccessHeaders
    }) 'https://example.test/ps51-success' -Headers $ps51SuccessHeaders

    # Windows PowerShell 5.1 error responses use this framework header type.
    # The observed profile takes the indexer branch.
    $ps51ErrorHeaders = New-Object System.Net.WebHeaderCollection
    $ps51ErrorHeaders.Add('Location', 'https://example.test/ps51-error')
    Assert-OmhRedirectLocation 'Windows PowerShell 5.1 WebHeaderCollection error response' ([pscustomobject]@{
        Headers = $ps51ErrorHeaders
    }) 'https://example.test/ps51-error' -Headers $ps51ErrorHeaders

    # NameValueCollection supports a string-key indexer and has no
    # TryGetValues method. The observed profile takes the indexer branch.
    $indexerOnlyHeaders = New-Object System.Collections.Specialized.NameValueCollection
    $indexerOnlyHeaders.Add('Location', 'https://example.test/indexer-only')
    $indexerOnlyProfile = Get-OmhHeaderCapabilityProfile $indexerOnlyHeaders
    if ($indexerOnlyHeaders.PSObject.Methods['TryGetValues']) {
        throw "NameValueCollection indexer fake observed $indexerOnlyProfile."
    }
    Assert-OmhRedirectLocation 'NameValueCollection indexer fallback' ([pscustomobject]@{
        Headers = $indexerOnlyHeaders
    }) 'https://example.test/indexer-only' -Headers $indexerOnlyHeaders

    Assert-OmhRedirectLocation 'null response' $null ''
    Assert-OmhRedirectLocation 'response without Headers property' ([pscustomobject]@{}) ''
    Assert-OmhRedirectLocation 'headers without Location' ([pscustomobject]@{
        Headers = (New-Object 'System.Collections.Generic.Dictionary[string,string]')
    }) ''
    Assert-OmhRedirectLocation 'null Location value' ([pscustomobject]@{
        Headers = [pscustomobject]@{ Location = $null }
    }) ''

    if ($InjectRegression) {
        if ($script:OmhMutationFailures.Count -eq 0) {
            throw 'Injected pre-fix accessor passed all 10 cases; the behavioural suite did not detect the regression.'
        }
        $ps7ErrorDetector = @($script:OmhMutationFailures | Where-Object {
            $_.Name -eq 'PowerShell 7 error response without indexer'
        })
        if ($ps7ErrorDetector.Count -eq 0) {
            throw 'Injected pre-fix accessor was not caught by the PowerShell 7 error response without indexer.'
        }
        Write-Host 'PASS: PowerShell 7 error response without indexer caught the injected regression.'
        Write-Host "PASS: injected pre-fix accessor failed $($script:OmhMutationFailures.Count) of 10 cases as expected."
    } else {
        Write-Host 'PASS: 10 redirect-header cases'
    }
} catch {
    [Console]::Error.WriteLine("FAIL: $($_.Exception.Message)")
    exit 1
}
