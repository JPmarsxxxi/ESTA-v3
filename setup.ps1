# ESTA-v2 one-time environment setup
# Run this once before using any audio/timestamps/render skills.
# Usage: .\setup.ps1

$envName = "esta"

Write-Host "Checking for conda..." -ForegroundColor Cyan
if (-not (Get-Command conda -ErrorAction SilentlyContinue)) {
    Write-Host "ERROR: conda not found. Install Miniconda from https://docs.conda.io/en/latest/miniconda.html then re-run this script." -ForegroundColor Red
    exit 1
}

Write-Host "Checking for '$envName' environment..." -ForegroundColor Cyan
$envExists = conda env list 2>$null | Select-String "^$envName\s"

if ($envExists) {
    Write-Host "Environment '$envName' already exists. Updating from environment.yml..." -ForegroundColor Yellow
    conda env update -n $envName -f environment.yml --prune
} else {
    Write-Host "Creating '$envName' environment from environment.yml (this takes a few minutes)..." -ForegroundColor Cyan
    conda env create -f environment.yml
}

if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Environment setup failed. Check the output above." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Done. The 'esta' env is ready." -ForegroundColor Green
Write-Host "You don't need to activate it — skills call 'conda run -n esta' automatically." -ForegroundColor Green
