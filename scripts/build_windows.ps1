$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

python -m pytest
python -m PyInstaller `
  --noconfirm `
  --clean `
  --onefile `
  --windowed `
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
