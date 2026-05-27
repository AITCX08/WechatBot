@echo off
REM ============================================================
REM  WechatBot 优雅停止 (Windows)
REM
REM  Kills:
REM   1. Python processes listening on 9090 (dashboard + main.py)
REM   2. The sidecar python process (cwd contains wechat-decrypt)
REM
REM  Does NOT kill Weixin.exe — leave it logged in for next start.
REM ============================================================
setlocal EnableExtensions

echo [INFO] stopping WechatBot...

REM --- Kill any python listening on 9090 ---
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":9090" ^| findstr "LISTENING"') do (
    echo [INFO] killing dashboard PID %%P
    taskkill /PID %%P /F >nul 2>&1
)

REM --- Kill sidecar (wechat-decrypt monitor_web.py) ---
wmic process where "name='python.exe' and commandline like '%%monitor_web.py%%'" get processid 2>nul | findstr /r "[0-9]" >nul
if not errorlevel 1 (
    for /f "tokens=*" %%I in ('wmic process where "name='python.exe' and commandline like '%%monitor_web.py%%'" get processid /value 2^>nul ^| findstr "="') do (
        for /f "tokens=2 delims==" %%P in ("%%I") do (
            if not "%%P"=="" (
                echo [INFO] killing sidecar PID %%P
                taskkill /PID %%P /F >nul 2>&1
            )
        )
    )
) else (
    echo [INFO] no sidecar python process found
)

echo [OK] done.
endlocal
