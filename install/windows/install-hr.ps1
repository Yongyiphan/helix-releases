param([Parameter(Mandatory=$true)][string]$Wheel)
$ErrorActionPreference = 'Stop'
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Run from an elevated PowerShell.' }
$root = Join-Path ${env:ProgramFiles} 'Helix\helix-releases'
$release = Join-Path $root 'current'
New-Item -ItemType Directory -Force -Path $release | Out-Null
python -m venv $release
& (Join-Path $release 'Scripts\python.exe') -m pip install --no-index --force-reinstall $Wheel
$bin = Join-Path ${env:ProgramFiles} 'Helix\bin'
New-Item -ItemType Directory -Force -Path $bin | Out-Null
Set-Content -LiteralPath (Join-Path $bin 'hr.cmd') -Value "@echo off`r`n`"$release\Scripts\hr.exe`" %*`r`n" -Encoding ascii
$machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
if (($machinePath -split ';') -notcontains $bin) { [Environment]::SetEnvironmentVariable('Path', "$machinePath;$bin", 'Machine') }
Write-Host 'Helix Releases installed. Run: hr install list'
