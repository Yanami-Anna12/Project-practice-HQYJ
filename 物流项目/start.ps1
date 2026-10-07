<#
  车辆智能调度 Agent - 一键启动（PowerShell 版）

  用法：
    pwsh -File start.ps1

  与 start.bat 的区别：本脚本在后端最小化窗口 + 同时在本终端显示前端日志；
  Ctrl+C 会一并停掉后端。

  ★ 本文件必须以 UTF-8 with BOM 保存：
    Windows PowerShell 5.1 默认按 GBK 读取 .ps1，没有 BOM 时中文会变乱码，
    进而导致引号配对失败、脚本报语法错误。
#>

$ErrorActionPreference = 'Continue'
$Root = $PSScriptRoot
$Py = 'C:\Users\12966\miniconda3\envs\py312\python.exe'
$MySqlExe = 'C:\MySQL\MySQL Server 8.0\bin\mysql.exe'
$Line = '============================================================'

function Info($msg) { Write-Host $msg }
function Ok($msg) { Write-Host ('      ' + $msg) -ForegroundColor Green }
function Warn($msg) { Write-Host ('      ' + $msg) -ForegroundColor Yellow }
function Err($msg) { Write-Host ('      ' + $msg) -ForegroundColor Red }

Write-Host $Line
Write-Host '  车辆智能调度 Agent - 一键启动'
Write-Host $Line
Write-Host ''

# ---------- 1. 环境 ----------
Info '[1/5] 检查环境 ...'
if (-not (Test-Path $Py)) {
  Err ('找不到 Python 3.12：' + $Py)
  exit 1
}
Ok ('Python: ' + (& $Py --version 2>&1))

$pnpmCmd = Get-Command pnpm -ErrorAction SilentlyContinue
if (-not $pnpmCmd) {
  Err '找不到 pnpm，请先安装 Node.js 与 pnpm'
  exit 1
}
Ok ('pnpm: ' + (pnpm --version))

# ---------- 2. MySQL ----------
# 连接参数从 backend/.env 读取，不在脚本里硬编码密码
# （早先写死过明文口令，提交到仓库造成泄露，已修正）
Info '[2/5] 检查 MySQL ...'
$envFile = Join-Path $Root 'backend\.env'
if (-not (Test-Path $envFile)) {
  Err ('找不到配置文件：' + $envFile)
  Err '请先复制 backend/.env.example 为 backend/.env 并按本机情况修改。'
  exit 1
}

$dbCfg = @{}
foreach ($line in (Get-Content $envFile -Encoding UTF8)) {
  if ($line -match '^\s*([A-Z_]+)\s*=\s*(.*)$') {
    $dbCfg[$matches[1]] = $matches[2].Trim()
  }
}
$dbUser = 'root'
if ($dbCfg.ContainsKey('DB_USER')) { $dbUser = $dbCfg['DB_USER'] }
$dbPass = ''
if ($dbCfg.ContainsKey('DB_PASSWORD')) { $dbPass = $dbCfg['DB_PASSWORD'] }

if (Test-Path $MySqlExe) {
  $env:MYSQL_PWD = $dbPass
  $mysqlOut = & $MySqlExe -u $dbUser --connect-timeout=4 -e 'SELECT 1;' 2>&1
  $env:MYSQL_PWD = ''
  if ($mysqlOut -match '1') {
    Ok 'MySQL 可连接'
  } else {
    Warn 'MySQL 连接失败，后端会启动失败。'
    Warn '请确认 MySQL 8.0 服务已启动、且 .env 里的 DB_USER/DB_PASSWORD 正确。'
  }
} else {
  Ok '未找到 mysql.exe，跳过预检（后端会自行连接）'
}

# ---------- 3. 依赖 ----------
Info '[3/5] 检查后端依赖 ...'
& $Py -c 'import fastapi, sqlalchemy, ortools, langgraph' 2>$null
if ($LASTEXITCODE -ne 0) {
  Warn '缺少依赖，正在安装（可能需要几分钟）...'
  & $Py -m pip install -r (Join-Path $Root 'backend\requirements.txt')
} else {
  Ok '依赖齐全'
}

Info '[4/5] 检查前端依赖 ...'
$frontendDir = Join-Path $Root 'frontend'
if (-not (Test-Path (Join-Path $frontendDir 'node_modules'))) {
  Warn '首次运行，正在安装前端依赖 ...'
  Push-Location $frontendDir
  pnpm install
  Pop-Location
} else {
  Ok 'node_modules 已存在'
}

# ---------- 4. 初始数据 ----------
Info '[5/5] 载入初始数据（幂等，已存在的不重复插入）...'
Push-Location (Join-Path $Root 'backend')
$seedOut = & $Py seed.py 2>&1
Pop-Location
$seedOut | Select-String -Pattern '数据表已就绪|初始数据载入完成' | ForEach-Object { Ok $_.Line }

# ---------- 5. 启动 ----------
Write-Host ''
Write-Host $Line
Write-Host '  启动服务'
Write-Host $Line
Write-Host ''
Write-Host '  后端  http://127.0.0.1:8000/docs'
Write-Host '  前端  http://127.0.0.1:5175'
Write-Host ''
Write-Host '  演示账号（登录页点卡片自动填入，密码见 backend\.env）'
Write-Host '    admin       系统管理员（全部 29 个权限）'
Write-Host '    dispatcher  调度员'
Write-Host '    viewer      只读观察者'
Write-Host ''

$backend = Start-Process -FilePath $Py -ArgumentList 'run.py' `
  -WorkingDirectory (Join-Path $Root 'backend') -PassThru -WindowStyle Minimized

try {
  Start-Sleep -Seconds 7
  Start-Process 'http://127.0.0.1:5175' | Out-Null

  Push-Location $frontendDir
  Info '前端日志如下。按 Ctrl+C 停止前端（后端也会一并停止）：'
  Write-Host ''
  pnpm run dev
} finally {
  Pop-Location -ErrorAction SilentlyContinue
  if ($backend -and -not $backend.HasExited) {
    Write-Host ''
    Info '正在停止后端 ...'
    Stop-Process -Id $backend.Id -Force -ErrorAction SilentlyContinue
  }
}
