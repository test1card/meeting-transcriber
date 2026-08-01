[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$InputFile,
    [Parameter(Mandatory = $true)]
    [string]$OutputDirectory,
    [string]$Glossary,
    [int]$ChunkSeconds = 240
)

$ErrorActionPreference = "Stop"
$python = Join-Path $PSScriptRoot ".venv-qwen\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Missing Qwen environment."
}
$arguments = @(
    (Join-Path $PSScriptRoot "scripts\transcribe_qwen.py"),
    (Resolve-Path -LiteralPath $InputFile).Path,
    "--output", [System.IO.Path]::GetFullPath($OutputDirectory),
    "--chunk-seconds", $ChunkSeconds
)
if ($Glossary) {
    $arguments += @("--glossary", (Resolve-Path -LiteralPath $Glossary).Path)
}
& $python @arguments
exit $LASTEXITCODE
