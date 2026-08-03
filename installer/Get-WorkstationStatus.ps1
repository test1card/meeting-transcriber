[CmdletBinding()]
param(
    [string]$CatalogPath,
    [string]$RuntimeRoot,
    [string]$StatePath
)

$ErrorActionPreference = "Stop"
$OutputEncoding = [Text.UTF8Encoding]::new($false)
$scriptRoot = $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($scriptRoot)) {
    $scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Definition
}
if ([string]::IsNullOrWhiteSpace($scriptRoot)) {
    throw "Не удалось определить каталог установщика PowerShell."
}
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
Import-Module (Join-Path $scriptRoot "Workstation.Common.psm1") -Force
if ([string]::IsNullOrWhiteSpace($CatalogPath)) {
    $CatalogPath = Join-Path $scriptRoot "model-catalog.json"
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
