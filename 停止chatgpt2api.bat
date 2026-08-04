@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title ChatGPT2API 停止

set "APP_PORT=23456"
echo 正在停止 ChatGPT2API (端口 %APP_PORT%)...

set "FOUND=0"
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":%APP_PORT% " ^| findstr "LISTENING"') do (
    set "PID=%%P"
    rem P0-5：杀前校验进程映像名，只杀 python 进程，防误杀同端口其他程序
    set "IMG="
    for /f "tokens=1" %%I in ('tasklist /fi "PID eq %%P" /fo list ^| findstr /i "Image Name"') do set "IMG=%%I"
    echo !IMG! | findstr /i "python" >nul 2>nul
    if not errorlevel 1 (
        echo  终止 PID %%P (python)
        taskkill /f /pid %%P >nul 2>nul
        set "FOUND=1"
    ) else (
        echo  [跳过] PID %%P 不是 python 进程，不终止
    )
)

if "%FOUND%"=="1" (
    echo.
    echo 已停止。
) else (
    echo.
    echo 未发现运行中的 ChatGPT2API。
)
pause
