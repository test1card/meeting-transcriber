$ErrorActionPreference = "Stop"

try {
    Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 2 | Out-Null
    Write-Host "Ollama API is already running."
    exit 0
}
catch {
    $ollama = Get-Command ollama -ErrorAction Stop
    Write-Host "Starting Ollama API..."
    Start-Process -FilePath $ollama.Source -ArgumentList @("serve") -WindowStyle Hidden
}

for ($attempt = 1; $attempt -le 30; $attempt++) {
    Start-Sleep -Milliseconds 500
    try {
        Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 2 | Out-Null
        Write-Host "Ollama API is ready."
        exit 0
    }
    catch {
        # Keep polling until the startup deadline.
    }
}

throw "Ollama did not become ready on http://127.0.0.1:11434."

