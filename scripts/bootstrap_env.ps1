param(
    [ValidateSet("dev", "runtime", "agent")]
    [string]$Profile = "dev",
    [string]$VenvPath = ""
)

$ErrorActionPreference = "Stop"
$RepositoryRoot = Split-Path -Parent $PSScriptRoot

switch ($Profile) {
    "runtime" {
        if (-not $VenvPath) { $VenvPath = Join-Path $RepositoryRoot ".venv-runtime" }
        $RequirementsPath = Join-Path $RepositoryRoot "requirements.txt"
    }
    "agent" {
        if (-not $VenvPath) { $VenvPath = Join-Path $RepositoryRoot ".venv-agent" }
        # Discover the legacy agent directory to keep this script safe for
        # Windows PowerShell 5.1 ANSI source decoding.
        $AgentRequirements = @(
            Get-ChildItem -LiteralPath $RepositoryRoot -Directory -Filter "agent(*)" |
                ForEach-Object { Join-Path $_.FullName "requirements.txt" } |
                Where-Object { Test-Path -LiteralPath $_ }
        )
        if ($AgentRequirements.Count -ne 1) {
            throw "Expected exactly one agent requirements file matching agent(*)\requirements.txt under $RepositoryRoot; found $($AgentRequirements.Count)."
        }
        $RequirementsPath = $AgentRequirements[0]
    }
    default {
        if (-not $VenvPath) { $VenvPath = Join-Path $RepositoryRoot ".venv" }
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

$BasePython = (Get-Command python -ErrorAction Stop).Source
$Version = & $BasePython -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ($Version.Trim() -ne "3.11") {
    throw "Python 3.11 is required; found $Version at $BasePython"
}

if (-not (Test-Path -LiteralPath $VenvPath)) {
    Invoke-Checked $BasePython "-m" "venv" $VenvPath
}

$VenvPython = Join-Path $VenvPath "Scripts\python.exe"
if (-not (Test-Path -LiteralPath $VenvPython)) {
    throw "Virtual environment Python was not created at $VenvPython"
}
$VenvVersion = & $VenvPython -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ($VenvVersion.Trim() -ne "3.11") {
    throw "Existing virtual environment must use Python 3.11; found $VenvVersion at $VenvPython"
}

Invoke-Checked $VenvPython "-m" "pip" "install" "--upgrade" `
    "pip==26.1.1" "setuptools==80.9.0" "wheel==0.47.0"
Invoke-Checked $VenvPython "-m" "pip" "install" "--requirement" $RequirementsPath

$Verifier = Join-Path $RepositoryRoot "scripts\verify_environment.py"
if ($Profile -eq "agent") {
    Invoke-Checked $VenvPython $Verifier "--expected-venv" $VenvPath "--skip-runtime-lock"
} else {
    Invoke-Checked $VenvPython $Verifier "--expected-venv" $VenvPath
}

Write-Output "[OK] $Profile environment ready at $VenvPath"
