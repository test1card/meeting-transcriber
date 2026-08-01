[CmdletBinding()]
param(
    [string]$CatalogPath,
    [string]$RuntimeRoot,
    [string]$StatePath
)

$ErrorActionPreference = "Stop"
Import-Module (Join-Path $PSScriptRoot "Workstation.Common.psm1") -Force
if (-not $CatalogPath) {
    $CatalogPath = Join-Path $PSScriptRoot "model-catalog.json"
}
if (-not $RuntimeRoot) {
    $RuntimeRoot = Get-DefaultRuntimeRoot
}
if (-not $StatePath) {
    $StatePath = Get-DefaultStatePath
}

try {
    $status = Get-WorkstationStatus `
        -CatalogPath $CatalogPath `
        -RuntimeRoot $RuntimeRoot `
        -StatePath $StatePath
    [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
    $status | ConvertTo-Json -Depth 20 -Compress
}
catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
