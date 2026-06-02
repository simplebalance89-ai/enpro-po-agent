# EnPro PO Agent — Local Windows Startup Script
# Run this in PowerShell to start the agent on the EnPro sandbox machine

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

# 2. Load .env into current process environment
if (Test-Path ".\.env") {
    Get-Content ".\.env" | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#")) {
            $parts = $line -split "=", 2
            if ($parts.Length -eq 2) {
                $key = $parts[0].Trim()
                $val = $parts[1].Trim()
                # Remove surrounding quotes if present
                if ($val.StartsWith('"') -and $val.EndsWith('"')) { $val = $val.Substring(1, $val.Length - 2) }
                [System.Environment]::SetEnvironmentVariable($key, $val, "Process")
            }
        }
    }
    Write-Host "Loaded .env into environment" -ForegroundColor Green
} else {
    Write-Host "WARNING: No .env file found." -ForegroundColor Yellow
}

# 3. Create data directories
$dirs = @(
    $env:CROSSWALK_DIR,
    $env:CISM_OUTPUT_DIR,
    $env:CISM_SO_OUTPUT_DIR,
    $env:CISM_BATCH_DIR,
    ".\data\po_store",
    ".\data\p21_data",
    ".\data\quote_data"
)
foreach ($d in $dirs) {
    if ($d -and -not (Test-Path $d)) {
        New-Item -ItemType Directory -Path $d -Force | Out-Null
        Write-Host "Created: $d" -ForegroundColor DarkGray
    }
}

# 4. Check dependencies
Write-Host "Checking dependencies..." -ForegroundColor Cyan
try {
    python -c "import fastapi, uvicorn, pydantic" 2>$null
    Write-Host "Core dependencies OK" -ForegroundColor Green
} catch {
    Write-Host "Installing dependencies..." -ForegroundColor Yellow
    pip install -r requirements.txt
}

# 5. Start server
Write-Host "" 
Write-Host "Starting server on http://localhost:8000" -ForegroundColor Cyan
Write-Host "- Health:     http://localhost:8000/health" -ForegroundColor DarkGray
Write-Host "- Portal:     http://localhost:8000/" -ForegroundColor DarkGray
Write-Host "- Review:     http://localhost:8000/review" -ForegroundColor DarkGray
Write-Host "- API Docs:   http://localhost:8000/docs" -ForegroundColor DarkGray
Write-Host ""
Write-Host "Press Ctrl+C to stop" -ForegroundColor Yellow
Write-Host "========================================" -ForegroundColor Cyan

$env:PYTHONPATH = "$PSScriptRoot;$env:PYTHONPATH"
uvicorn server:app --reload --host 0.0.0.0 --port 8000
