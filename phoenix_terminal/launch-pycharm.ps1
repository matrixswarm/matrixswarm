param(
    [string]$PhoenixRoot,
    [string]$PythonPath
)

$ErrorActionPreference = 'Stop'
$terminalRoot = $PSScriptRoot

if (-not $PhoenixRoot) {
    $PhoenixRoot = if ($env:PHOENIX_ROOT) {
        $env:PHOENIX_ROOT
    } else {
        Join-Path (Split-Path -Parent $terminalRoot) 'phoenix'
    }
}
$PhoenixRoot = (Resolve-Path -LiteralPath $PhoenixRoot).Path

if (-not (Test-Path -LiteralPath (Join-Path $PhoenixRoot 'phoenix.py'))) {
    throw "Phoenix source was not found: $PhoenixRoot"
}

if (-not $PythonPath) {
    $PythonPath = if ($env:PHOENIX_PYTHON) {
        $env:PHOENIX_PYTHON
    } else {
        $venvPython = Join-Path $PhoenixRoot '.venv\Scripts\python.exe'
        if (Test-Path -LiteralPath $venvPython) {
            $venvPython
        } else {
            (Get-Command python -ErrorAction Stop).Source
        }
    }
}
$PythonPath = (Resolve-Path -LiteralPath $PythonPath).Path
if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw "Python interpreter was not found: $PythonPath"
}

Set-Location -LiteralPath $terminalRoot
& $PythonPath -m phoenix_terminal launch --phoenix-root $PhoenixRoot
exit $LASTEXITCODE
