[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$InputFile,
    [Parameter(Mandatory = $true)]
    [string]$OutputDirectory,
    [string]$Glossary,
    [int]$ChunkSeconds = 600,
    [int]$MaxNewTokens = 8192
)

$ErrorActionPreference = "Stop"
$python = Join-Path $PSScriptRoot ".venv-moss\Scripts\python.exe"
$arguments = @(
    (Join-Path $PSScriptRoot "scripts\transcribe_moss_chunked.py"),
    (Resolve-Path -LiteralPath $InputFile).Path,
    "--output", [System.IO.Path]::GetFullPath($OutputDirectory),
    "--chunk-seconds", $ChunkSeconds,
    "--max-new-tokens", $MaxNewTokens
)
if ($Glossary) {
    $arguments += @("--glossary", (Resolve-Path -LiteralPath $Glossary).Path)
}
& $python @arguments
exit $LASTEXITCODE
