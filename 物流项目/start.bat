@echo off
chcp 65001 >nul
title 车辆智能调度 Agent - 启动器

echo ============================================================
echo   车辆智能调度 Agent - 一键启动
echo ============================================================
echo.

set "ROOT=%~dp0"
set "PY=C:\Users\12966\miniconda3\envs\py312\python.exe"

REM ---------- 环境检查 ----------
if not exist "%PY%" (
    echo [错误] 找不到 Python 3.12 环境：
    echo        %PY%
    echo        请确认 conda 环境 py312 存在。
    pause
    exit /b 1
)

where pnpm >nul 2>nul
if errorlevel 1 (
    echo [错误] 找不到 pnpm，请先安装 Node.js 与 pnpm。
    pause
    exit /b 1
)

REM ---------- 检查 MySQL ----------
echo [1/5] 检查 MySQL ...
"C:\MySQL\MySQL Server 8.0\bin\mysql.exe" -u root -p52misaka -e "SELECT 1;" >nul 2>nul
if errorlevel 1 (
    echo       [警告] MySQL 连接失败。后端启动后会报错。
    echo       请确认 MySQL 8.0 服务已启动。
) else (
    echo       OK
)

REM ---------- 检查依赖 ----------
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

REM ---------- 载入初始数据（幂等） ----------
echo [4/5] 检查数据库与初始数据 ...
pushd "%ROOT%backend"
"%PY%" seed.py >nul 2>nul
if errorlevel 1 (
    echo       [警告] seed 失败，可能 MySQL 未就绪。继续尝试启动 ...
) else (
    echo       OK
)
popd

REM ---------- 启动两个服务 ----------
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
echo   演示账号（点卡片自动填入）：
echo     admin      / admin123    系统管理员（全部权限）
echo     dispatcher / 123456     调度员
echo     viewer     / 123456     只读观察者
echo.
echo   关闭服务：直接关掉那两个黑窗口即可。
echo ============================================================
timeout /t 8 /nobreak >nul
start "" http://127.0.0.1:5175
