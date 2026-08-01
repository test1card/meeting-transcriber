[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string[]]$Transcripts,
    [string]$Labels,
    [string]$Anchor,
    [string]$OutputDirectory,
    [ValidateSet("ollama", "openai", "vllm", "deepseek")]
    [string]$JudgeProvider = "ollama",
    [string]$JudgeBaseUrl = "http://127.0.0.1:11434",
    [string]$JudgeModel = "gemma4:26b",
    [string]$Glossary,
    [string]$Models = "gemma4:e4b,gemma4:26b",
    [string]$DeepSeekModels = "deepseek-v4-flash,deepseek-v4-pro",
    [switch]$NoDeepSeek,
    [switch]$NoSummary
)

$ErrorActionPreference = "Stop"
$python = Join-Path $PSScriptRoot ".venv-win\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Missing Windows environment. Run .\setup.ps1 first."
}

$resolvedTranscripts = @(
    foreach ($transcript in $Transcripts) {
        (Resolve-Path -LiteralPath $transcript).Path
    }
)
if ($resolvedTranscripts.Count -lt 2) {
    throw "Provide at least two STT transcript JSON files."
}

if (-not $Labels) {
    $Labels = (
        $resolvedTranscripts |
            ForEach-Object { [System.IO.Path]::GetFileNameWithoutExtension($_) }
    ) -join ","
}
if (-not $Anchor) {
    $Anchor = ($Labels -split ",")[0].Trim()
}
if ($OutputDirectory) {
    $output = [System.IO.Path]::GetFullPath($OutputDirectory)
}
else {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $output = Join-Path $PSScriptRoot "outputs\consensus-$stamp"
}
[System.IO.Directory]::CreateDirectory($output) | Out-Null

if ($JudgeProvider -eq "ollama") {
    & (Join-Path $PSScriptRoot "scripts\Start-Ollama.ps1")
}

$env:PYTHONPATH = $PSScriptRoot
$consensusArgs = @(
    "-m", "meeting_transcriber.consensus_cli"
) + $resolvedTranscripts + @(
    "--labels", $Labels,
    "--anchor", $Anchor,
    "--output", $output,
    "--provider", $JudgeProvider,
    "--base-url", $JudgeBaseUrl,
    "--model", $JudgeModel,
    "--language", "ru"
)
if ($Glossary) {
    $consensusArgs += @("--glossary", (Resolve-Path -LiteralPath $Glossary).Path)
}

& $python @consensusArgs
if ($LASTEXITCODE -ne 0 -or $NoSummary) {
    exit $LASTEXITCODE
}

$comparisonArgs = @(
    "-m", "meeting_transcriber.compare_cli",
    (Join-Path $output "transcript.json"),
    "--output", $output,
    "--local-provider", "ollama",
    "--local-base-url", "http://127.0.0.1:11434",
    "--local-models", $Models,
    "--deepseek-models", $DeepSeekModels,
    "--summary-language", "Russian"
)
if ($NoDeepSeek) {
    $comparisonArgs += "--no-deepseek"
}
else {
    if ([string]::IsNullOrWhiteSpace($env:DEEPSEEK_API_KEY)) {
        throw "DeepSeek comparison requested, but DEEPSEEK_API_KEY is missing."
    }
    Write-Warning "DeepSeek comparison sends the consensus transcript text externally."
}

& $python @comparisonArgs
exit $LASTEXITCODE
