[CmdletBinding()]
param(
    [ValidateSet("Plan", "Install", "Verify")]
    [string]$Action = "Plan",
    [string]$PackId = "deepseek-production",
    [string[]]$ModelIds = @(),
    [string]$CatalogPath,
    [string]$RuntimeRoot,
    [string]$StatePath,
    [string]$SourceRoot,
    [string]$AppExecutable,
    [string]$ExpectedUserSid,
    [switch]$NoElevation
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$OutputEncoding = [Text.UTF8Encoding]::new($false)
$scriptRoot = $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($scriptRoot)) {
    $scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Definition
}
if ([string]::IsNullOrWhiteSpace($scriptRoot)) {
    throw "Не удалось определить каталог установщика PowerShell."
}
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)

if ([string]::IsNullOrWhiteSpace($CatalogPath)) {
    $CatalogPath = Join-Path $scriptRoot "model-catalog.json"
}
Import-Module (Join-Path $scriptRoot "Workstation.Common.psm1") -Force
$currentUserSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
if ([string]::IsNullOrWhiteSpace($ExpectedUserSid)) {
    $ExpectedUserSid = $currentUserSid
}
elseif ($currentUserSid -ne $ExpectedUserSid) {
    $sidMismatch = $true
}
else {
    $sidMismatch = $false
}

if ([string]::IsNullOrWhiteSpace($RuntimeRoot)) {
    $RuntimeRoot = Get-DefaultRuntimeRoot
}
if ([string]::IsNullOrWhiteSpace($StatePath)) {
    $StatePath = Get-DefaultStatePath
}
if ([string]::IsNullOrWhiteSpace($SourceRoot)) {
    $SourceRoot = Split-Path -Parent $scriptRoot
}

$catalog = Get-Content -Raw -Encoding UTF8 -LiteralPath $CatalogPath | ConvertFrom-Json
$pack = $catalog.packs | Where-Object id -eq $PackId | Select-Object -First 1
if (-not $pack) {
    throw "Unknown model pack: $PackId"
}

$requestedModelIds = @(
    foreach ($value in $ModelIds) {
        @([string]$value -split ",") |
            ForEach-Object { $_.Trim() } |
            Where-Object { $_ }
    }
)

$selectedIds = [Collections.Generic.List[string]]::new()
foreach ($id in @($pack.required_model_ids) + @($requestedModelIds)) {
    if ($id -and -not $selectedIds.Contains([string]$id)) {
        $selectedIds.Add([string]$id)
    }
}
$selectedModels = @(
    foreach ($id in $selectedIds) {
        $model = $catalog.models | Where-Object id -eq $id | Select-Object -First 1
        if (-not $model) {
            throw "Unknown model id: $id"
        }
        $allowed = @($pack.required_model_ids) -contains $id
        $allowed = $allowed -or (@($pack.optional_model_ids) -contains $id)
        $allowed = $allowed -or [bool]$model.selectable
        if (-not $allowed) {
            throw "Model is not selectable for this setup: $id"
        }
        $model
    }
)

$estimatedDownload = [Math]::Round(
    (@($selectedModels | Measure-Object download_gb -Sum).Sum),
    1
)
$hardware = Get-HardwareProfile -RuntimeRoot $RuntimeRoot
$plan = [pscustomobject]@{
    schema_version = 2
    action = $Action
    pack_id = $PackId
    pack_label = $pack.label
    selected_model_ids = @($selectedIds)
    estimated_model_download_gb = $estimatedDownload
    estimated_total_installed_gb = [double]$pack.estimated_installed_gb
    runtime_root = $RuntimeRoot
    source_root = $SourceRoot
    state_path = $StatePath
    hardware = $hardware
}

