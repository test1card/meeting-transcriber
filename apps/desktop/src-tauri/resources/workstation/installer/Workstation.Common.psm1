Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Test-Command {
    param([Parameter(Mandatory)][string]$Name)
    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

function Write-JsonAtomic {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)]$Value
    )
    $directory = Split-Path -Parent $Path
    if ($directory) {
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
    }
    $temporary = "$Path.$PID.tmp"
    $json = $Value | ConvertTo-Json -Depth 20
    [IO.File]::WriteAllText($temporary, $json, [Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $temporary -Destination $Path -Force
}

function Read-JsonFile {
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        return $null
    }
    try {
        return Get-Content -Raw -Encoding UTF8 -LiteralPath $Path | ConvertFrom-Json
    }
    catch {
        return $null
    }
}

function Get-LocalAppDataRoot {
    $candidates = @()
    try { $candidates += [Environment]::GetFolderPath("LocalApplicationData") } catch {}
    $candidates += $env:LOCALAPPDATA
    if (-not [string]::IsNullOrWhiteSpace($env:USERPROFILE)) {
        $candidates += [IO.Path]::Combine($env:USERPROFILE, "AppData", "Local")
    }
    try { $candidates += [Environment]::GetFolderPath("UserProfile") } catch {}
    foreach ($candidate in $candidates) {
        if (-not [string]::IsNullOrWhiteSpace([string]$candidate)) {
            try { return [IO.Path]::GetFullPath([string]$candidate) } catch {}
        }
    }
    throw "Не удалось определить локальную папку данных пользователя Windows. Проверьте профиль пользователя и переменные среды LOCALAPPDATA/USERPROFILE."
}

function Get-DefaultRuntimeRoot {
    return [IO.Path]::Combine((Get-LocalAppDataRoot), "MeetingDocuments", "runtime")
}

function Get-DefaultStatePath {
    return [IO.Path]::Combine((Get-LocalAppDataRoot), "MeetingDocuments", "setup-state.json")
}

function Get-NvidiaProfile {
    $result = [ordered]@{
        available = $false
        name = ""
        vram_gb = 0.0
        driver = ""
        cuda_visible = $false
    }
    $nvidia = Get-Command "nvidia-smi.exe" -ErrorAction SilentlyContinue
    if (-not $nvidia) {
        $nvidia = Get-Command "nvidia-smi" -ErrorAction SilentlyContinue
    }
    if (-not $nvidia) {
        return [pscustomobject]$result
    }
    try {
        $line = & $nvidia.Source `
            --query-gpu=name,memory.total,driver_version `
            --format=csv,noheader,nounits 2>$null |
            Select-Object -First 1
        if ($line) {
            $parts = @($line -split "," | ForEach-Object { $_.Trim() })
            $result.available = $true
            $result.name = $parts[0]
            $result.vram_gb = [Math]::Round(([double]$parts[1] / 1024), 1)
            $result.driver = $parts[2]
            $result.cuda_visible = $true
        }
    }
    catch {
        # Returned as unavailable; status remains useful on machines without NVIDIA.
    }
    return [pscustomobject]$result
}

