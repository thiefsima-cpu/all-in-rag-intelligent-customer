param(
    [ValidateSet("dev", "runtime", "agent")]
    [string]$Profile = "dev",
    [string]$CondaEnvName = ""
)

$ErrorActionPreference = "Stop"
$RepositoryRoot = Split-Path -Parent $PSScriptRoot

switch ($Profile) {
    "runtime" {
        if (-not $CondaEnvName) { $CondaEnvName = "graphrag-c9-runtime" }
        $RequirementsPath = Join-Path $RepositoryRoot "requirements.txt"
    }
    "agent" {
        if (-not $CondaEnvName) { $CondaEnvName = "graphrag-c9-agent" }
        $RequirementsPath = Join-Path $RepositoryRoot "agent\requirements.txt"
        if (-not (Test-Path -LiteralPath $RequirementsPath)) {
            throw "Expected agent requirements file at $RequirementsPath."
        }
    }
    default {
        if (-not $CondaEnvName) { $CondaEnvName = "graphrag-c9-dev" }
        $RequirementsPath = Join-Path $RepositoryRoot "requirements-dev.txt"
    }
}

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

function Get-CondaEnvironmentPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$CondaCommand,
        [Parameter(Mandatory = $true)]
        [string]$EnvironmentName
    )

    $EnvJson = & $CondaCommand "env" "list" "--json" | Out-String
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to list conda environments."
    }
    $EnvInfo = $EnvJson | ConvertFrom-Json
    foreach ($EnvPath in $EnvInfo.envs) {
        if ((Split-Path -Leaf $EnvPath) -ieq $EnvironmentName) {
            return $EnvPath
        }
    }
    return ""
}

try {
    Get-Command conda -ErrorAction Stop | Out-Null
} catch {
    throw "Miniconda or Anaconda is required. Install it and make the conda command available."
}

$CondaCommand = "conda"
$CondaEnvPath = Get-CondaEnvironmentPath $CondaCommand $CondaEnvName
if (-not $CondaEnvPath) {
    Invoke-Checked $CondaCommand "create" "--yes" "--name" $CondaEnvName "python=3.11"
    $CondaEnvPath = Get-CondaEnvironmentPath $CondaCommand $CondaEnvName
}
if (-not $CondaEnvPath) {
    throw "Conda environment was not created: $CondaEnvName"
}

$Version = & $CondaCommand "run" "--name" $CondaEnvName "python" "-c" "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ($LASTEXITCODE -ne 0) {
    throw "Unable to run Python from conda environment $CondaEnvName."
}
if ($Version.Trim() -ne "3.11") {
    throw "Conda environment $CondaEnvName must use Python 3.11; found $Version"
}

Invoke-Checked $CondaCommand "run" "--name" $CondaEnvName "python" "-m" "pip" "install" "--upgrade" `
    "pip==26.1.1" "setuptools==80.9.0" "wheel==0.47.0"
if ($Profile -ne "agent") {
    Invoke-Checked $CondaCommand "run" "--name" $CondaEnvName "python" "-m" "pip" `
        "uninstall" "--yes" "jieba"
}
Invoke-Checked $CondaCommand "run" "--name" $CondaEnvName "python" "-m" "pip" "install" `
    "--requirement" $RequirementsPath

$Verifier = Join-Path $RepositoryRoot "scripts\verify_environment.py"
if ($Profile -eq "agent") {
    Invoke-Checked $CondaCommand "run" "--name" $CondaEnvName "python" $Verifier `
        "--expected-conda-env" $CondaEnvName "--skip-runtime-lock"
} else {
    Invoke-Checked $CondaCommand "run" "--name" $CondaEnvName "python" $Verifier `
        "--expected-conda-env" $CondaEnvName
}

Write-Output "[OK] $Profile conda environment ready: $CondaEnvName ($CondaEnvPath)"
