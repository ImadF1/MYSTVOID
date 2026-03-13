$CallerLocation = (Get-Location).Path
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

$ForwardArgs = @($args)
if (-not ($ForwardArgs -contains "--repo-path")) {
    $ForwardArgs = @("--repo-path", $CallerLocation) + $ForwardArgs
}

& $Python -m agent.cli @ForwardArgs