function Get-NvidiaResourceProfile {
    $fallback = Get-NvidiaProfile
    $result = [ordered]@{
        available = [bool]$fallback.available
        name = [string]$fallback.name
        vram_gb = [double]$fallback.vram_gb
        largest_single_gpu_vram_gb = [double]$fallback.vram_gb
        total_vram_gb = [double]$fallback.vram_gb
        gpu_count = if ($fallback.available) { 1 } else { 0 }
        power_limit_w = 0.0
        total_power_limit_w = 0.0
        driver = [string]$fallback.driver
        cuda_visible = [bool]$fallback.cuda_visible
        gpus = @()
    }
    $nvidia = Get-Command "nvidia-smi.exe" -ErrorAction SilentlyContinue
    if (-not $nvidia) {
        $nvidia = Get-Command "nvidia-smi" -ErrorAction SilentlyContinue
    }
    if (-not $nvidia) {
        return [pscustomobject]$result
    }
    try {
        $lines = @(
            & $nvidia.Source `
                --query-gpu=index,name,memory.total,driver_version,power.limit `
                --format=csv,noheader,nounits 2>$null
        )
        $gpus = @(
            foreach ($line in $lines) {
                if (-not $line) { continue }
                $parts = @($line -split "," | ForEach-Object { $_.Trim() })
                if ($parts.Count -lt 4) { continue }
                $power = 0.0
                if ($parts.Count -ge 5 -and $parts[4] -notmatch "N/A") {
                    try { $power = [double]$parts[4] } catch { $power = 0.0 }
                }
                [pscustomobject]@{
                    index = [int]$parts[0]
                    name = [string]$parts[1]
                    vram_gb = [Math]::Round(([double]$parts[2] / 1024), 1)
                    driver = [string]$parts[3]
                    power_limit_w = [Math]::Round($power, 1)
                }
            }
        )
        if ($gpus.Count) {
            $primary = $gpus | Sort-Object vram_gb -Descending | Select-Object -First 1
            $result.available = $true
            $result.name = $primary.name
            $result.vram_gb = $primary.vram_gb
            $result.largest_single_gpu_vram_gb = $primary.vram_gb
            $result.total_vram_gb = [Math]::Round([double](($gpus | Measure-Object vram_gb -Sum).Sum), 1)
            $result.gpu_count = $gpus.Count
            $result.power_limit_w = $primary.power_limit_w
            $result.total_power_limit_w = [Math]::Round([double](($gpus | Measure-Object power_limit_w -Sum).Sum), 1)
            $result.driver = $primary.driver
            $result.cuda_visible = $true
            $result.gpus = @($gpus)
        }
    }
    catch {
        # Keep the compatible single-GPU fallback when extended telemetry fails.
    }
    return [pscustomobject]$result
}

function Get-FormFactorProfile {
    $chassisTypes = @()
    $hasBattery = $false
    try {
        $chassisTypes = @(
            Get-CimInstance Win32_SystemEnclosure |
            ForEach-Object { @($_.ChassisTypes) } |
            ForEach-Object { [int]$_ }
        )
    }
    catch {}
    try {
        $hasBattery = $null -ne (Get-CimInstance Win32_Battery | Select-Object -First 1)
    }
    catch {}
    $portableTypes = @(8, 9, 10, 11, 12, 14, 18, 21, 30, 31, 32)
    $portable = $hasBattery -or @(
        $chassisTypes | Where-Object { $portableTypes -contains $_ }
    ).Count -gt 0
    return [pscustomobject]@{
        id = if ($portable) { "portable" } else { "desktop" }
        portable = $portable
        has_battery = $hasBattery
        chassis_types = @($chassisTypes)
    }
}

function Get-WslProfile {
    $distros = @()
    $available = Test-Command "wsl.exe"
    if ($available) {
        $stdout = Join-Path ([IO.Path]::GetTempPath()) ("meeting-documents-wsl-" + [Guid]::NewGuid().ToString("N") + ".out")
        $stderr = Join-Path ([IO.Path]::GetTempPath()) ("meeting-documents-wsl-" + [Guid]::NewGuid().ToString("N") + ".err")
        try {
            $process = Start-Process -FilePath "wsl.exe" -ArgumentList @("--list", "--quiet") -WindowStyle Hidden -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
            if ($process.WaitForExit(5000)) {
                $distros = @(Get-Content -LiteralPath $stdout -ErrorAction SilentlyContinue | ForEach-Object { ($_ -replace [char]0, "").Trim() } | Where-Object { $_ })
            }
            else {
                try { $process.Kill() } catch {}
            }
        }
        catch {
            $distros = @()
        }
        finally {
            Remove-Item -LiteralPath $stdout,$stderr -Force -ErrorAction SilentlyContinue
        }
    }
    return [pscustomobject]@{
        available = $available
        distro_ready = $distros -contains "Ubuntu-22.04"
        distros = $distros
    }
}
function Get-OllamaProfile {
    $installed = (Test-Command "ollama.exe") -or (Test-Command "ollama")
    $running = $false
    $models = @()
    try {
        $response = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 2
        $running = $true
        $models = @($response.models | ForEach-Object { [string]$_.name })
    }
    catch {
        if ($installed) {
            try {
                $models = @(
                    & ollama list 2>$null |
                    Select-Object -Skip 1 |
                    ForEach-Object { ($_ -split "\s+")[0] } |
                    Where-Object { $_ }
                )
            }
            catch {
                $models = @()
            }
        }
    }
    return [pscustomobject]@{
        installed = $installed
        running = $running
        models = $models
    }
}

