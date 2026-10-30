$ErrorActionPreference = 'Stop'
$sohriRoot = $PSScriptRoot
$sohriPython = (Get-Command python).Source
$sohriPythonw = Join-Path (Split-Path $sohriPython) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $sohriPythonw)) { throw 'pythonw.exe not found' }
$sohriSupervisor = Join-Path $sohriRoot 'supervisor.py'
$sohriStop = Join-Path $sohriRoot 'data\STOP'
if (Test-Path -LiteralPath $sohriStop) { Remove-Item -LiteralPath $sohriStop }

# A per-user Startup shortcut needs no administrator rights and launches hidden.
$sohriStartup = [Environment]::GetFolderPath('Startup')
$sohriShell = New-Object -ComObject WScript.Shell
$sohriShortcut = $sohriShell.CreateShortcut((Join-Path $sohriStartup 'Sohri.lnk'))
$sohriShortcut.TargetPath = $sohriPythonw
$sohriShortcut.Arguments = '"' + $sohriSupervisor + '"'
$sohriShortcut.WorkingDirectory = $sohriRoot
$sohriShortcut.Description = 'Sohri Telegram inbox with automatic restart'
$sohriShortcut.WindowStyle = 7
$sohriShortcut.Save()
Start-Process -FilePath $sohriPythonw -ArgumentList ('"' + $sohriSupervisor + '"') -WorkingDirectory $sohriRoot -WindowStyle Hidden
Write-Output ('Startup installed: ' + (Join-Path $sohriStartup 'Sohri.lnk'))
