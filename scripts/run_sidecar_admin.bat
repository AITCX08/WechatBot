@echo off
REM ============================================================
REM  以管理员身份启动 wechat-decrypt sidecar
REM  密钥提取需要读微信进程内存 → 必须管理员权限
REM
REM  用法：右键本文件 → 以管理员身份运行
REM  （或在管理员终端里直接执行本 .bat）
REM ============================================================

REM --- 自我提权：如果不是管理员，重新以管理员身份拉起自己 ---
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [INFO] 正在请求管理员权限...
    powershell -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo [OK] 已获得管理员权限
cd /d "%~dp0..\wx\sidecar\wechat-decrypt"
set WECHAT_DECRYPT_NONINTERACTIVE=1
echo [INFO] 启动 sidecar (端口 5678)...
echo [INFO] 浏览器打开 http://127.0.0.1:5678 查看
echo.
".venv\Scripts\python.exe" monitor_web.py

pause
