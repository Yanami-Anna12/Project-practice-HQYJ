# 停止由 start.bat / start.ps1 启动的服务（释放 8000 与 5175 端口）
$ErrorActionPreference = 'SilentlyContinue'

Write-Host '正在停止车辆智能调度 Agent 服务 ...'

$stopped = 0
foreach ($port in 8000, 5175) {
  $conns = Get-NetTCPConnection -State Listen | Where-Object { $_.LocalPort -eq $port }
  foreach ($c in $conns) {
    $proc = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue
    if ($proc) {
      Write-Host ('  端口 ' + $port + ' -> 结束进程 ' + $proc.ProcessName + ' (PID ' + $proc.Id + ')')
      Stop-Process -Id $proc.Id -Force
      $stopped = $stopped + 1
    }
  }
}

if ($stopped -eq 0) {
  Write-Host '  没有需要停止的进程（端口 8000 / 5175 都空闲）'
} else {
  Write-Host ('已停止 ' + $stopped + ' 个进程。')
  Write-Host '提示：如果之前用 start.bat 开了两个黑窗口，直接关掉它们也可以。'
}
