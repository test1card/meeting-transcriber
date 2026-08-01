[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$InputFile,
    [Parameter(Mandatory = $true)]
    [string]$OutputDirectory,
    [string]$Glossary,
    [int]$MaxNewTokens = 32768
)

$ErrorActionPreference = "Stop"
$python = Join-Path $PSScriptRoot ".venv-moss\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Missing MOSS environment."
}
$arguments = @(
    (Join-Path $PSScriptRoot "scripts\transcribe_moss.py"),
    (Resolve-Path -LiteralPath $InputFile).Path,
    "--output", [System.IO.Path]::GetFullPath($OutputDirectory),
    "--max-new-tokens", $MaxNewTokens
)
if ($Glossary) {
    $arguments += @("--glossary", (Resolve-Path -LiteralPath $Glossary).Path)
}
& $python @arguments
exit $LASTEXITCODE
