@echo off
REM ============================================================
REM  WechatBot 一键启动 (Windows)
REM
REM  Behavior:
REM   1. Verifies Python is on PATH.
REM   2. Activates the project venv (.venv\) if it exists.
REM   3. Installs requirements.txt the first time (marker: .venv/.installed).
REM   4. Launches the wechat-decrypt sidecar in a new window (best-effort).
REM   5. Starts main.py with the chosen chat model (default 0 = none).
REM
REM  Usage:
REM     start.bat                     -> default model (0)
REM     start.bat 7                   -> DeepSeek
REM     start.bat 7 --auto-start      -> auto-start every account
REM     start.bat 0 --dashboard-only  -> dashboard only, no Weixin
REM ============================================================
setlocal EnableExtensions EnableDelayedExpansion

REM --- 0. Locate project root (script directory) ---
cd /d "%~dp0"

REM --- 1. Python check ---
where python >nul 2>&1
if errorlevel 1 (
    echo [ERR] python.exe not on PATH. Install Python 3.10+ first.
    pause
    exit /b 1
)

REM --- 2. venv (optional but recommended) ---
if exist ".venv\Scripts\activate.bat" (
    call ".venv\Scripts\activate.bat"
    echo [OK] activated .venv
) else (
    echo [INFO] no .venv found; using system Python
)

REM --- 3. Install deps once ---
if not exist ".venv\.installed" (
    if exist requirements.txt (
        echo [INFO] installing requirements (first run)...
        python -m pip install --quiet -r requirements.txt
        if errorlevel 1 (
            echo [WARN] pip install reported errors; continuing anyway
        ) else (
            if exist ".venv" type nul > ".venv\.installed"
        )
    )
)

REM --- 4. Launch sidecar in a new window ---
if exist "wx\sidecar\wechat-decrypt\monitor_web.py" (
    echo [INFO] launching wechat-decrypt sidecar in new window...
    start "wechat-decrypt sidecar" cmd /k "cd /d "%~dp0wx\sidecar\wechat-decrypt" && python monitor_web.py"
) else (
    echo [WARN] sidecar not found at wx\sidecar\wechat-decrypt; skipping
)

REM --- 5. Parse args ---
set CHAT_MODEL=%1
if "%CHAT_MODEL%"=="" set CHAT_MODEL=0
shift
set EXTRA_ARGS=
:collect_args
if "%~1"=="" goto launch
set EXTRA_ARGS=%EXTRA_ARGS% %~1
shift
goto collect_args

:launch
echo.
echo ============================================================
echo  Starting WechatBot
echo  Model: %CHAT_MODEL%   Args: %EXTRA_ARGS%
echo  Dashboard: http://127.0.0.1:9090
echo  (Ctrl+C to stop)
echo ============================================================
echo.
python main.py -c %CHAT_MODEL% %EXTRA_ARGS%

endlocal
