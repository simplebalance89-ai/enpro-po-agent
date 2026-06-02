# EnPro PO Agent — Local Windows Startup Script
# Run this from the repo root in PowerShell

$ErrorActionPreference = "Stop"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  EnPro PO Agent — Local Sandbox Mode" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# 1. Check Python
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
    Write-Host "ERROR: Python not found in PATH." -ForegroundColor Red
    exit 1
}
Write-Host "Python found: $($py.Source)" -ForegroundColor Green

# 2. Create data directories
$dirs = @(
    "data\crosswalks",
    "data\cism_output",
    "data\cism_so_output",
    "data\cism_batch",
    "data\po_store",
    "data\p21_data",
    "data\quote_data",
    "data\invoices"
)
foreach ($d in $dirs) {
    if (-not (Test-Path $d)) {
        New-Item -ItemType Directory -Path $d -Force | Out-Null
        Write-Host "Created: $d" -ForegroundColor DarkGray
    }
}

# 3. Check dependencies
Write-Host "Checking dependencies..." -ForegroundColor Cyan
try {
    python -c "import fastapi, uvicorn, pydantic" 2>$null
    Write-Host "Core dependencies OK" -ForegroundColor Green
} catch {
    Write-Host "Installing dependencies..." -ForegroundColor Yellow
    pip install -r requirements.txt
}

# 4. Start server
Write-Host "" 
Write-Host "Starting server on http://localhost:8001" -ForegroundColor Cyan
Write-Host "- Health:     http://localhost:8001/health" -ForegroundColor DarkGray
Write-Host "- Portal:     http://localhost:8001/" -ForegroundColor DarkGray
Write-Host "- Test Drive: http://localhost:8001/test-drive" -ForegroundColor DarkGray
Write-Host "- API Docs:   http://localhost:8001/docs" -ForegroundColor DarkGray
Write-Host ""
Write-Host "Press Ctrl+C to stop" -ForegroundColor Yellow
Write-Host "========================================" -ForegroundColor Cyan

$env:PYTHONPATH = "$PWD\src;$env:PYTHONPATH"
uvicorn src.server:app --reload --host 0.0.0.0 --port 8001
