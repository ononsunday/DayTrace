param([string]$Python = '')
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $taskRoot
if (-not $Python) { $Python = Join-Path $taskRoot '.venv\Scripts\python.exe' }
if (-not (Test-Path -LiteralPath $Python)) {
    & py -3 -m venv (Join-Path $taskRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw '需要安装 Python 3.12 或更高版本。可通过 -Python 指定解释器。' }
    $Python = Join-Path $taskRoot '.venv\Scripts\python.exe'
}
& $Python -c 'import sys; assert sys.version_info >= (3, 12), "Python 3.12+ is required"'
if ($LASTEXITCODE -ne 0) { throw 'Python 3.12+ is required.' }
& $Python -c 'import PySide6, PyInstaller, pytest'
if ($LASTEXITCODE -ne 0) {
    & $Python -m pip install -r requirements-dev.txt
    if ($LASTEXITCODE -ne 0) { throw '依赖安装失败，请检查网络后重新运行。' }
}
& $Python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw '测试未通过，停止打包。' }
& $Python scripts\make_icon.py
if ($LASTEXITCODE -ne 0) { throw '图标生成失败。' }
& $Python -m PyInstaller --noconfirm --clean DayTrace.spec
if ($LASTEXITCODE -ne 0) { throw '打包失败。' }
Write-Host '打包完成：dist\DayTrace\DayTrace.exe'
