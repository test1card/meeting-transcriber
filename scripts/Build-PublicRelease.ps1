[CmdletBinding()]
param(
    [string]$Version = "0.1.15",
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $PSScriptRoot
$desktopRoot = Join-Path $projectRoot "apps\desktop"
$releaseBase = Join-Path $projectRoot "release"
$releaseRoot = Join-Path $releaseBase "MeetingDocuments-$Version-win-x64"
$testRoot = Join-Path ([IO.Path]::GetTempPath()) "meeting-documents-public-release-tests"

if (-not $SkipTests) {
    Push-Location $projectRoot
    try {
        python -m pytest -q --basetemp $testRoot
        if ($LASTEXITCODE -ne 0) { throw "Python tests failed." }
    }
    finally {
        Pop-Location
    }
}

Push-Location $desktopRoot
try {
    npm run check
    if ($LASTEXITCODE -ne 0) { throw "TypeScript check failed." }
    npm run test:ui
    if ($LASTEXITCODE -ne 0) { throw "UI tests failed." }
    npm run tauri:build:full
    if ($LASTEXITCODE -ne 0) { throw "Tauri build failed." }
}
finally {
    Pop-Location
}

$resourceRoot = Join-Path $desktopRoot "src-tauri\resources\workstation"
$forbiddenNames = Get-ChildItem -LiteralPath $resourceRoot -File -Recurse | Where-Object {
    $_.Name -eq ".env" -or $_.Extension -in @(".mp4", ".m4a", ".mp3", ".wav", ".docx")
}
if ($forbiddenNames) {
    throw "Private input/output files were found in packaged resources: $($forbiddenNames.FullName -join ', ')"
}

$textExtensions = @(".py", ".ps1", ".psm1", ".sh", ".json", ".toml", ".md", ".txt", ".js", ".html", ".css")
$forbiddenPatterns = @(
    "(?i)C:\\\\Users\\\\[^\\\\]+\\\\(?:Projects|OneDrive|Downloads)",
    "запись совещания",
    "OneDrive\\Документы",
    '(?m)^\s*(?:DEEPSEEK_API_KEY|HF_TOKEN)\s*=\s*["''][^"''\r\n]{8,}["'']',
    '\bsk-[A-Za-z0-9_-]{16,}\b',
    '\bhf_[A-Za-z0-9]{16,}\b'
)
$privacyHits = New-Object System.Collections.Generic.List[string]
foreach ($file in Get-ChildItem -LiteralPath $resourceRoot -File -Recurse) {
    if ($file.Extension -notin $textExtensions) { continue }
    $content = [IO.File]::ReadAllText($file.FullName)
    foreach ($pattern in $forbiddenPatterns) {
        if ($content -match $pattern) {
            $privacyHits.Add("$($file.FullName): $pattern")
        }
    }
}
if ($privacyHits.Count -gt 0) {
    throw "Privacy scan failed:`n$($privacyHits -join "`n")"
}

$installerDirectory = Join-Path $desktopRoot "src-tauri\target\release\bundle\nsis"
$installer = Get-ChildItem -LiteralPath $installerDirectory -File |
    Where-Object { $_.Name -like "*_${Version}_x64-setup.exe" } |
    Sort-Object LastWriteTimeUtc -Descending |
    Select-Object -First 1
if (-not $installer) {
    throw "Installer for version $Version was not found in $installerDirectory"
}

$resolvedReleaseBase = [IO.Path]::GetFullPath($releaseBase).TrimEnd('\') + '\'
$resolvedReleaseRoot = [IO.Path]::GetFullPath($releaseRoot)
if (-not $resolvedReleaseRoot.StartsWith($resolvedReleaseBase, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Unsafe release path: $resolvedReleaseRoot"
}
if (Test-Path -LiteralPath $resolvedReleaseRoot) {
    Remove-Item -LiteralPath $resolvedReleaseRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $resolvedReleaseRoot | Out-Null

Copy-Item -LiteralPath $installer.FullName -Destination $resolvedReleaseRoot
Copy-Item -LiteralPath (Join-Path $projectRoot "LICENSE") -Destination $resolvedReleaseRoot
Copy-Item -LiteralPath (Join-Path $projectRoot "THIRD_PARTY_NOTICES.md") -Destination $resolvedReleaseRoot
Copy-Item -LiteralPath (Join-Path $projectRoot "PUBLIC_RELEASE_RU.md") -Destination (Join-Path $resolvedReleaseRoot "ИНСТРУКЦИЯ_ДЛЯ_ПОЛЬЗОВАТЕЛЯ.md")

$releaseInstaller = Join-Path $resolvedReleaseRoot $installer.Name
$hash = Get-FileHash -LiteralPath $releaseInstaller -Algorithm SHA256
$hashLine = "$($hash.Hash.ToLowerInvariant())  $($installer.Name)`r`n"
[IO.File]::WriteAllText(
    (Join-Path $resolvedReleaseRoot "SHA256SUMS.txt"),
    $hashLine,
    [Text.UTF8Encoding]::new($false)
)

$archivePath = Join-Path $releaseBase "MeetingDocuments-$Version-win-x64.zip"
if (Test-Path -LiteralPath $archivePath) {
    Remove-Item -LiteralPath $archivePath -Force
}
Add-Type -AssemblyName System.IO.Compression.FileSystem
[IO.Compression.ZipFile]::CreateFromDirectory(
    $resolvedReleaseRoot,
    $archivePath,
    [IO.Compression.CompressionLevel]::Optimal,
    $false
)
$archiveHash = Get-FileHash -LiteralPath $archivePath -Algorithm SHA256
[IO.File]::WriteAllText(
    "$archivePath.sha256.txt",
    "$($archiveHash.Hash.ToLowerInvariant())  $([IO.Path]::GetFileName($archivePath))`r`n",
    [Text.UTF8Encoding]::new($false)
)

Write-Host "Public release ready: $resolvedReleaseRoot"
Write-Host "Installer SHA256: $($hash.Hash)"
Write-Host "Shareable archive: $archivePath"
Write-Host "Archive SHA256: $($archiveHash.Hash)"