function Get-HardwareProfile {
    param([Parameter(Mandatory)][string]$RuntimeRoot)
    $cpu = $null
    $system = $null
    try { $cpu = Get-CimInstance Win32_Processor | Select-Object -First 1 } catch {}
    try { $system = Get-CimInstance Win32_ComputerSystem } catch {}

    $ramBytes = if ($system) { [double]$system.TotalPhysicalMemory } else { 0 }
    $root = [IO.Path]::GetPathRoot([IO.Path]::GetFullPath($RuntimeRoot))
    $drive = $null
    try { $drive = Get-PSDrive -Name $root.Substring(0, 1) } catch {}
    $os = [Environment]::OSVersion.Version
    $nvidia = Get-NvidiaResourceProfile
    $formFactor = Get-FormFactorProfile
    $wsl = Get-WslProfile

    return [pscustomobject]@{
        os = [pscustomobject]@{
            version = $os.ToString()
            build = $os.Build
            supported = ($os.Major -ge 10 -and $os.Build -ge 19041)
        }
        cpu = [pscustomobject]@{
            name = if ($cpu) { [string]$cpu.Name } else { [Environment]::GetEnvironmentVariable("PROCESSOR_IDENTIFIER") }
            physical_cores = if ($cpu) { [int]$cpu.NumberOfCores } else { 0 }
            logical_cores = [Environment]::ProcessorCount
        }
        ram_gb = [Math]::Round(($ramBytes / 1GB), 1)
        disk = [pscustomobject]@{
            root = $root
            free_gb = if ($drive) { [Math]::Round(($drive.Free / 1GB), 1) } else { 0 }
        }
        nvidia = $nvidia
        wsl = $wsl
        form_factor = [pscustomobject]@{
            id = if (
                $nvidia.gpu_count -gt 1 -or
                $nvidia.largest_single_gpu_vram_gb -ge 32 -or
                ($ramBytes / 1GB) -ge 128
            ) { "workstation" } else { $formFactor.id }
            portable = $formFactor.portable
            has_battery = $formFactor.has_battery
            chassis_types = @($formFactor.chassis_types)
        }
    }
}

function Resolve-HardwareClass {
    param(
        [Parameter(Mandatory)]$Catalog,
        [Parameter(Mandatory)]$Hardware
    )
    $vram = [double]$Hardware.nvidia.vram_gb
    $ram = [double]$Hardware.ram_gb
    if (-not $Hardware.nvidia.available) {
        return $Catalog.hardware_profiles | Where-Object id -eq "cpu-only" | Select-Object -First 1
    }
    $matches = @(
        $Catalog.hardware_profiles |
        Where-Object {
            $_.id -ne "cpu-only" -and
            $vram -ge [double]$_.min_vram_gb -and
            $vram -le [double]$_.max_vram_gb -and
            $ram -ge [double]$_.min_ram_gb
        }
    )
    if ($matches.Count) {
        return $matches[-1]
    }
    return $Catalog.hardware_profiles | Where-Object id -eq "gpu-8" | Select-Object -First 1
}