if ($Action -eq "Plan") {
    [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
    $plan | ConvertTo-Json -Depth 12 -Compress
    exit 0
}

function Test-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Quote-ProcessArgument {
    param([string]$Value)
    return '"' + ($Value -replace '"', '\"') + '"'
}

function Start-ElevatedCopy {
    $arguments = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", (Quote-ProcessArgument $PSCommandPath),
        "-Action", "Install",
        "-PackId", (Quote-ProcessArgument $PackId),
        "-CatalogPath", (Quote-ProcessArgument $CatalogPath),
        "-RuntimeRoot", (Quote-ProcessArgument $RuntimeRoot),
        "-StatePath", (Quote-ProcessArgument $StatePath),
        "-SourceRoot", (Quote-ProcessArgument $SourceRoot),
        "-ExpectedUserSid", (Quote-ProcessArgument $ExpectedUserSid)
    )
    if ($selectedIds.Count) {
        $arguments += @("-ModelIds", (Quote-ProcessArgument (@($selectedIds) -join ",")))
    }
    if ($AppExecutable) {
        $arguments += @("-AppExecutable", (Quote-ProcessArgument $AppExecutable))
    }
    Start-Process `
        -FilePath "powershell.exe" `
        -Verb RunAs `
        -WindowStyle Hidden `
        -ArgumentList ($arguments -join " ") | Out-Null
}

$modelResults = [ordered]@{}
$modelFailures = [Collections.Generic.List[object]]::new()

function Set-ModelResult {
    param(
        [Parameter(Mandatory)]$Model,
        [Parameter(Mandatory)][string]$Status,
        [string]$Detail = ""
    )
    $modelResults[[string]$Model.id] = [pscustomobject]@{
        id = [string]$Model.id
        label = [string]$Model.display_name
        required = @($pack.required_model_ids) -contains [string]$Model.id
        status = $Status
        detail = $Detail
    }
}
function New-State {
    param(
        [string]$Status,
        [string]$Stage,
        [double]$Progress,
        [string]$Message,
        [bool]$RebootRequired = $false,
        $ErrorValue = $null
    )
    return [pscustomobject]@{
        schema_version = 1
        status = $Status
        stage = $Stage
        progress = $Progress
        message = $Message
        reboot_required = $RebootRequired
        error = $ErrorValue
        model_results = @($modelResults.Values)
        pack_id = $PackId
        selected_model_ids = @($selectedIds)
        runtime_root = $RuntimeRoot
        log_path = (Join-Path (Split-Path -Parent $StatePath) "setup.log")
        updated_at = [DateTimeOffset]::Now.ToString("o")
    }
}

