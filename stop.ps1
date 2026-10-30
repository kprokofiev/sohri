$ErrorActionPreference = 'Stop'
$sohriRoot = $PSScriptRoot
New-Item -ItemType File -Path (Join-Path $sohriRoot 'data\STOP') -Force | Out-Null
foreach ($sohriName in @('supervisor', 'bot')) {
  $sohriPidFile = Join-Path $sohriRoot ('data\' + $sohriName + '.pid')
  if (Test-Path -LiteralPath $sohriPidFile) {
    $sohriProcessId = [int](Get-Content -LiteralPath $sohriPidFile)
    $sohriProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $sohriProcessId" -ErrorAction SilentlyContinue
    if ($sohriProcess -and $sohriProcess.CommandLine.Contains($sohriName + '.py')) {
      # Verify PID ownership before stopping a process. Stop the tree to avoid orphan Codex jobs.
      & taskkill.exe /PID $sohriProcessId /T /F | Out-Null
    }
  }
}
Write-Output 'Sohri stopped. To start again: .\install-autostart.ps1'
