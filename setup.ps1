$ErrorActionPreference = "Stop"
$distro = "Ubuntu-22.04"
$venv = "/home/fall/.venvs/meeting-transcriber"
$comparisonVenv = Join-Path $PSScriptRoot ".venv-win"
$comparisonPython = Join-Path $comparisonVenv "Scripts\python.exe"

Write-Host "Installing FFmpeg in $distro..."
& wsl.exe -d $distro -u root -- apt-get update
& wsl.exe -d $distro -u root -- apt-get install -y ffmpeg python3.10-venv

Write-Host "Creating isolated Python environment..."
& wsl.exe -d $distro -- mkdir -p /home/fall/.venvs
& wsl.exe -d $distro -- python3 -m venv $venv
& wsl.exe -d $distro -- "$venv/bin/python" -m pip install --upgrade pip setuptools wheel
& wsl.exe -d $distro -- "$venv/bin/python" -m pip install `
    "whisperx==3.8.6" "httpx>=0.28,<1" "python-dotenv>=1.2,<2" "pytest>=9,<10"

Write-Host "Creating isolated Windows summarization environment..."
& uv venv $comparisonVenv --python 3.14
& uv pip install --python $comparisonPython `
    "httpx>=0.28,<1" "python-dotenv>=1.2,<2" "pytest>=9,<10"

Write-Host "Verifying CUDA..."
& wsl.exe -d $distro -- "$venv/bin/python" -c `
    "import torch; print('CUDA:', torch.cuda.is_available()); print('GPU:', torch.cuda.get_device_name(0))"

Write-Host "Setup complete."
