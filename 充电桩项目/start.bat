@echo off
chcp 936 >nul
title 充电桩运维管理 AI Agent - 启动器

echo ============================================================
echo   充电桩运维管理 AI Agent 平台 - 一键启动
echo ============================================================
echo.

set "ROOT=%~dp0"
REM ---------- Python 环境 ----------
REM 本机使用 Miniconda 的 py312 环境（Python 3.12），与「车辆智能调度 Agent」项目共用
REM 如需换用其它解释器，设置环境变量 PYTHON_EXE 即可
if defined PYTHON_EXE (
    set "PY=%PYTHON_EXE%"
) else (
    set "PY=D:\miniconda3\envs\py312\python.exe"
)
set "ENVFILE=%ROOT%backend\.env"

if not exist "%PY%" (
    echo [错误] 找不到 Python 3.12：
    echo        %PY%
    echo        请先运行 D:\DSH一般工作区\setup_env.bat 创建环境，
    echo        或设置环境变量 PYTHON_EXE 指向已有解释器。
    pause
    exit /b 1
)

where pnpm >nul 2>nul
if errorlevel 1 (
    echo [警告] 未找到 pnpm，前端将无法启动。可只跑后端。
)

if not exist "%ENVFILE%" (
    echo [提示] 未找到 backend\.env，正在从 .env.example 生成 ...
    copy /y "%ROOT%backend\.env.example" "%ENVFILE%" >nul
)

echo [1/4] 检查后端依赖 ...
"%PY%" -c "import fastapi, sqlalchemy, langgraph, ortools, openpyxl, bcrypt" >nul 2>nul
if errorlevel 1 (
    echo       缺少依赖，正在安装（首次可能需要几分钟）...
    "%PY%" -m pip install -r "%ROOT%backend\requirements.txt" -i https://pypi.tuna.tsinghua.edu.cn/simple
) else (
    echo       OK
)

echo [2/4] 检查前端依赖 ...
if not exist "%ROOT%frontend\node_modules" (
    if exist "%ROOT%frontend\package.json" (
        echo       首次运行，正在安装 ...
        pushd "%ROOT%frontend"
        call pnpm install
        popd
    ) else (
        echo       [跳过] 前端尚未初始化
    )
) else (
    echo       OK
)

echo [3/4] 启动后端（首次启动会自动建库并注入演示数据，约需 20 秒）...
start "充电桩运维后端 8010" cmd /k "chcp 936 >nul && cd /d "%ROOT%backend" && "%PY%" run.py"

echo [4/4] 启动前端 ...
if exist "%ROOT%frontend\package.json" (
    timeout /t 12 /nobreak >nul
    start "充电桩运维前端 5185" cmd /k "chcp 936 >nul && cd /d "%ROOT%frontend" && pnpm run dev"
)

echo.
echo ============================================================
echo   后端接口文档： http://127.0.0.1:8010/docs
echo   前端管理后台： http://127.0.0.1:5185
echo.
echo   演示账号（密码均为 123456，admin 为 admin123）：
echo     admin          平台管理员（平台数据权限）
echo     project_admin  项目管理员（项目数据权限）
echo     station_admin  站点管理员（站点数据权限）
echo     inspector      运维人员（个人数据权限）
echo.
echo   注意：端口 8010/5185 刻意与「车辆智能调度 Agent」项目
echo         （8000/5175）错开，两个项目可同时运行。
echo   关闭服务：双击 stop.bat，或直接关掉命令行窗口。
echo ============================================================
pause
