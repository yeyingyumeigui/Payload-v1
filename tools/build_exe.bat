@echo off
chcp 65001 >nul
REM 通信卫星有效载荷方案设计器 —— 一键构建 exe
REM 用法：双击本脚本（或在 cmd 中运行 build_exe.bat）
setlocal
set VENV_PY=C:\Users\Lenovo\.workbuddy\binaries\python\envs\default\Scripts\python.exe
cd /d "%~dp0"

echo [1/2] PyInstaller 打包...
"%VENV_PY%" -m PyInstaller --noconfirm --clean design_app.spec
if errorlevel 1 (
  echo 打包失败，请查看 tools\_build_exe.log
  pause & exit /b 1
)

echo [2/2] 完成。产物: tools\dist\载荷方案设计器.exe
pause
