$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

python -m pytest
python -m PyInstaller `
  --noconfirm `
  --clean `
  --onefile `
  --windowed `
  --icon "src\mb_optimizer\resources\app.ico" `
  --add-data "src\mb_optimizer\resources\app.png;mb_optimizer\resources" `
  --add-data "src\mb_optimizer\resources\app.ico;mb_optimizer\resources" `
  --name "MB-CF-Optimizer-windows-x64" `
  app.py

$Exe = Join-Path $Root "dist\MB-CF-Optimizer-windows-x64.exe"
$Checksum = (Get-FileHash $Exe -Algorithm SHA256).Hash.ToLower()
"$Checksum  MB-CF-Optimizer-windows-x64.exe" | Set-Content `
  -Path "$Exe.sha256" `
  -Encoding ascii `
  -NoNewline

Write-Host "Built: $Exe"
Write-Host "SHA-256: $Checksum"
