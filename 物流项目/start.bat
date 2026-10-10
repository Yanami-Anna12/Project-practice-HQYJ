@echo off
chcp 65001 >nul
title 车辆智能调度 Agent - 启动器

echo ============================================================
echo   车辆智能调度 Agent - 一键启动
echo ============================================================
echo.

set "ROOT=%~dp0"
REM ---------- Python 环境（自动探测，可用环境变量 PYTHON_EXE 覆盖）----------
REM 依次尝试多个常见安装位置，避免换电脑后因盘符/用户名不同而启动失败。
set "PY="
if defined PYTHON_EXE set "PY=%PYTHON_EXE%"
if not exist "%PY%" set "PY=%USERPROFILE%\miniconda3\envs\py312\python.exe"
if not exist "%PY%" set "PY=%LOCALAPPDATA%\miniconda3\envs\py312\python.exe"
if not exist "%PY%" set "PY=C:\ProgramData\miniconda3\envs\py312\python.exe"
if not exist "%PY%" set "PY=C:\miniconda3\envs\py312\python.exe"
if not exist "%PY%" set "PY=D:\miniconda3\envs\py312\python.exe"
if not exist "%PY%" for /f "delims=" %%i in ('where python 2^>nul') do if not defined PY set "PY=%%i"
set "ENVFILE=%ROOT%backend\.env"

REM ---------- 环境检查 ----------
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

REM ---------- 从 .env 读数据库配置（不在脚本里硬编码密码）----------
if not exist "%ENVFILE%" (
    echo [提示] 未找到 backend\.env，正在从 .env.example 自动生成 ...
    copy /y "%ROOT%backend\.env.example" "%ENVFILE%" >nul
    echo [注意] 数据库密码用的是模板里的占位值，若连不上 MySQL 请改 %ENVFILE% 里的 DB_PASSWORD。
    echo        本机若已装 MySQL 且密码不同，改完重新运行本脚本即可；不装 MySQL 也能跑（会自动回退 SQLite）。
)

for /f "usebackq tokens=1,* delims==" %%a in ("%ENVFILE%") do (
    if /i "%%a"=="DB_USER"     set "DB_USER=%%b"
    if /i "%%a"=="DB_PASSWORD" set "DB_PASSWORD=%%b"
    if /i "%%a"=="DB_NAME"     set "DB_NAME=%%b"
)

echo [1/5] 检查 MySQL ...
REM ---------- 自动搜索 mysql.exe（别写死路径，也别用 for 列表：
REM            带空格的 "C:\Program Files\..." 在 for 集合里会被当成命令，
REM            报 'C:\Program' is not recognized —— 这个坑踩过）----------
set "MYSQL_EXE="
for /f "delims=" %%i in ('where mysql 2^>nul') do if not defined MYSQL_EXE set "MYSQL_EXE=%%i"
if not defined MYSQL_EXE if exist "%ProgramFiles%\MySQL\MySQL Server 8.0\bin\mysql.exe" set "MYSQL_EXE=%ProgramFiles%\MySQL\MySQL Server 8.0\bin\mysql.exe"
if not defined MYSQL_EXE if exist "%ProgramFiles%\MySQL\MySQL Server 8.4\bin\mysql.exe" set "MYSQL_EXE=%ProgramFiles%\MySQL\MySQL Server 8.4\bin\mysql.exe"
if not defined MYSQL_EXE if exist "%ProgramFiles(x86)%\MySQL\MySQL Server 8.0\bin\mysql.exe" set "MYSQL_EXE=%ProgramFiles(x86)%\MySQL\MySQL Server 8.0\bin\mysql.exe"
if not defined MYSQL_EXE if exist "C:\MySQL\MySQL Server 8.0\bin\mysql.exe" set "MYSQL_EXE=C:\MySQL\MySQL Server 8.0\bin\mysql.exe"
if not defined MYSQL_EXE if exist "D:\MySQL\MySQL Server 8.0\bin\mysql.exe" set "MYSQL_EXE=D:\MySQL\MySQL Server 8.0\bin\mysql.exe"
if not defined MYSQL_EXE if exist "D:\mysql\bin\mysql.exe" set "MYSQL_EXE=D:\mysql\bin\mysql.exe"
if not defined MYSQL_EXE if exist "C:\mysql\bin\mysql.exe" set "MYSQL_EXE=C:\mysql\bin\mysql.exe"
if not defined MYSQL_EXE if exist "C:\xampp\mysql\bin\mysql.exe" set "MYSQL_EXE=C:\xampp\mysql\bin\mysql.exe"
if not defined MYSQL_EXE if exist "D:\xampp\mysql\bin\mysql.exe" set "MYSQL_EXE=D:\xampp\mysql\bin\mysql.exe"
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
    "%PY%" -m pip install -r "%ROOT%backend\requirements.txt" -i https://pypi.tuna.tsinghua.edu.cn/simple || "%PY%" -m pip install -r "%ROOT%backend\requirements.txt" -i https://mirrors.aliyun.com/pypi/simple || "%PY%" -m pip install -r "%ROOT%backend\requirements.txt" || echo       [警告] 依赖自动安装失败，请检查网络
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
start "调度后端" cmd /k "chcp 65001 >nul && cd /d "%ROOT%backend" && "%PY%" run.py"
timeout /t 6 /nobreak >nul
REM 读后端实际端口（run.py 写入的 .runtime_port），让前端把 /api 代理到正确端口
set "BPORT="
if exist "%ROOT%backend\.runtime_port" for /f "usebackq delims=" %%p in ("%ROOT%backend\.runtime_port") do set "BPORT=%%p"
if defined BPORT set "VITE_PROXY_TARGET=http://127.0.0.1:%BPORT%"
start "调度前端" cmd /k "chcp 65001 >nul && cd /d "%ROOT%frontend" && %PKG% run dev"

echo.
echo ============================================================
echo   已启动两个窗口：
echo     · 调度后端 8000   http://127.0.0.1:8000/docs
echo     · 调度前端 5175   http://127.0.0.1:5175
echo       （若该端口被系统保留/占用，Vite 会自动用 5176、5177…，
echo         请以「调度前端」窗口里打印的 Local 地址为准）
echo.
echo   等约 10 秒后浏览器打开： http://127.0.0.1:5175
echo.
echo   演示账号（登录页点卡片自动填入，密码见 backend\.env）：
echo     admin       系统管理员（全部 29 个权限）
echo     dispatcher  调度员
echo     viewer      只读观察者
echo.
echo   关闭服务：双击 stop.bat，或直接关掉这两个黑窗口。
echo ============================================================
timeout /t 8 /nobreak >nul
start "" http://127.0.0.1:5175
