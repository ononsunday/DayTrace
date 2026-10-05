@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo 请先按照 README.md 创建 Python 环境并安装依赖。
    pause
    exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" "run_daytrace.py"