function Update-State {
    param(
        [string]$Stage,
        [double]$Progress,
        [string]$Message,
        [string]$Status = "RUNNING",
        [bool]$RebootRequired = $false,
        $ErrorValue = $null
    )
    $state = New-State `
        -Status $Status `
        -Stage $Stage `
        -Progress $Progress `
        -Message $Message `
        -RebootRequired $RebootRequired `
        -ErrorValue $ErrorValue
    Write-JsonAtomic -Path $StatePath -Value $state
    $stamp = [DateTimeOffset]::Now.ToString("yyyy-MM-dd HH:mm:ss")
    Add-Content `
        -LiteralPath $state.log_path `
        -Encoding UTF8 `
        -Value "[$stamp] [$Stage] $Message"
}

function Update-ProcessPath {
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machine;$user"
}

function Ensure-WingetPackage {
    param(
        [Parameter(Mandatory)][string]$CommandName,
        [Parameter(Mandatory)][string]$PackageId
    )
    Update-ProcessPath
    if (Test-Command $CommandName) {
        return
    }
    if (-not (Test-Command "winget.exe")) {
        throw "Не найден $CommandName и недоступен winget. Установите Windows App Installer (winget), FFmpeg/uv/Ollama вручную, затем повторите запуск."
    }
    $stdout = Join-Path ([IO.Path]::GetTempPath()) ("meeting-documents-winget-" + [Guid]::NewGuid().ToString("N") + ".out")
    $stderr = Join-Path ([IO.Path]::GetTempPath()) ("meeting-documents-winget-" + [Guid]::NewGuid().ToString("N") + ".err")
    try {
        $arguments = @("install", "--id", $PackageId, "--exact", "--silent", "--accept-source-agreements", "--accept-package-agreements", "--disable-interactivity")
        $process = Start-Process -FilePath "winget.exe" -ArgumentList $arguments -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
        if ($process.ExitCode -ne 0) {
            $detail = if (Test-Path -LiteralPath $stderr) { (Get-Content -Raw -LiteralPath $stderr -ErrorAction SilentlyContinue).Trim() } else { "" }
            if ([string]::IsNullOrWhiteSpace($detail) -and (Test-Path -LiteralPath $stdout)) { $detail = (Get-Content -Raw -LiteralPath $stdout -ErrorAction SilentlyContinue).Trim() }
            throw "winget не смог установить $PackageId (код $($process.ExitCode)). $detail"
        }
    }
    finally {
        Remove-Item -LiteralPath $stdout,$stderr -Force -ErrorAction SilentlyContinue
    }
    Update-ProcessPath
    if (-not (Test-Command $CommandName)) {
        throw "Пакет $PackageId установлен, но команда $CommandName не найдена в PATH. Перезапустите приложение или добавьте каталог программы в PATH."
    }
}

function Resolve-Uv {
    Update-ProcessPath
    $command = Get-Command "uv.exe" -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    $fallback = $null
    if (-not [string]::IsNullOrWhiteSpace($env:USERPROFILE)) {
        $fallback = Join-Path $env:USERPROFILE ".local\bin\uv.exe"
    }
    if ($fallback -and (Test-Path -LiteralPath $fallback)) { return $fallback }
    throw "uv.exe was installed but cannot be found."
}

function Copy-RuntimeSource {
    New-Item -ItemType Directory -Path $RuntimeRoot -Force | Out-Null
    $directories = @(
        "meeting_transcriber",
        "scripts",
        "vendor\MOSS-Transcribe-Diarize"
    )
    foreach ($relative in $directories) {
        $source = Join-Path $SourceRoot $relative
        if (-not (Test-Path -LiteralPath $source)) {
            throw "Bundled runtime source is missing: $source"
        }
        $target = Join-Path $RuntimeRoot $relative
        New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
        Copy-Item -LiteralPath $source -Destination $target -Recurse -Force
    }
    $files = @(
        "run.ps1",
        "run-moss-checkpointed.ps1",
        "run-qwen-checkpointed.ps1",
        "run-speaker-clustering.ps1"
    )
    foreach ($relative in $files) {
        $source = Join-Path $SourceRoot $relative
        if (-not (Test-Path -LiteralPath $source)) {
            throw "Bundled runtime file is missing: $source"
        }
        Copy-Item -LiteralPath $source -Destination (Join-Path $RuntimeRoot $relative) -Force
    }
    Copy-Item -LiteralPath $CatalogPath -Destination (Join-Path $RuntimeRoot "model-catalog.json") -Force
}

function Ensure-Venv {
    param(
        [Parameter(Mandatory)][string]$Uv,
        [Parameter(Mandatory)][string]$Name
    )
    $path = Join-Path $RuntimeRoot $Name
    $python = Join-Path $path "Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $python)) {
        & $Uv venv $path --python 3.12
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to create $Name."
        }
    }
    return $python
}

function Invoke-UvInstall {
    param(
        [Parameter(Mandatory)][string]$Uv,
        [Parameter(Mandatory)][string]$Python,
        [Parameter(Mandatory)][string[]]$Packages,
        [string]$IndexUrl
    )
    $arguments = @("pip", "install", "--python", $Python)
    if ($IndexUrl) {
        $arguments += @("--index-url", $IndexUrl)
    }
    $arguments += $Packages
    & $Uv @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Python package installation failed for $Python."
    }
}

function Ensure-Wsl {
    if (-not (Test-Command "wsl.exe")) {
        try {
            Enable-WindowsOptionalFeature -Online -FeatureName @("Microsoft-Windows-Subsystem-Linux", "VirtualMachinePlatform") -All -NoRestart -ErrorAction Stop | Out-Null
        }
        catch {
            throw "Не удалось включить компоненты WSL2. Запустите установщик от администратора и проверьте, что виртуализация включена в BIOS/UEFI."
        }
        Update-ProcessPath
    }
    if (-not (Test-Command "wsl.exe")) {
        return $false
    }
    $profile = Get-HardwareProfile -RuntimeRoot $RuntimeRoot
    if ($profile.wsl.distro_ready) {
        & wsl.exe -d Ubuntu-22.04 -- true 2>$null
        return ($LASTEXITCODE -eq 0)
    }
    & wsl.exe --install -d Ubuntu-22.04 --no-launch --web-download
    $code = $LASTEXITCODE
    if ($code -ne 0 -and $code -ne 3010) {
        throw "Не удалось установить WSL2/Ubuntu-22.04 (код $code). Включите виртуализацию и компонент WSL в Windows, затем повторите запуск."
    }
    $profile = Get-HardwareProfile -RuntimeRoot $RuntimeRoot
    if (-not $profile.wsl.distro_ready) {
        return $false
    }
    & wsl.exe -d Ubuntu-22.04 -- true 2>$null
    return ($LASTEXITCODE -eq 0)
}
function Register-ResumeAfterReboot {
    if (-not $AppExecutable) {
        return
    }
    $command = '"' + $AppExecutable + '"'
    New-ItemProperty `
        -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce" `
        -Name "MeetingDocumentsSetup" `
        -Value $command `
        -PropertyType String `
        -Force | Out-Null
}

function Ensure-WslRuntime {
    & wsl.exe -d Ubuntu-22.04 -u root -- bash -lc `
        "apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y ffmpeg python3-venv python3-pip"
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install WSL system packages."
    }
    & wsl.exe -d Ubuntu-22.04 -u root -- bash -lc `
        "python3 -m venv /opt/meeting-documents/venv && /opt/meeting-documents/venv/bin/python -m pip install --upgrade pip setuptools wheel && /opt/meeting-documents/venv/bin/python -m pip install whisperx==3.8.6 'httpx>=0.28,<1' 'python-dotenv>=1.2,<2'"
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create the WSL WhisperX runtime."
    }
}

function Write-ModelMarker {
    param([Parameter(Mandatory)]$Model)
    $directory = Join-Path $RuntimeRoot ".installed-models"
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
    $additionalRevisions = @()
    if ($Model.PSObject.Properties.Name -contains "additional_revisions") {
        $additionalRevisions = @($Model.additional_revisions)
    }
    $marker = [pscustomobject]@{
        id = $Model.id
        locator = $Model.locator
        revision = $Model.revision
        additional_revisions = $additionalRevisions
        installed_at = [DateTimeOffset]::Now.ToString("o")
        catalog_id = $catalog.catalog_id
    }
    Write-JsonAtomic -Path (Join-Path $directory "$($Model.id).json") -Value $marker
}

function Invoke-HuggingFaceDownload {
    param(
        [Parameter(Mandatory)][string]$Python,
        [Parameter(Mandatory)][string]$Repo,
        [Parameter(Mandatory)][string]$Revision
    )
    $code = @'
from huggingface_hub import snapshot_download
import sys
snapshot_download(repo_id=sys.argv[1], revision=sys.argv[2])
'@
    & $Python -c $code $Repo $Revision
    if ($LASTEXITCODE -ne 0) {
        throw "Model download failed: $Repo"
    }
}

function Install-HuggingFaceModel {
    param(
        [Parameter(Mandatory)]$Model,
        [Parameter(Mandatory)][hashtable]$Pythons
    )
    if ($Model.install_environment -eq "whisperx-wsl") {
        $additionalRepo = [string]$Model.additional_locators[0]
        $additionalRevision = [string]$Model.additional_revisions[0]
        $script = @'
from huggingface_hub import snapshot_download
from pathlib import Path
import sys
root = Path.home() / ".cache" / "meeting-transcriber"
snapshot_download(repo_id=sys.argv[1], revision=sys.argv[2], cache_dir=root)
snapshot_download(repo_id=sys.argv[3], revision=sys.argv[4], cache_dir=root / "alignment")
'@
        $encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($script))
        $bash = "export HF_HUB_DISABLE_PROGRESS_BARS=1; printf '%s' '$encoded' | base64 -d | /opt/meeting-documents/venv/bin/python - '$($Model.locator)' '$($Model.revision)' '$additionalRepo' '$additionalRevision'"
        $wslOutput = @(& wsl.exe -d Ubuntu-22.04 -- bash -lc $bash 2>&1)
        $wslExitCode = $LASTEXITCODE
        $logPath = Join-Path (Split-Path -Parent $StatePath) "setup.log"
        foreach ($line in $wslOutput) {
            if (-not [string]::IsNullOrWhiteSpace([string]$line)) {
                Add-Content -LiteralPath $logPath -Encoding UTF8 -Value "[whisperx] $line"
            }
        }
        if ($wslExitCode -ne 0) {
            $summary = @($wslOutput | Select-Object -Last 6) -join " | "
            if ([string]::IsNullOrWhiteSpace($summary)) {
                $summary = "WSL exited with code $wslExitCode"
            }
            throw "WhisperX model preload failed: $summary"
        }
        Write-ModelMarker -Model $Model
        return
    }
    $python = $Pythons[[string]$Model.install_environment]
    Invoke-HuggingFaceDownload `
        -Python $python `
        -Repo ([string]$Model.locator) `
        -Revision ([string]$Model.revision)
    if ($Model.PSObject.Properties.Name -contains "additional_locators") {
        for ($index = 0; $index -lt $Model.additional_locators.Count; $index++) {
            Invoke-HuggingFaceDownload `
                -Python $python `
                -Repo ([string]$Model.additional_locators[$index]) `
                -Revision ([string]$Model.additional_revisions[$index])
        }
    }
    Write-ModelMarker -Model $Model
}

function Ensure-OllamaRunning {
    $ollama = Get-Command "ollama.exe" -ErrorAction SilentlyContinue
    if (-not $ollama) {
        $fallback = $null
        if (-not [string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
            $fallback = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
        }
        if ($fallback -and (Test-Path -LiteralPath $fallback)) {
            $ollama = Get-Item -LiteralPath $fallback
        }
    }
    if (-not $ollama) {
        throw "Ollama was installed but ollama.exe cannot be found."
    }
    $ollamaPath = $null
    foreach ($property in @("Source", "Path", "FullName")) {
        if ($ollama.PSObject.Properties.Name -contains $property) {
            $candidate = [string]$ollama.$property
            if (-not [string]::IsNullOrWhiteSpace($candidate)) {
                $ollamaPath = $candidate
                break
            }
        }
    }
    if (-not $ollamaPath -or -not (Test-Path -LiteralPath $ollamaPath)) {
        throw "Ollama executable path could not be resolved."
    }
    try {
        Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 2 | Out-Null
    }
    catch {
        Start-Process -FilePath $ollamaPath -ArgumentList "serve" -WindowStyle Hidden | Out-Null
        Start-Sleep -Seconds 2
    }
    return $ollamaPath
}

function Install-OllamaModel {
    param(
        [Parameter(Mandatory)]$Model,
        [Parameter(Mandatory)][string]$Ollama
    )
    & $Ollama pull ([string]$Model.locator)
    if ($LASTEXITCODE -ne 0) {
        throw "Ollama model download failed: $($Model.locator)"
    }
}

function Verify-Installation {
    $statusScript = Join-Path $scriptRoot "Get-WorkstationStatus.ps1"
    $json = & powershell.exe `
        -NoProfile `
        -ExecutionPolicy Bypass `
        -File $statusScript `
        -CatalogPath $CatalogPath `
        -RuntimeRoot $RuntimeRoot `
        -StatePath $StatePath
    if ($LASTEXITCODE -ne 0) {
        throw "Final workstation status check failed."
    }
    return $json | ConvertFrom-Json
}

if ($Action -eq "Verify") {
    $result = Verify-Installation
    [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
    $result | ConvertTo-Json -Depth 20 -Compress
    exit $(if ($result.ready) { 0 } else { 2 })
}

$mutex = [Threading.Mutex]::new($false, "Local\MeetingDocumentsWorkstationSetup")
$ownsMutex = $false
$currentOllamaModels = @((Get-OllamaProfile).models)
foreach ($model in $selectedModels) {
    if ($model.provider -match "-api$") {
        Set-ModelResult -Model $model -Status "ready" -Detail "External API model; no local download required."
    }
    elseif (Test-WorkstationModelInstalled -Model $model -RuntimeRoot $RuntimeRoot -OllamaModels $currentOllamaModels) {
        Set-ModelResult -Model $model -Status "skipped" -Detail "Already installed at the requested revision."
    }
    else {
        Set-ModelResult -Model $model -Status "pending" -Detail "Waiting for installation."
    }
}
try {
    try {
        $ownsMutex = $mutex.WaitOne(0)
    }
    catch [Threading.AbandonedMutexException] {
        $ownsMutex = $true
    }
    if (-not $ownsMutex) {
        [Console]::Error.WriteLine("Another workstation setup process is already running; monitoring the existing process.")
        exit 3
    }

    if ($sidMismatch) {
        throw "Установка должна выполняться под той же учётной записью Windows, которая запустила приложение. Не выбирайте другую администраторскую учётную запись в окне UAC."
    }

    $needsElevation = -not $hardware.wsl.distro_ready
    if ($needsElevation -and -not (Test-Administrator) -and -not $NoElevation) {
        Update-State `
            -Stage "requesting_admin" `
            -Progress 0.02 `
            -Message "Waiting for administrator approval"
        if ($ownsMutex) {
            $mutex.ReleaseMutex()
            $ownsMutex = $false
        }
        Start-ElevatedCopy
        exit 0
    }

    if (-not $hardware.os.supported) {
        throw "Поддерживаются только Windows 10 (сборка 19041+) и Windows 11."
    }
    $localModels = @($selectedModels | Where-Object { $_.provider -notmatch "-api$" })
    if ($localModels.Count -gt 0 -and (-not $hardware.nvidia.available -or -not $hardware.nvidia.cuda_visible)) {
        throw "Для выбранных локальных моделей нужна NVIDIA-видеокарта с рабочим драйвером CUDA. Установка остановлена до загрузки больших файлов."
    }
    if ($hardware.disk.free_gb -lt ([double]$pack.estimated_installed_gb + 8)) {
        throw "Insufficient free disk space. Keep at least 8 GB beyond the selected pack estimate."
    }

    Update-State -Stage "wsl" -Progress 0.12 -Message "Checking WSL2 and Ubuntu 22.04"
    $wslReady = Ensure-Wsl
    if (-not $wslReady) {
        Register-ResumeAfterReboot
        Update-State `
            -Stage "reboot_required" `
            -Progress 0.14 `
            -Message "Restart Windows to finish WSL installation" `
            -Status "PAUSED_REBOOT" `
            -RebootRequired $true
        exit 0
    }


    Update-State -Stage "prerequisites" -Progress 0.15 -Message "Checking Windows prerequisites"
    Ensure-WingetPackage -CommandName "ffprobe" -PackageId "Gyan.FFmpeg"
    Ensure-WingetPackage -CommandName "uv" -PackageId "astral-sh.uv"
    if (@($selectedModels | Where-Object provider -eq "ollama").Count) {
        Ensure-WingetPackage -CommandName "ollama" -PackageId "Ollama.Ollama"
    }

    Update-State -Stage "runtime_source" -Progress 0.18 -Message "Installing application runtime files"
    Copy-RuntimeSource

    Update-State -Stage "python_core" -Progress 0.23 -Message "Creating core and Word environments"
    $uv = Resolve-Uv
    $corePython = Ensure-Venv -Uv $uv -Name ".venv-win"
    Invoke-UvInstall -Uv $uv -Python $corePython -Packages @(
        "httpx>=0.28,<1",
        "python-dotenv>=1.2,<2"
    )
    $docsPython = Ensure-Venv -Uv $uv -Name ".venv-docs"
    Invoke-UvInstall -Uv $uv -Python $docsPython -Packages @(
        "python-docx==1.2.0",
        "lxml>=6,<7",
        "pillow>=11,<12"
    )

    Update-State -Stage "python_speech" -Progress 0.34 -Message "Creating CUDA speech environments"
    $mossPython = Ensure-Venv -Uv $uv -Name ".venv-moss"
    Invoke-UvInstall `
        -Uv $uv `
        -Python $mossPython `
        -Packages @("torch", "torchaudio") `
        -IndexUrl "https://download.pytorch.org/whl/cu128"
    Invoke-UvInstall `
        -Uv $uv `
        -Python $mossPython `
        -Packages @("-e", (Join-Path $RuntimeRoot "vendor\MOSS-Transcribe-Diarize"), "speechbrain==1.1.0", "scikit-learn", "av", "scipy")

    $qwenPython = $null
    $qwenSelected = @($selectedModels | Where-Object { $_.id -eq "qwen3-asr-1.7b-aligner" }).Count -gt 0
    if ($qwenSelected) {
        $qwenPython = Ensure-Venv -Uv $uv -Name ".venv-qwen"
        Invoke-UvInstall `
            -Uv $uv `
            -Python $qwenPython `
            -Packages @("torch", "torchaudio") `
            -IndexUrl "https://download.pytorch.org/whl/cu128"
        Invoke-UvInstall `
            -Uv $uv `
            -Python $qwenPython `
            -Packages @("qwen-asr==0.0.6", "speechbrain==1.1.0")
    }
    Update-State -Stage "wsl_runtime" -Progress 0.48 -Message "Installing WhisperX runtime in WSL"
    Ensure-WslRuntime

    $pythons = @{
        moss = $mossPython
        qwen = $qwenPython
        core = $corePython
        docs = $docsPython
    }
    $downloadModels = @($selectedModels | Where-Object { $_.provider -notmatch "-api$" })
    $modelCount = [Math]::Max(1, $downloadModels.Count)
    $ollamaExe = $null
    for ($index = 0; $index -lt $downloadModels.Count; $index++) {
        $model = $downloadModels[$index]
        $progress = 0.55 + (0.35 * $index / $modelCount)
        if ($model.provider -eq "ollama") {
            $currentOllamaModels = @((Get-OllamaProfile).models)
        }
        if (Test-WorkstationModelInstalled -Model $model -RuntimeRoot $RuntimeRoot -OllamaModels $currentOllamaModels) {
            Set-ModelResult -Model $model -Status "skipped" -Detail "Already installed at the requested revision."
            Update-State `
                -Stage "models" `
                -Progress $progress `
                -Message "Skipping $($model.display_name); already installed"
            continue
        }

        Set-ModelResult -Model $model -Status "installing" -Detail "Download or installation is in progress."
        Update-State `
            -Stage "models" `
            -Progress $progress `
            -Message "Downloading $($model.display_name)"
        try {
            if ($model.provider -eq "ollama") {
                if (-not $ollamaExe) {
                    $ollamaExe = Ensure-OllamaRunning
                }
                Install-OllamaModel -Model $model -Ollama $ollamaExe
            }
            else {
                Install-HuggingFaceModel -Model $model -Pythons $pythons
            }
            Set-ModelResult -Model $model -Status "ready" -Detail "Installed and recorded at the requested revision."
        }
        catch {
            $failure = [pscustomobject]@{
                id = [string]$model.id
                label = [string]$model.display_name
                message = $_.Exception.Message
            }
            [void]$modelFailures.Add($failure)
            Set-ModelResult -Model $model -Status "failed" -Detail $_.Exception.Message
            Update-State `
                -Stage "models" `
                -Progress (0.55 + (0.35 * ($index + 1) / $modelCount)) `
                -Message "Could not install $($model.display_name); continuing"
        }
    }

    Update-State -Stage "verification" -Progress 0.94 -Message "Verifying CUDA, models, and Word export"
    & $mossPython -c "import torch; assert torch.cuda.is_available(); print(torch.cuda.get_device_name(0))"
    if ($LASTEXITCODE -ne 0) { throw "MOSS CUDA verification failed." }
    if ($qwenPython) {
        & $qwenPython -c "import torch, qwen_asr, speechbrain; assert torch.cuda.is_available()"
        if ($LASTEXITCODE -ne 0) { throw "Qwen CUDA verification failed." }
    }
    & $docsPython -c "import docx, lxml"
    if ($LASTEXITCODE -ne 0) { throw "DOCX environment verification failed." }
    & wsl.exe -d Ubuntu-22.04 -- /opt/meeting-documents/venv/bin/python -c `
        "import torch, whisperx; assert torch.cuda.is_available()"
    if ($LASTEXITCODE -ne 0) { throw "WhisperX WSL CUDA verification failed." }

    $finalStatus = Verify-Installation
    if (-not $finalStatus.ready) {
        throw "Final readiness check reports missing required components."
    }
    if ($modelFailures.Count -gt 0) {
        $partialError = [pscustomobject]@{
            message = "$($modelFailures.Count) model components could not be installed."
            type = "PartialInstallation"
            failures = @($modelFailures)
        }
        Update-State `
            -Stage "partial" `
            -Progress 1 `
            -Message "Installation finished with $($modelFailures.Count) unresolved components" `
            -Status "PARTIAL" `
            -ErrorValue $partialError
        exit 2
    }
    Update-State `
        -Stage "complete" `
        -Progress 1 `
        -Message "Workstation is ready" `
        -Status "COMPLETE"
}
catch {
    $errorValue = [pscustomobject]@{
        message = $_.Exception.Message
        type = $_.Exception.GetType().FullName
    }
    try {
        Update-State `
            -Stage "failed" `
            -Progress 0 `
            -Message "Setup failed" `
            -Status "FAILED" `
            -ErrorValue $errorValue
    }
    catch {}
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
finally {
    if ($ownsMutex) {
        $mutex.ReleaseMutex()
    }
    $mutex.Dispose()
}
