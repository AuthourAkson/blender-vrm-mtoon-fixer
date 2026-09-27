@echo off
chcp 65001 >nul
setlocal
set "BLENDER=D:\Blender Foundation\Blender 4.5\blender.exe"
if not exist "%BLENDER%" set "BLENDER=D:\Blender Foundation\Blender 3.6\blender.exe"

if "%~1"=="" (
    echo 用法：把 .blend 或 .blend1 文件拖到这个 run_fix.bat 上
    echo 也可以直接双击后再把文件拖到窗口里来，目前请先拖放文件运行。
    pause
    exit /b
)

set "INPUT=%~1"
set "OUTPUT=%~dpn1_MToonFixed.vrm"

echo 正在用 Blender 修复材质并导出 VRM，请等待...
echo 输入: "%INPUT%"
echo 输出: "%OUTPUT%"
"%BLENDER%" --background --python "%~dp0vrm_material_fixer.py" -
