@echo off
chcp 65001 >nul
title 车辆智能调度 Agent - 启动器

echo ============================================================
echo   车辆智能调度 Agent - 一键启动
echo ============================================================
echo.

set "ROOT=%~dp0"
set "PY=C:\Users\12966\miniconda3\envs\py312\python.exe"
set "ENVFILE=%ROOT%backend\.env"

REM ---------- 环境检查 ----------
if not exist "%PY%" (
    echo [错误] 找不到 Python 3.12 环境：
    echo        %PY%
    pause
    exit /b 1
)

where pnpm >nul 2>nul
if errorlevel 1 (
    echo [错误] 找不到 pnpm，请先安装 Node.js 与 pnpm。
    pause
    exit /b 1
)

REM ---------- 从 .env 读数据库配置（不在脚本里硬编码密码）----------
if not exist "%ENVFILE%" (
    echo [错误] 找不到配置文件：%ENVFILE%
    echo        请先复制 .env.example 为 .env 并按本机情况修改。
    pause
    exit /b 1
)

for /f "usebackq tokens=1,* delims==" %%a in ("%ENVFILE%") do (
    if /i "%%a"=="DB_USER"     set "DB_USER=%%b"
    if /i "%%a"=="DB_PASSWORD" set "DB_PASSWORD=%%b"
    if /i "%%a"=="DB_NAME"     set "DB_NAME=%%b"
)

echo [1/5] 检查 MySQL ...
set "MYSQL_EXE=C:\MySQL\MySQL Server 8.0\bin\mysql.exe"
if exist "%MYSQL_EXE%" (
    set "MYSQL_PWD=%DB_PASSWORD%"
    "%MYSQL_EXE%" -u %DB_USER% --connect-timeout=4 -e "SELECT 1;" >nul 2>nul
    if errorlevel 1 (
        echo       [警告] 连接失败。请确认 MySQL 服务已启动、.env 里的口令正确。
    ) else (
        echo       OK
    )
    set "MYSQL_PWD="
) else (
    echo       [跳过] 找不到 mysql.exe，交由后端自行连接。
)

REM ---------- 依赖 ----------
echo [2/5] 检查后端依赖 ...
"%PY%" -c "import fastapi, sqlalchemy, ortools, langgraph" >nul 2>nul
if errorlevel 1 (
    echo       缺少依赖，正在安装 ...
    "%PY%" -m pip install -r "%ROOT%backend\requirements.txt"
)

echo [3/5] 检查前端依赖 ...
if not exist "%ROOT%frontend\node_modules" (
    echo       首次运行，正在安装（可能需要几分钟）...
    pushd "%ROOT%frontend"
    call pnpm install
    popd
) else (
    echo       OK
)

REM ---------- 初始数据（幂等）----------
echo [4/5] 检查数据库与初始数据 ...
pushd "%ROOT%backend"
"%PY%" seed.py >nul 2>nul
if errorlevel 1 (
    echo       [警告] seed 失败，可能是 MySQL 未就绪。继续尝试启动 ...
) else (
    echo       OK
)
popd

REM ---------- 启动 ----------
echo [5/5] 启动服务 ...
start "调度后端 8000" cmd /k "chcp 65001 >nul && cd /d "%ROOT%backend" && "%PY%" run.py"
timeout /t 6 /nobreak >nul
start "调度前端 5175" cmd /k "chcp 65001 >nul && cd /d "%ROOT%frontend" && pnpm run dev"

echo.
echo ============================================================
echo   已启动两个窗口：
echo     · 调度后端 8000   http://127.0.0.1:8000/docs
echo     · 调度前端 5175   http://127.0.0.1:5175
echo.
echo   等约 10 秒后浏览器打开： http://127.0.0.1:5175
echo.
echo   演示账号（登录页点卡片自动填入，密码见 backend\.env）：
echo     admin       系统管理员（全部 29 个权限）
echo     dispatcher  调度员
echo     viewer      只读观察者
echo.
echo   关闭服务：双击 stop.ps1，或直接关掉这两个黑窗口。
echo ============================================================
timeout /t 8 /nobreak >nul
start "" http://127.0.0.1:5175
