[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$InputFile,

    [string]$OutputDirectory,

    [string]$Models = "gemma4:e4b,gemma4:26b",

    [string]$DeepSeekModels = "deepseek-v4-flash,deepseek-v4-pro",

    [ValidateSet("ollama", "openai", "vllm")]
    [string]$Provider = "ollama",

    [string]$BaseUrl = "http://127.0.0.1:11434",

    [string]$Language,

    [string]$SummaryLanguage = "Russian",

    [int]$MinSpeakers,

    [int]$MaxSpeakers,

    [switch]$NoDiarization,

    [switch]$NoDeepSeek,

    [switch]$NoSummary,

    [switch]$BridgeProbe
)

$ErrorActionPreference = "Stop"

function ConvertTo-Base64Utf8 {
    param([Parameter(Mandatory = $true)][string]$Value)
    return [Convert]::ToBase64String([Text.UTF8Encoding]::new($false).GetBytes($Value))
}

function ConvertTo-BashDecodedUtf8 {
    param([Parameter(Mandatory = $true)][string]$Value)
    return '"$(printf %s ''' + (ConvertTo-Base64Utf8 $Value) + ''' | base64 -d)"'
}

$distro = "Ubuntu-22.04"
$inputWindows = (Resolve-Path -LiteralPath $InputFile).Path
$runnerWindows = Join-Path $PSScriptRoot "scripts\run_wsl.sh"
$comparisonPython = Join-Path $PSScriptRoot ".venv-win\Scripts\python.exe"

if ($OutputDirectory) {
    $outputWindows = [System.IO.Path]::GetFullPath($OutputDirectory)
}
else {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $stem = [System.IO.Path]::GetFileNameWithoutExtension($inputWindows)
    $outputWindows = Join-Path $PSScriptRoot "outputs\$stem-$stamp"
}
[System.IO.Directory]::CreateDirectory($outputWindows) | Out-Null

if (-not $NoSummary -and $Provider -eq "ollama") {
    & (Join-Path $PSScriptRoot "scripts\Start-Ollama.ps1")
}

$cliArguments = @("--no-summary")
if ($Language) {
    $cliArguments += @("--language", $Language)
}
if ($MinSpeakers -gt 0) {
    $cliArguments += @("--min-speakers", [string]$MinSpeakers)
}
if ($MaxSpeakers -gt 0) {
    $cliArguments += @("--max-speakers", [string]$MaxSpeakers)
}
if ($NoDiarization) {
    $cliArguments += "--no-diarize"
}
if ($BridgeProbe) {
    $cliArguments += "--help"
}

$runnerExpression = ConvertTo-BashDecodedUtf8 $runnerWindows
$inputExpression = ConvertTo-BashDecodedUtf8 $inputWindows
$outputExpression = ConvertTo-BashDecodedUtf8 $outputWindows
$cliExpressions = @($cliArguments | ForEach-Object { ConvertTo-BashDecodedUtf8 ([string]$_) })
$wslScript = `
    'runner_win=' + $runnerExpression + '; ' + `
    'input_win=' + $inputExpression + '; ' + `
    'output_win=' + $outputExpression + '; ' + `
    'runner=$(wslpath -a "$runner_win"); ' + `
    'input=$(wslpath -a "$input_win"); ' + `
    'output=$(wslpath -a "$output_win"); ' + `
    'exec bash "$runner" "$input" --output "$output" ' + ($cliExpressions -join ' ')
$wslBootstrap = 'printf %s ' + (ConvertTo-Base64Utf8 $wslScript) + '|base64 -d|bash'

& wsl.exe -d $distro -- bash -lc $wslBootstrap
$transcriptionExit = $LASTEXITCODE
if ($transcriptionExit -ne 0 -or $NoSummary -or $BridgeProbe) {
    exit $transcriptionExit
}

$transcriptJson = Join-Path $outputWindows "transcript.json"
$comparisonArgs = @(
    "-m", "meeting_transcriber.compare_cli",
    $transcriptJson,
    "--output", $outputWindows,
    "--local-provider", $Provider,
    "--local-base-url", $BaseUrl,
    "--local-models", $Models,
    "--deepseek-models", $DeepSeekModels,
    "--summary-language", $SummaryLanguage
)
if ($NoDeepSeek) {
    $comparisonArgs += "--no-deepseek"
}
else {
    if ([string]::IsNullOrWhiteSpace($env:DEEPSEEK_API_KEY)) {
        throw "DeepSeek comparison requested, but DEEPSEEK_API_KEY is missing."
    }
    Write-Warning "DeepSeek comparison sends transcript text to the external DeepSeek API."
}

$env:PYTHONPATH = $PSScriptRoot
if (-not (Test-Path -LiteralPath $comparisonPython)) {
    throw "Missing Windows comparison environment. Run .\setup.ps1."
}
& $comparisonPython @comparisonArgs
exit $LASTEXITCODE
