[CmdletBinding()]
param(
    [string]$CatalogPath,
    [string]$RuntimeRoot,
    [string]$StatePath
)

$ErrorActionPreference = "Stop"
$OutputEncoding = [Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
Import-Module (Join-Path $PSScriptRoot "Workstation.Common.psm1") -Force
if ([string]::IsNullOrWhiteSpace($CatalogPath)) {
    $CatalogPath = Join-Path $PSScriptRoot "model-catalog.json"
}
if ([string]::IsNullOrWhiteSpace($RuntimeRoot)) {
    $RuntimeRoot = Get-DefaultRuntimeRoot
}
if ([string]::IsNullOrWhiteSpace($StatePath)) {
    $StatePath = Get-DefaultStatePath
}

try {
    $status = Get-WorkstationStatus `
        -CatalogPath $CatalogPath `
        -RuntimeRoot $RuntimeRoot `
        -StatePath $StatePath
    $status | ConvertTo-Json -Depth 20 -Compress
}
catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
