@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title ChatGPT2API 停止器

echo 正在停止 ChatGPT2API (端口 23456)...

set "FOUND=0"
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":23456 " ^| findstr "LISTENING"') do (
    echo  终止 PID %%P
    taskkill /f /pid %%P >nul 2>nul
    set "FOUND=1"
)

if "%FOUND%"=="1" (
    echo.
    echo 已停止。
) else (
    echo.
    echo 未发现运行中的 ChatGPT2API。
)
pause
