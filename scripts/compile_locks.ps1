param(
    [string]$Python = "python",
    [string]$IndexUrl = "https://pypi.org/simple",
    [string[]]$UpgradePackage = @()
)

$ErrorActionPreference = "Stop"
$RepositoryRoot = Split-Path -Parent $PSScriptRoot

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Command,
        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]]$Arguments
    )
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $Command $Arguments"
    }
}

$Version = & $Python "-c" "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ($LASTEXITCODE -ne 0) {
    throw "Unable to run Python command: $Python"
}
if ($Version.Trim() -ne "3.11") {
    throw "Lock files must be generated with Python 3.11; found $($Version.Trim())."
}

$PipArgs = "--index-url $IndexUrl"
$UpgradeArguments = @(
    foreach ($Package in $UpgradePackage) {
        if ($Package.Trim()) {
            "--upgrade-package=$($Package.Trim())"
        }
    }
)

Push-Location $RepositoryRoot
try {
    $RuntimeArguments = @(
        "-m", "piptools", "compile", "pyproject.toml",
        "--output-file", "requirements.txt",
        "--strip-extras",
        "--allow-unsafe",
        "--pip-args=$PipArgs"
    ) + $UpgradeArguments
    Invoke-Checked -Command $Python -Arguments $RuntimeArguments

    $DevelopmentArguments = @(
        "-m", "piptools", "compile", "pyproject.toml",
        "--extra=dev",
        "--output-file", "requirements-dev.txt",
        "--strip-extras",
        "--allow-unsafe",
        "--pip-args=$PipArgs"
    ) + $UpgradeArguments
    Invoke-Checked -Command $Python -Arguments $DevelopmentArguments
} finally {
    Pop-Location
}
