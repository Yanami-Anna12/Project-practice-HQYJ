@echo off
chcp 65001 >nul
title 充电桩运维管理 AI Agent - 启动器

echo ============================================================
echo   充电桩运维管理 AI Agent 平台 - 一键启动
echo ============================================================
echo.

set "ROOT=%~dp0"
REM ---------- Python 环境（自动探测，可用环境变量 PYTHON_EXE 覆盖）----------
REM 依次尝试多个常见安装位置，不再写死某一台电脑的盘符（原为 D:\miniconda3\...）。
set "PY="
if defined PYTHON_EXE set "PY=%PYTHON_EXE%"
if not exist "%PY%" set "PY=%USERPROFILE%\miniconda3\envs\py312\python.exe"
if not exist "%PY%" set "PY=%LOCALAPPDATA%\miniconda3\envs\py312\python.exe"
if not exist "%PY%" set "PY=C:\ProgramData\miniconda3\envs\py312\python.exe"
if not exist "%PY%" set "PY=C:\miniconda3\envs\py312\python.exe"
if not exist "%PY%" set "PY=D:\miniconda3\envs\py312\python.exe"
if not exist "%PY%" for /f "delims=" %%i in ('where python 2^>nul') do if not defined PY set "PY=%%i"
set "ENVFILE=%ROOT%backend\.env"

if not exist "%PY%" (
    echo [错误] 找不到可用的 Python 解释器。
    echo        已尝试 PYTHON_EXE、conda 常见安装位置、以及 PATH 里的 python。
    echo        请安装 Miniconda 并创建 py312 环境，或设置环境变量 PYTHON_EXE 指向已有解释器，
    echo        例如：set PYTHON_EXE=C:\Users\你的用户名\miniconda3\envs\py312\python.exe
    pause
    exit /b 1
)
echo [环境] 使用 Python: %PY%

REM 包管理器：优先 pnpm，没有就退回 npm（install / run 语法一致）
where pnpm >nul 2>nul
if errorlevel 1 (
    where npm >nul 2>nul
    if errorlevel 1 (
        echo [错误] 找不到 pnpm，也没有 npm。请先安装 Node.js：https://nodejs.org
        pause
        exit /b 1
    )
    echo [提示] 未找到 pnpm，改用 npm。
    set "PKG=npm"
) else (
    set "PKG=pnpm"
)

if not exist "%ENVFILE%" (
    echo [提示] 未找到 backend\.env，正在从 .env.example 生成 ...
    copy /y "%ROOT%backend\.env.example" "%ENVFILE%" >nul
)

echo [1/4] 检查后端依赖 ...
"%PY%" -c "import fastapi, sqlalchemy, langgraph, ortools, openpyxl, bcrypt, jose, aiosqlite" >nul 2>nul
if errorlevel 1 (
    echo       缺少依赖，正在安装（首次可能需要几分钟）...
    "%PY%" -m pip install -r "%ROOT%backend\requirements.txt" -i https://pypi.tuna.tsinghua.edu.cn/simple || "%PY%" -m pip install -r "%ROOT%backend\requirements.txt" -i https://mirrors.aliyun.com/pypi/simple || "%PY%" -m pip install -r "%ROOT%backend\requirements.txt" || echo       [警告] 依赖自动安装失败，请检查网络
) else (
    echo       OK
)

echo [2/4] 检查前端依赖 ...
if not exist "%ROOT%frontend\node_modules" (
    if exist "%ROOT%frontend\package.json" (
        echo       首次运行，正在安装 ...
        pushd "%ROOT%frontend"
        call %PKG% install
        popd
    ) else (
        echo       [跳过] 前端尚未初始化
    )
) else (
    echo       OK
)

echo [3/4] 启动后端（首次启动会自动建库并注入演示数据，约需 20 秒）...
start "充电桩运维后端" cmd /k "chcp 65001 >nul && cd /d "%ROOT%backend" && "%PY%" run.py"

echo [4/4] 启动前端 ...
REM 读后端实际端口（run.py 写入的 .runtime_port），让前端把 /api 代理到正确端口
set "BPORT="
if exist "%ROOT%backend\.runtime_port" for /f "usebackq delims=" %%p in ("%ROOT%backend\.runtime_port") do set "BPORT=%%p"
if defined BPORT set "VITE_API_TARGET=http://127.0.0.1:%BPORT%"
if exist "%ROOT%frontend\package.json" (
    timeout /t 12 /nobreak >nul
    start "充电桩运维前端" cmd /k "chcp 65001 >nul && cd /d "%ROOT%frontend" && %PKG% run dev"
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
