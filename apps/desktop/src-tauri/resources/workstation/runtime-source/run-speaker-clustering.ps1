[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$MossTranscript,
    [Parameter(Mandatory = $true)]
    [string]$AudioFile,
    [Parameter(Mandatory = $true)]
    [string]$OutputDirectory,
    [int]$NumSpeakers,
    [int]$MaxSpeakers = 8
)

$ErrorActionPreference = "Stop"
$python = Join-Path $PSScriptRoot ".venv-qwen\Scripts\python.exe"
$arguments = @(
    (Join-Path $PSScriptRoot "scripts\cluster_moss_speakers.py"),
    (Resolve-Path -LiteralPath $MossTranscript).Path,
    (Resolve-Path -LiteralPath $AudioFile).Path,
    "--output", [System.IO.Path]::GetFullPath($OutputDirectory),
    "--max-speakers", $MaxSpeakers
)
if ($NumSpeakers -gt 0) {
    $arguments += @("--num-speakers", $NumSpeakers)
}
& $python @arguments
exit $LASTEXITCODE
