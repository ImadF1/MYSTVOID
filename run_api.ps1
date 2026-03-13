$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    $Python = "python"
}

if ([string]::IsNullOrWhiteSpace($env:PYTHONPATH)) {
    $env:PYTHONPATH = $Root
} else {
    $env:PYTHONPATH = "$Root;$env:PYTHONPATH"
}

& $Python -m uvicorn api.server:app --host 127.0.0.1 --port 8000 --reload
