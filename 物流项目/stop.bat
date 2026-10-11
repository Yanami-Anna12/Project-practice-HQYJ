@echo off
chcp 65001 >nul
title 车辆智能调度 Agent - 停止器

echo ============================================================
echo   车辆智能调度 Agent - 停止服务
echo ============================================================
echo.

set /a KILLED=0
set /a FAILED=0
set "KILLED_PIDS="
set "ROOT=%~dp0"

REM ---------- 实际端口从 .runtime_port 读（端口可能因被占用/Windows 保留段而顺延）----------
set "BPORT=8000"
if exist "%ROOT%backend\.runtime_port" for /f "usebackq delims=" %%p in ("%ROOT%backend\.runtime_port") do set "BPORT=%%p"
set "FPORT=5175"
if exist "%ROOT%frontend\.runtime_port" for /f "usebackq delims=" %%p in ("%ROOT%frontend\.runtime_port") do set "FPORT=%%p"

REM ---------- 1) 先按 start.bat 打开的控制台窗口标题，结束整棵进程树 ----------
REM 这一步专治 uvicorn reload 模式：reloader 父进程会跟随窗口被 /T 一并结束。
call :killtree "调度后端"
call :killtree "调度前端"

REM ---------- 2) 再按端口兜底（服务不是由 start.bat 启动的情况）----------
for %%P in (%BPORT% %FPORT% 8000 5175) do call :killport %%P

echo.
if "%KILLED%%FAILED%"=="00" (
    echo   没有需要停止的进程（端口 %BPORT% / %FPORT% 都空闲）。
) else (
    echo   已结束 %KILLED% 个进程，失败 %FAILED% 个。
    if not "%FAILED%"=="0" echo   失败通常是权限不足：请右键本文件，选择“以管理员身份运行”。
    echo   提示：如果之前 start.bat 开的黑窗口还留着，直接关掉它们也可以。
)
call :check %BPORT%
call :check %FPORT%
echo.
pause
exit /b 0

REM ---------- 按窗口标题结束进程树 ----------
:killtree
taskkill /F /T /FI "WINDOWTITLE eq %~1" >nul 2>nul
if not errorlevel 1 (
    echo   已结束窗口进程树：%~1
    set /a KILLED+=1
)
exit /b 0

REM ---------- 按端口反复结束 ----------
REM reload 模式下 netstat 报的 PID 可能是已退出的父进程，杀不掉属于正常现象，
REM 因此这里反复尝试，直到「一轮下来一个都没杀成」为止，最后由 :check 如实汇报。
:killport
set /a ROUND=0
:killport_loop
set /a ROUND+=1
set /a KILLED_BEFORE=%KILLED%
for /f "tokens=5" %%a in ('netstat -ano ^| findstr /c:":%1 " ^| findstr /c:"LISTENING"') do call :killone %1 %%a
if %KILLED% gtr %KILLED_BEFORE% if %ROUND% lss 6 (
    ping -n 3 127.0.0.1 >nul 2>nul
    goto :killport_loop
)
exit /b 0

:killone
echo(%KILLED_PIDS%| findstr /c:";%2;" >nul && exit /b 0
set "KILLED_PIDS=%KILLED_PIDS%;%2;"
taskkill /f /pid %2 >nul 2>nul
if errorlevel 1 (
    echo   端口 %1 -^> PID %2 结束失败（该 PID 可能已退出，见下方复查结果）
    set /a FAILED+=1
) else (
    echo   端口 %1 -^> 已结束进程 PID %2
    set /a KILLED+=1
)
exit /b 0

REM ---------- 复查端口是否真的释放 ----------
:check
set "LEFT="
for /f "tokens=5" %%a in ('netstat -ano ^| findstr /c:":%1 " ^| findstr /c:"LISTENING"') do set "LEFT=1"
if defined LEFT (
    echo   [警告] 端口 %1 仍被占用。多半是 uvicorn 以 --reload 启动留下的孤儿 worker，
    echo          可执行：taskkill /f /im python.exe   后重试。
) else (
    echo   端口 %1 已释放。
)
exit /b 0