function Resolve-ResourceTier {
    param(
        [Parameter(Mandatory)]$Catalog,
        [Parameter(Mandatory)]$Hardware
    )
    if (-not $Hardware.nvidia.available) {
        return $Catalog.resource_tiers |
            Where-Object id -eq "resource-api-only" |
            Select-Object -First 1
    }
    $vram = [double]$Hardware.nvidia.largest_single_gpu_vram_gb
    $matches = @(
        $Catalog.resource_tiers |
        Where-Object {
            $_.id -ne "resource-api-only" -and
            $vram -ge [double]$_.min_single_gpu_vram_gb -and
            $vram -le [double]$_.max_single_gpu_vram_gb
        }
    )
    if ($matches.Count) {
        return $matches[-1]
    }
    return $Catalog.resource_tiers |
        Where-Object id -ne "resource-api-only" |
        Sort-Object min_single_gpu_vram_gb |
        Select-Object -Last 1
}

function Get-ModelFit {
    param(
        [Parameter(Mandatory)]$Model,
        [Parameter(Mandatory)]$Hardware
    )
    if ($Model.provider -match "-api$") {
        return [pscustomobject]@{
            status = "api"
            label = "API model"
            reason = "Runs in the external API; audio and speaker processing remain local."
        }
    }
    $vram = [double]$Hardware.nvidia.vram_gb
    $ram = [double]$Hardware.ram_gb
    $recommendedVram = [double]$Model.recommended_vram_gb
    $minimumVram = [double]$Model.min_vram_gb
    $minimumRam = [double]$Model.min_ram_gb
    if (-not $Hardware.nvidia.available) {
        return [pscustomobject]@{
            status = "unavailable"
            label = "NVIDIA GPU required"
            reason = "This local speech/LLM runtime is configured for CUDA."
        }
    }
    if ($vram -ge $recommendedVram -and $ram -ge $minimumRam) {
        return [pscustomobject]@{
            status = "recommended"
            label = "Recommended"
            reason = "VRAM and RAM have sufficient working headroom."
        }
    }
    if ($vram -ge $minimumVram -and $ram -ge $minimumRam) {
        return [pscustomobject]@{
            status = "fits"
            label = "Fits"
            reason = "Supported, but GPU memory headroom is limited."
        }
    }
    $offload = $false
    if ($Model.PSObject.Properties.Name -contains "supports_cpu_offload") {
        $offload = [bool]$Model.supports_cpu_offload
    }
    if ($offload -and $ram -ge $minimumRam) {
        return [pscustomobject]@{
            status = "slow_offload"
            label = "Slow RAM offload"
            reason = "Weights exceed VRAM; part of inference will use system memory."
        }
    }
    return [pscustomobject]@{
        status = "unavailable"
        label = "Not recommended"
        reason = "VRAM or RAM is insufficient for stable operation."
    }
}

function Test-PythonEnvironment {
    param(
        [Parameter(Mandatory)][string]$RuntimeRoot,
        [Parameter(Mandatory)][string]$Name
    )
    return Test-Path -LiteralPath (Join-Path $RuntimeRoot "$Name\Scripts\python.exe")
}

