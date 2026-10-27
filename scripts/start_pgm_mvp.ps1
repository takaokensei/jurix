param([ValidateRange(1024, 65535)][int]$Port = 8294)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonExecutable = Join-Path $projectRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonExecutable)) {
    $pythonExecutable = (& uv python find 3.12)
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 is required; install the documented runtime first.' }
}
& $pythonExecutable (Join-Path $PSScriptRoot 'pgm_mvp_runtime.py') start --port $Port
exit $LASTEXITCODE
