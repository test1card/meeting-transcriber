[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$InputFile,
    [string]$OutputDirectory,
    [string]$Glossary,
    [int]$NumSpeakers,
    [int]$MaxSpeakers = 8,
    [string]$JudgeModel = "gemma4:26b",
    [string]$SummaryModels = "gemma4:e4b,gemma4:26b",
    [string]$DeepSeekModels = "deepseek-v4-flash,deepseek-v4-pro",
    [switch]$NoDeepSeek
)

$ErrorActionPreference = "Stop"
$inputPath = (Resolve-Path -LiteralPath $InputFile).Path
$root = if ($OutputDirectory) {
    [System.IO.Path]::GetFullPath($OutputDirectory)
}
else {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    Join-Path $PSScriptRoot "outputs\full-benchmark-$stamp"
}
[System.IO.Directory]::CreateDirectory($root) | Out-Null

$whisper = Join-Path $root "whisperx"
$moss = Join-Path $root "moss"
$qwen = Join-Path $root "qwen"
$mossGlobal = Join-Path $root "moss-global"
$consensus = Join-Path $root "consensus"

if (-not (Test-Path -LiteralPath (Join-Path $whisper "transcript.json"))) {
    & (Join-Path $PSScriptRoot "run.ps1") $inputPath `
        -OutputDirectory $whisper -Language ru -NoDiarization -NoSummary
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

$mossComplete = $false
$mossTranscript = Join-Path $moss "transcript.json"
if (Test-Path -LiteralPath $mossTranscript) {
    $mossPayload = Get-Content -Raw -LiteralPath $mossTranscript | ConvertFrom-Json
    $mossComplete = [bool]$mossPayload.metadata.complete
}
if (-not $mossComplete) {
    $arguments = @{
        InputFile = $inputPath
        OutputDirectory = $moss
    }
    if ($Glossary) { $arguments.Glossary = $Glossary }
    & (Join-Path $PSScriptRoot "run-moss-checkpointed.ps1") @arguments
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

$qwenComplete = $false
$qwenTranscript = Join-Path $qwen "transcript.json"
if (Test-Path -LiteralPath $qwenTranscript) {
    $qwenPayload = Get-Content -Raw -LiteralPath $qwenTranscript | ConvertFrom-Json
    $qwenComplete = [bool]$qwenPayload.metadata.complete
}
if (-not $qwenComplete) {
    $arguments = @{
        InputFile = $inputPath
        OutputDirectory = $qwen
    }
    if ($Glossary) { $arguments.Glossary = $Glossary }
    & (Join-Path $PSScriptRoot "run-qwen-checkpointed.ps1") @arguments
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

$speakerArguments = @{
    MossTranscript = $mossTranscript
    AudioFile = $inputPath
    OutputDirectory = $mossGlobal
    MaxSpeakers = $MaxSpeakers
}
if ($NumSpeakers -gt 0) {
    $speakerArguments.NumSpeakers = $NumSpeakers
}
& (Join-Path $PSScriptRoot "run-speaker-clustering.ps1") @speakerArguments
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$consensusArguments = @{
    Transcripts = @(
        (Join-Path $mossGlobal "transcript.json"),
        $qwenTranscript,
        (Join-Path $whisper "transcript.json")
    )
    Labels = "moss,qwen,whisperx"
    Anchor = "moss"
    OutputDirectory = $consensus
    JudgeModel = $JudgeModel
    Models = $SummaryModels
    DeepSeekModels = $DeepSeekModels
}
if ($Glossary) { $consensusArguments.Glossary = $Glossary }
if ($NoDeepSeek) { $consensusArguments.NoDeepSeek = $true }
& (Join-Path $PSScriptRoot "consensus.ps1") @consensusArguments
exit $LASTEXITCODE
