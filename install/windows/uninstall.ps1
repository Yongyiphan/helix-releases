param([switch]$PurgeState)
$ErrorActionPreference = 'Stop'
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Run from an elevated PowerShell.' }
foreach ($service in @('hdc-controller','helix-updater')) { sc.exe stop $service 2>$null | Out-Null; sc.exe delete $service 2>$null | Out-Null }
$paths = @((Join-Path ${env:ProgramFiles} 'Helix\helix-releases'),(Join-Path ${env:ProgramFiles} 'Helix\hdc'),(Join-Path ${env:ProgramFiles} 'Helix\updater'),(Join-Path ${env:ProgramData} 'Helix\Updater'))
if ($PurgeState) { $paths += (Join-Path ${env:ProgramData} 'Helix\HDC') }
foreach ($path in $paths) { Remove-Item -LiteralPath $path -Recurse -Force -ErrorAction SilentlyContinue }
Write-Host ('Helix installations removed; state was ' + $(if ($PurgeState) {'purged'} else {'preserved'}) + '.')
