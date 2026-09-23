import os
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("powershell") is None, reason="Windows PowerShell is required")
def test_windows_installer_runtime_functions_execute(tmp_path):
    installer = Path(__file__).parents[1] / "install" / "windows" / "install.ps1"
    source_text = installer.read_text(encoding="utf-8")
    assert re.search(r"& \$python -m pip install .*\*> \$null", source_text)
    harness = textwrap.dedent(
        r"""
        $ErrorActionPreference = 'Stop'
        $source = Get-Content -Raw -LiteralPath $env:INSTALLER_SCRIPT
        $definitions = [regex]::Match($source, '(?s)(function Invoke-GitHubJson.*?)(?=Assert-Administrator)').Groups[1].Value
        if ([string]::IsNullOrWhiteSpace($definitions)) { throw 'Installer function definitions were not found.' }
        . ([scriptblock]::Create($definitions))

        $script:fakeResponse = @(
            [pscustomobject]@{ id = 1 }
            [pscustomobject]@{ id = 2 }
        )
        function Invoke-RestMethod { $script:fakeResponse }
        $items = @(Invoke-GitHubJson 'https://example.test/releases')
        if ($items.Count -ne 2 -or $items[0].id -ne 1 -or $items[1].id -ne 2) {
            throw 'Invoke-GitHubJson did not enumerate an array response.'
        }

        $root = Join-Path ([IO.Path]::GetTempPath()) ('helix-installer-runtime-' + [guid]::NewGuid())
        try {
            $payload = Join-Path $root 'payload'
            $destination = Join-Path $root 'install'
            $download = Join-Path $root 'download'
            New-Item -ItemType Directory -Force -Path $payload, $destination, $download | Out-Null
            Set-Content -LiteralPath (Join-Path $payload 'HelixUpdaterService.exe') -Value 'test-service-host'
            $zip = Join-Path $root 'service-host.zip'
            Compress-Archive -Path (Join-Path $payload 'HelixUpdaterService.exe') -DestinationPath $zip
            $script:fakeZip = $zip
            function Invoke-WebRequest { param([string]$Uri, [string]$OutFile); Copy-Item -LiteralPath $script:fakeZip -Destination $OutFile }
            $hash = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant()
            $release = [pscustomobject]@{
                ServiceHostAsset = [pscustomobject]@{ name = 'service-host.zip' }
                ServiceHostMetadata = [pscustomobject]@{ sha256 = $hash }
            }
            $installed = Install-WindowsServiceHost $release $download $destination
            if (-not (Test-Path -LiteralPath $installed)) { throw 'Service host was not installed.' }
            if ((Get-Content -Raw -LiteralPath $installed).Trim() -ne 'test-service-host') {
                throw 'Installed service host content did not match the downloaded asset.'
            }
        }
        finally {
            Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue
        }
        """
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", harness],
        env={**os.environ, "INSTALLER_SCRIPT": str(installer)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
