#requires -Modules Az.Storage
<#
.SYNOPSIS
    Push P21/crosswalk CSVs from the local machine to Azure Blob.

.DESCRIPTION
    Companion to pull_cism_from_blob.ps1. This is the INBOUND side of the
    pipeline:

        P21 SQL  -->  local CSV dump  -->  Azure Blob  -->  Render service

    Run this on the machine that has SQL / file-system access to the refreshed
    CSVs (the EnPro Vega box). Schedule it via Task Scheduler to run after
    whatever job refreshes the CSVs from P21 (daily, hourly, whatever fits).

    After upload, optionally pings the Render service so it re-syncs + rebuilds
    the crosswalks immediately instead of waiting for a restart.

.PARAMETER SourceDir
    Folder containing the refreshed CSVs. Defaults to:
      C:\Claude\Work\EnPro\Ariba_Coupa\data

.PARAMETER StorageAccountName
    Azure Storage Account name (default: enproaidatav1)

.PARAMETER ContainerName
    Blob container name (default: crosswalk)

.PARAMETER StorageAccountKey
    Storage account key. Defaults to $env:AZURE_STORAGE_KEY.

.PARAMETER RenderSyncUrl
    If set, POSTed after upload to trigger Render to pull the fresh blobs
    and rebuild crosswalks. Example:
      https://enpro-po-agent.onrender.com/api/v1/crosswalk/sync-from-blob?rebuild=true

.PARAMETER LogPath
    Path to log file. Defaults to C:\P21\CISM\Logs\blob_push.log.
#>

param(
    [string]$SourceDir          = "C:\Claude\Work\EnPro\Ariba_Coupa\data",
    [string]$StorageAccountName = "enproaidatav1",
    [string]$ContainerName      = "crosswalk",
    [string]$StorageAccountKey  = $env:AZURE_STORAGE_KEY,
    [string]$RenderSyncUrl      = "https://enpro-po-agent.onrender.com/api/v1/crosswalk/sync-from-blob?rebuild=true",
    [string]$LogPath            = "C:\P21\CISM\Logs\blob_push.log"
)

$ErrorActionPreference = "Stop"

# Ensure log directory exists
$LogDir = Split-Path $LogPath -Parent
if ($LogDir -and -not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

function Write-Log {
    param([string]$Message, [string]$Level = "INFO")
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') | $Level | $Message"
    Add-Content -Path $LogPath -Value $line
    Write-Host $line
}

Write-Log "=== Crosswalk Blob Push Started ==="
Write-Log "Source:    $SourceDir"
Write-Log "Account:   $StorageAccountName"
Write-Log "Container: $ContainerName"

# Local filename  ->  blob path inside the container
# The Render service's sync_crosswalks_from_blob expects everything under
# the 'crosswalk/' prefix. Since the container itself is named 'crosswalk',
# we nest one level (crosswalk/p21/, crosswalk/quotes/, etc.) so that the
# matching prefix inside the container is literally 'crosswalk/'.
$FileMap = @{
    "PO Portal SO Header.csv"          = "crosswalk/p21/so_headers_latest.csv"
    "PO Portal SO Lines.csv"           = "crosswalk/p21/so_lines_latest.csv"
    "PO Portal Customers.csv"          = "crosswalk/p21/customers_latest.csv"
    "PO Portal Customers Ship-To.csv"  = "crosswalk/p21/ship_tos_latest.csv"
    "PO Portal Customer Defaults.csv"  = "crosswalk/p21/customer_defaults_latest.csv"
    "PO Portal Salespeople.csv"        = "crosswalk/p21/salespeople_latest.csv"
    "PO Portal Quotes.csv"             = "crosswalk/quotes/quotes_latest.csv"
    "dynamics_quotes_active.csv"       = "crosswalk/quotes/dynamics_active_latest.csv"
}

# ── Azure connection ─────────────────────────────────────────────────────────

try {
    if (-not $StorageAccountKey) {
        Write-Log "No -StorageAccountKey and `$env:AZURE_STORAGE_KEY not set." "ERROR"
        exit 2
    }
    $ctx = New-AzStorageContext -StorageAccountName $StorageAccountName -StorageAccountKey $StorageAccountKey
    # Verify container exists
    $null = Get-AzStorageContainer -Name $ContainerName -Context $ctx
    Write-Log "Connected and verified container '$ContainerName' exists"
} catch {
    Write-Log "Azure connection/container check failed: $_" "ERROR"
    exit 3
}

# ── Upload loop ──────────────────────────────────────────────────────────────

$uploaded = 0
$missing  = 0
$failed   = 0

foreach ($entry in $FileMap.GetEnumerator()) {
    $fileName = $entry.Key
    $blobName = $entry.Value
    $localPath = Join-Path $SourceDir $fileName

    if (-not (Test-Path $localPath)) {
        Write-Log "Missing local file, skipping: $fileName" "WARN"
        $missing++
        continue
    }

    try {
        $size = (Get-Item $localPath).Length
        Write-Log "Uploading $fileName ($size bytes) -> $blobName"
        Set-AzStorageBlobContent `
            -File $localPath `
            -Container $ContainerName `
            -Blob $blobName `
            -Context $ctx `
            -Force | Out-Null
        $uploaded++
    } catch {
        Write-Log "Upload failed for $fileName : $_" "ERROR"
        $failed++
    }
}

Write-Log "Upload summary: uploaded=$uploaded missing=$missing failed=$failed"

# ── Ping Render to sync + rebuild ────────────────────────────────────────────

if ($RenderSyncUrl -and $uploaded -gt 0) {
    try {
        Write-Log "Pinging Render: $RenderSyncUrl"
        $resp = Invoke-RestMethod -Method Post -Uri $RenderSyncUrl -TimeoutSec 60
        $dlCount = if ($resp.downloaded) { $resp.downloaded.Count } else { 0 }
        $errCount = if ($resp.errors) { $resp.errors.Count } else { 0 }
        Write-Log "Render sync: downloaded=$dlCount errors=$errCount build=$($resp.build)"
        if ($errCount -gt 0) {
            foreach ($e in $resp.errors) { Write-Log "  $e" "WARN" }
        }
    } catch {
        Write-Log "Render sync ping failed: $_" "WARN"
    }
}

Write-Log "=== Crosswalk Blob Push Completed ==="
exit $failed
