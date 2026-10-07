@echo off
chcp 936 >nul
echo 正在停止充电桩运维管理 AI Agent 服务 ...

for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8010" ^| findstr "LISTENING"') do (
    taskkill /f /pid %%a >nul 2>nul
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5185" ^| findstr "LISTENING"') do (
    taskkill /f /pid %%a >nul 2>nul
)

echo 已停止 8010（后端）与 5185（前端）。
pause
