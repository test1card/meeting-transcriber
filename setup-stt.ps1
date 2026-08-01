$ErrorActionPreference = "Stop"
$mossCommit = "0e3d1403fd8f1f1c674e883ece96b9f630794ebe"
$vendor = Join-Path $PSScriptRoot "vendor"
$mossSource = Join-Path $vendor "MOSS-Transcribe-Diarize"

New-Item -ItemType Directory -Path $vendor -Force | Out-Null
if (-not (Test-Path -LiteralPath $mossSource)) {
    git clone --filter=blob:none `
        https://github.com/OpenMOSS/MOSS-Transcribe-Diarize.git $mossSource
}
git -C $mossSource fetch origin
git -C $mossSource checkout $mossCommit

$mossPython = Join-Path $PSScriptRoot ".venv-moss\Scripts\python.exe"
uv venv (Join-Path $PSScriptRoot ".venv-moss") --python 3.12
uv pip install --python $mossPython torch torchaudio `
    --index-url https://download.pytorch.org/whl/cu128
uv pip install --python $mossPython -e $mossSource

$qwenPython = Join-Path $PSScriptRoot ".venv-qwen\Scripts\python.exe"
uv venv (Join-Path $PSScriptRoot ".venv-qwen") --python 3.12
uv pip install --python $qwenPython torch torchaudio `
    --index-url https://download.pytorch.org/whl/cu128
uv pip install --python $qwenPython qwen-asr

& $mossPython -c "import torch; print('MOSS CUDA:', torch.cuda.get_device_name(0))"
& $qwenPython -c "import torch; print('Qwen CUDA:', torch.cuda.get_device_name(0))"
Write-Host "MOSS and Qwen STT environments are ready."
