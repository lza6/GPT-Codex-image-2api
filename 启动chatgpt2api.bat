@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title ChatGPT2API 启动器

set "APP_PORT=23456"
set "CHATGPT2API_PORT=%APP_PORT%"

echo.
echo ================================================
echo  ChatGPT2API 一键启动
echo  自动清理残留 / 检查环境 / 启动服务
echo ================================================
echo.

rem ---------- 0/6 清理上次残留进程 ----------
echo [0/6] 清理上次残留进程...
set "OLD_PID="
for /f "tokens=5" %%P in ('netstat -ano ^| findstr LISTENING ^| findstr :%APP_PORT%') do set "OLD_PID=%%P"
if defined OLD_PID (
    echo       终止占用端口 %APP_PORT% 的进程 PID %OLD_PID%
    taskkill /f /pid %OLD_PID% >nul 2>nul
    timeout /t 1 /nobreak >nul
)

rem ---------- 1/6 定位 Python ----------
set "PY="
python --version >nul 2>nul
if not errorlevel 1 (
    set "PY=python"
    goto :py_ok
)
py -3 --version >nul 2>nul
if not errorlevel 1 (
    set "PY=py -3"
    goto :py_ok
)
for %%V in (314 313 312 311 310) do (
    if exist "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe" (
        set "PY=%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe"
        goto :py_ok
    )
)
if exist "C:\Python313\python.exe" (
    set "PY=C:\Python313\python.exe"
    goto :py_ok
)
if exist "C:\Python311\python.exe" (
    set "PY=C:\Python311\python.exe"
    goto :py_ok
)
echo [错误] 未找到 Python 3.11+，请先安装 https://www.python.org/downloads/
goto :failed

:py_ok
"%PY%" --version
if errorlevel 1 (
    echo [错误] Python 无法运行
    goto :failed
)
echo [1/6] Python 检查通过

rem ---------- 2/6 定位 uv ----------
set "UV=uv"
%UV% --version >nul 2>nul
if not errorlevel 1 (
    goto :uv_ok
)
if exist "%USERPROFILE%\.local\bin\uv.exe" (
    set "UV=%USERPROFILE%\.local\bin\uv.exe"
    goto :uv_ok
)
if exist "%USERPROFILE%\.cargo\bin\uv.exe" (
    set "UV=%USERPROFILE%\.cargo\bin\uv.exe"
    goto :uv_ok
)
echo [2/6] 未找到 uv，正在安装...
"%PY%" -m pip install uv --quiet
if errorlevel 1 (
    echo [错误] uv 安装失败，请手动执行: "%PY%" -m pip install uv
    goto :failed
)
set "UV=%USERPROFILE%\.local\bin\uv.exe"

:uv_ok
"%UV%" --version
if errorlevel 1 (
    echo [错误] uv 无法运行
    goto :failed
)
echo [2/6] uv 检查通过

rem ---------- 3/6 安装后端依赖 ----------
echo [3/6] 安装后端依赖 (首次运行较慢)...
"%UV%" sync --frozen --no-dev
if errorlevel 1 (
    echo [错误] 后端依赖安装失败
    goto :failed
)
echo       后端依赖就绪

rem ---------- 4/6 构建前端 ----------
set "NEED_BUILD=1"
if exist "web_dist\index.html" if exist "web_dist\.build-stamp" set "NEED_BUILD=0"
if "%NEED_BUILD%"=="1" goto :do_build

for /f "usebackq delims=" %%H in (`powershell -NoProfile -ExecutionPolicy Bypass -File %~dp0scripts\web_stamp.ps1`) do set "CUR_STAMP=%%H"
set /p "OLD_STAMP=<web_dist\.build-stamp"
if not "%CUR_STAMP%"=="%OLD_STAMP%" goto :do_build
echo [4/6] Frontend unchanged, skip build
goto :backend

:do_build
echo [4/6] Building frontend (first run may be slow)...
node --version >nul 2>nul
if errorlevel 1 (
    echo       [warn] Node.js not found, skip frontend build, API only
    goto :backend
)

pushd web
if not exist "node_modules" (
    call npm.cmd ci --no-audit --no-fund
    if errorlevel 1 (
        echo       [error] npm ci failed, skip build
        popd
        goto :backend
    )
)
call npm.cmd run build
if errorlevel 1 (
    echo       [error] frontend build failed, skip
    popd
    goto :backend
)
popd

if not exist "web\out" (
    echo       [warn] web\out build output not found
    goto :backend
)
if exist "web_dist" rmdir /s /q "web_dist"
move /y "web\out" "web_dist" >nul
for /f "usebackq delims=" %%H in (`powershell -NoProfile -ExecutionPolicy Bypass -File %~dp0scripts\web_stamp.ps1`) do set "NEW_STAMP=%%H"
>"web_dist\.build-stamp" echo %NEW_STAMP%
echo       frontend build done

:backend
rem ---------- 5/6 检查端口 ----------
netstat -ano | findstr LISTENING | findstr :%APP_PORT% >nul 2>nul
if not errorlevel 1 (
    echo [错误] 端口 %APP_PORT% 已被占用，请先关闭占用程序
    goto :failed
)
echo [5/6] 端口 %APP_PORT% 空闲

rem ---------- 6/6 启动服务 (崩溃自动重启) ----------
echo [6/6] 启动 ChatGPT2API (端口 %APP_PORT%)...
echo.
echo   Web 管理界面: http://localhost:%APP_PORT%
echo   关闭此窗口即可停止服务
echo.

set "RESTART_COUNT=0"
set "MAX_RESTART=5"
set "BACKOFF_SECS=3"
set "CRASH_LOG=%~dp0crash.log"
:service_loop
"%UV%" run python main.py
set "EXIT_CODE=%ERRORLEVEL%"
if "%EXIT_CODE%"=="0" (
    goto :end
)
set /a RESTART_COUNT+=1
echo %date% %time% exit=%EXIT_CODE% count=%RESTART_COUNT% >> "%CRASH_LOG%"
echo.
echo [警告] 服务异常退出 (代码 %EXIT_CODE%)，第 %RESTART_COUNT%/%MAX_RESTART% 次，%BACKOFF_SECS% 秒后重试...
echo   已记录到 crash.log，要彻底停止请直接关闭此窗口
echo.
if %RESTART_COUNT% GEQ %MAX_RESTART% (
    echo [熔断] 连续 %MAX_RESTART% 次崩溃，停止自动重启防止刷盘死循环。
    echo   查 crash.log 定位原因，修复后可手动再次启动。
    goto :failed
)
timeout /t %BACKOFF_SECS% /nobreak >nul
set /a BACKOFF_SECS*=2
if %BACKOFF_SECS% GTR 60 set "BACKOFF_SECS=60"
goto :service_loop

:failed
echo.
echo 启动失败，请根据上方错误信息处理。
pause
exit /b 1

:end
echo.
echo 服务已停止。
pause
exit /b 0
