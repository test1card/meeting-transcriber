param(
    [Parameter(Mandatory = $true)]
    [int]$ProcessId,
    [Parameter(Mandatory = $true)]
    [string]$LogPath,
    [int]$IntervalSeconds = 15
)

$ErrorActionPreference = "SilentlyContinue"
$started = Get-Date
"timestamp,status,cpu_seconds,working_set_mb,gpu_utilization,gpu_memory_mb" |
    Set-Content -LiteralPath $LogPath -Encoding utf8

while ($true) {
    $process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    $timestamp = (Get-Date).ToString("o")
    if (-not $process) {
        "$timestamp,finished,,,," |
            Add-Content -LiteralPath $LogPath -Encoding utf8
        break
    }
    $gpu = (
        nvidia-smi `
            --query-gpu=utilization.gpu,memory.used `
            --format=csv,noheader,nounits
    ).Trim() -split ","
    $utilization = if ($gpu.Count -ge 1) { $gpu[0].Trim() } else { "" }
    $memory = if ($gpu.Count -ge 2) { $gpu[1].Trim() } else { "" }
    $workingSetMb = [math]::Round($process.WorkingSet64 / 1MB, 1)
    "$timestamp,running,$($process.CPU),$workingSetMb,$utilization,$memory" |
        Add-Content -LiteralPath $LogPath -Encoding utf8
    Start-Sleep -Seconds $IntervalSeconds
}