function Test-WorkstationModelInstalled {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]$Model,
        [Parameter(Mandatory)][string]$RuntimeRoot,
        [string[]]$OllamaModels = @()
    )
    if ($Model.provider -match "-api$") {
        return $true
    }
    if ($Model.provider -eq "ollama") {
        $wanted = ([string]$Model.locator -replace ":latest$", "")
        $available = @($OllamaModels | ForEach-Object { ([string]$_ -replace ":latest$", "") })
        return $available -contains $wanted
    }

    $markerPath = Join-Path $RuntimeRoot ".installed-models\$($Model.id).json"
    $marker = Read-JsonFile -Path $markerPath
    if (-not $marker) {
        return $false
    }
    if ([string]$marker.id -ne [string]$Model.id -or
        [string]$marker.locator -ne [string]$Model.locator -or
        [string]$marker.revision -ne [string]$Model.revision) {
        return $false
    }
    if ($Model.PSObject.Properties.Name -contains "additional_revisions") {
        if (-not ($marker.PSObject.Properties.Name -contains "additional_revisions")) {
            return $false
        }
        if ((@($marker.additional_revisions) -join "|") -ne (@($Model.additional_revisions) -join "|")) {
            return $false
        }
    }
    return $true
}
function Get-WorkstationStatus {
    param(
        [Parameter(Mandatory)][string]$CatalogPath,
        [Parameter(Mandatory)][string]$RuntimeRoot,
        [Parameter(Mandatory)][string]$StatePath
    )
    $catalog = Get-Content -Raw -Encoding UTF8 -LiteralPath $CatalogPath | ConvertFrom-Json
    $hardware = Get-HardwareProfile -RuntimeRoot $RuntimeRoot
    $ollama = Get-OllamaProfile
    $hardwareClass = Resolve-ResourceTier -Catalog $catalog -Hardware $hardware

    $qwenRequired = [double]$hardware.nvidia.largest_single_gpu_vram_gb -ge 10.5

    $components = @(
        [pscustomobject]@{ id = "windows"; label = "Windows version"; required = $true; ready = [bool]$hardware.os.supported; detail = "Windows 10 build 19041+ or Windows 11" },
        [pscustomobject]@{ id = "nvidia"; label = "NVIDIA and CUDA"; required = $true; ready = [bool]$hardware.nvidia.available; detail = if ($hardware.nvidia.available) { "$($hardware.nvidia.name), $($hardware.nvidia.vram_gb) GB" } else { "Compatible NVIDIA GPU not detected" } },
        [pscustomobject]@{ id = "wsl"; label = "WSL2 Ubuntu 22.04"; required = $true; ready = [bool]$hardware.wsl.distro_ready; detail = if ($hardware.wsl.distro_ready) { "Ubuntu-22.04 is ready" } else { "Will be installed; a restart may be required" } },
        [pscustomobject]@{ id = "ffmpeg"; label = "FFmpeg"; required = $true; ready = (Test-Command "ffprobe"); detail = "Audio and video decoding" },
        [pscustomobject]@{ id = "uv"; label = "Python runtime manager"; required = $true; ready = (Test-Command "uv"); detail = "Isolated model environments" },
        [pscustomobject]@{ id = "python-core"; label = "Core Python"; required = $true; ready = (Test-PythonEnvironment $RuntimeRoot ".venv-win"); detail = "Orchestration and DeepSeek" },
        [pscustomobject]@{ id = "python-docs"; label = "Word exporter"; required = $true; ready = (Test-PythonEnvironment $RuntimeRoot ".venv-docs"); detail = "Four DOCX outputs" },
        [pscustomobject]@{ id = "python-moss"; label = "MOSS runtime"; required = $true; ready = (Test-PythonEnvironment $RuntimeRoot ".venv-moss"); detail = "Speech, timestamps, and speakers" },
        [pscustomobject]@{ id = "python-qwen"; label = "Qwen/ECAPA runtime"; required = $qwenRequired; ready = (Test-PythonEnvironment $RuntimeRoot ".venv-qwen"); detail = if ($qwenRequired) { "Independent STT and global speakers" } else { "Не требуется для профиля 8 ГБ" } },
        [pscustomobject]@{ id = "ollama"; label = "Ollama"; required = $false; ready = [bool]$ollama.installed; detail = if ($ollama.installed) { "$($ollama.models.Count) models installed" } else { "Required only for fully local mode" } }
    )

    $models = @(
        foreach ($model in $catalog.models) {
            $fit = Get-ModelFit -Model $model -Hardware $hardware
            $installed = Test-WorkstationModelInstalled `
                -Model $model `
                -RuntimeRoot $RuntimeRoot `
                -OllamaModels @($ollama.models)
            [pscustomobject]@{
                id = $model.id
                display_name = $model.display_name
                role = $model.role
                provider = $model.provider
                locator = $model.locator
                download_gb = $model.download_gb
                quality_tier = $model.quality_tier
                efficiency_tier = $model.efficiency_tier
                production_status = $model.production_status
                selectable = [bool]$model.selectable
                rationale = $model.rationale
                installed = $installed
                fit = $fit
            }
        }
    )

    $packs = @(
        foreach ($pack in $catalog.packs) {
            [pscustomobject]@{
                id = $pack.id
                label = $pack.label
                description = $pack.description
                required_model_ids = @($pack.required_model_ids)
                optional_model_ids = @($pack.optional_model_ids)
                api_model_ids = @($pack.api_model_ids)
                estimated_download_gb = $pack.estimated_download_gb
                estimated_installed_gb = $pack.estimated_installed_gb
                recommended = (
                    @($hardwareClass.recommended_pack_ids) -contains [string]$pack.id -and
                    [double]$hardware.ram_gb -ge [double]$hardwareClass.min_ram_gb -and
                    [double]$hardware.disk.free_gb -ge [double]$hardwareClass.min_free_disk_gb -and
                    @(
                        $models |
                        Where-Object { @($pack.required_model_ids) -contains $_.id } |
                        Where-Object { $_.fit.status -eq "unavailable" }
                    ).Count -eq 0
                )
            }
        }
    )

    $state = Read-JsonFile -Path $StatePath
    if (-not $state) {
        $state = [pscustomobject]@{
            status = "IDLE"
            stage = "not_started"
            progress = 0
            message = "Setup has not started"
            reboot_required = $false
            error = $null
            model_results = @()
        }
    }
    $requiredReady = @($components | Where-Object required | Where-Object { -not $_.ready }).Count -eq 0
    return [pscustomobject]@{
        schema_version = 2
        catalog = [pscustomobject]@{
            id = $catalog.catalog_id
            as_of = $catalog.as_of
            review_window = $catalog.review_window
            disclaimer = $catalog.disclaimer
        }
            resource_policy = $catalog.resource_policy
        runtime_root = $RuntimeRoot
        state_path = $StatePath
        ready = $requiredReady
        hardware = $hardware
        hardware_class = $hardwareClass
        resource_assessment = [pscustomobject]@{
            tier_id = $hardwareClass.id
            deployment_class = $hardware.form_factor.id
            largest_single_gpu_vram_gb = $hardware.nvidia.largest_single_gpu_vram_gb
            total_vram_gb = $hardware.nvidia.total_vram_gb
            gpu_count = $hardware.nvidia.gpu_count
            meets_min_ram = [double]$hardware.ram_gb -ge [double]$hardwareClass.min_ram_gb
            meets_recommended_ram = [double]$hardware.ram_gb -ge [double]$hardwareClass.recommended_ram_gb
            meets_min_disk = [double]$hardware.disk.free_gb -ge [double]$hardwareClass.min_free_disk_gb
            meets_recommended_disk = [double]$hardware.disk.free_gb -ge [double]$hardwareClass.recommended_free_disk_gb
            multi_gpu_vram_summed_for_models = $false
            current_parallel_gpu_jobs = 1
        }
        ollama = $ollama
        components = $components
        packs = $packs
        models = $models
        setup = $state
    }
}

Export-ModuleMember -Function `
    Get-DefaultRuntimeRoot, Get-DefaultStatePath, Get-LocalAppDataRoot, Get-HardwareProfile, `
    Get-WorkstationStatus, Get-OllamaProfile, Test-WorkstationModelInstalled, `
    Read-JsonFile, Write-JsonAtomic, Test-Command

