[CmdletBinding()]
param(
    [string]$Owner = 'Yongyiphan',
    [string]$Repository = 'helix-releases',
    [ValidateSet('stable')]
    [string]$Channel = 'stable'
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

function Assert-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'Run install.ps1 from an elevated PowerShell session.'
    }
}

function Invoke-GitHubJson([string]$Uri) {
    $response = Invoke-RestMethod -Headers @{ Accept = 'application/vnd.github+json' } -Uri $Uri
    if ($response -is [Array]) {
        foreach ($item in $response) { Write-Output $item }
    } else {
        $response
    }
}

function Assert-SafeAssetName([string]$Name) {
    if ([string]::IsNullOrWhiteSpace($Name) -or $Name -notmatch '^[A-Za-z0-9_.+-]+$') {
        throw "GitHub returned an unsafe artifact name: $Name"
    }
}

function Get-VerifiedRelease([string]$ReleaseRepository, [string]$Package, [switch]$SkipSourceVerification) {
    $api = "https://api.github.com/repos/$Owner/$ReleaseRepository"
    $releases = @(Invoke-GitHubJson "$api/releases?per_page=100")
    $releases = @($releases | Where-Object {
        -not $_.draft -and -not $_.prerelease -and $_.tag_name -like "$Package-v*"
    })

    $release = $releases |
        Sort-Object { [version]($_.tag_name -replace "^$Package-v", '') } -Descending |
        Select-Object -First 1
    if (-not $release) { throw "No stable $Package GitHub release was found." }

    $version = ($release.tag_name -replace "^$Package-v", '')
    $manifestAsset = @($release.assets | Where-Object name -eq "$Package-$version.manifest.json") | Select-Object -First 1
    if (-not $manifestAsset) { throw "Release $($release.tag_name) has no manifest asset." }
    $manifest = Invoke-GitHubJson $manifestAsset.browser_download_url

    if ($manifest.schema -ne 1 -or $manifest.package -ne $Package -or
        $manifest.channel -ne $Channel -or $manifest.version -ne $version) {
        throw "Invalid $Package manifest identity in release $($release.tag_name)."
    }
    if ($manifest.commit -notmatch '^[0-9a-fA-F]{40}$') { throw "Invalid source commit in $Package manifest." }

    if (-not $SkipSourceVerification) {
        $commit = Invoke-GitHubJson "$api/commits/$($manifest.commit)"
        $verified = $commit.commit.verification.verified
        $authors = @($commit.author.login, $commit.committer.login) | Where-Object { $_ }
        if (-not $verified -or ($authors -notcontains $Owner)) {
            throw "$Package source commit $($manifest.commit) is not verified and associated with $Owner."
        }
    }

    $artifact = $manifest.artifacts.'windows-x86_64'
    if (-not $artifact) { $artifact = $manifest.artifacts.any }
    Assert-SafeAssetName $artifact.file
    if ($artifact.sha256 -notmatch '^[0-9a-fA-F]{64}$') { throw "Invalid $Package artifact checksum." }
    $artifactAsset = @($release.assets | Where-Object name -eq $artifact.file) | Select-Object -First 1
    if (-not $artifactAsset) { throw "Release $($release.tag_name) is missing $($artifact.file)." }
    $serviceHostAsset = $null
    $serviceHostMetadata = $null
    if ($Package -eq 'helix-updater') {
        $serviceHostAsset = @($release.assets | Where-Object name -eq "helix-updater-service-host-$version-windows-x86_64.zip") | Select-Object -First 1
        if (-not $serviceHostAsset) { throw "HU release $($release.tag_name) is missing its Windows service-host asset." }
        $serviceHostMetadata = $manifest.runtime_assets.'windows-x86_64'
        if (-not $serviceHostMetadata -or $serviceHostMetadata.file -ne $serviceHostAsset.name -or $serviceHostMetadata.sha256 -notmatch '^[0-9a-fA-F]{64}$') {
            throw "HU release $($release.tag_name) has invalid Windows service-host metadata."
        }
    }

    [pscustomobject]@{
        Repository = $ReleaseRepository
        Package = $Package
        Version = $version
        Commit = $manifest.commit
        Artifact = $artifact
        ArtifactAsset = $artifactAsset
        ServiceHostAsset = $serviceHostAsset
        ServiceHostMetadata = $serviceHostMetadata
    }
}

function Save-VerifiedArtifact($Release, [string]$Directory) {
    $path = Join-Path $Directory $Release.Artifact.file
    Invoke-WebRequest -Uri $Release.ArtifactAsset.browser_download_url -OutFile $path
    $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $Release.Artifact.sha256.ToLowerInvariant()) {
        throw "$($Release.Package) artifact checksum mismatch."
    }
    $path
}

function Install-HrRuntime([string]$Wheel, $Release, [string]$HelixRoot) {
    $packageRoot = Join-Path $HelixRoot 'helix-releases'
    $releaseRoot = Join-Path $packageRoot (Join-Path 'releases' $Release.Version)
    $venv = Join-Path $releaseRoot '.venv'
    New-Item -ItemType Directory -Force -Path $releaseRoot | Out-Null

    if (-not (Test-Path (Join-Path $venv 'Scripts\python.exe'))) {
        & py -3 -m venv $venv
        if ($LASTEXITCODE -ne 0) { throw 'Python 3 and the venv module are required.' }
    }
    $python = Join-Path $venv 'Scripts\python.exe'
    & $python -m pip install --disable-pip-version-check --no-index --no-deps --force-reinstall $Wheel *> $null
    if ($LASTEXITCODE -ne 0) { throw 'Installing the HR wheel failed.' }

    Set-Content -LiteralPath (Join-Path $releaseRoot 'release.json') -Encoding utf8 -Value (@{
        package = $Release.Package; version = $Release.Version; commit = $Release.Commit
        installed_at_utc = [DateTime]::UtcNow.ToString('o')
    } | ConvertTo-Json)
    Set-Content -LiteralPath (Join-Path $packageRoot 'installation.json') -Encoding utf8 -Value (@{
        schema = 1; package = $Release.Package; active_release = $Release.Version
        python = $python; root = $packageRoot
    } | ConvertTo-Json)
    Join-Path $venv 'Scripts\hr.exe'
}

function Install-WindowsServiceHost($HuRelease, [string]$TempRoot, [string]$HelixRoot) {
    $archive = Join-Path $TempRoot $HuRelease.ServiceHostAsset.name
    Invoke-WebRequest -Uri $HuRelease.ServiceHostAsset.browser_download_url -OutFile $archive
    $actual = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $HuRelease.ServiceHostMetadata.sha256.ToLowerInvariant()) { throw 'HU Windows service-host checksum mismatch.' }
    $publishRoot = Join-Path $TempRoot 'service-host-publish'
    Expand-Archive -LiteralPath $archive -DestinationPath $publishRoot -Force
    $serviceHostExecutable = Join-Path $publishRoot 'HelixUpdaterService.exe'
    if (-not (Test-Path $serviceHostExecutable)) { throw 'The HU release service-host asset did not contain HelixUpdaterService.exe.' }
    $destination = Join-Path $HelixRoot 'service-host\HelixUpdaterService.exe'
    New-Item -ItemType Directory -Force -Path (Split-Path $destination) | Out-Null
    Copy-Item -LiteralPath $serviceHostExecutable -Destination $destination -Force
    $destination
}

Assert-Administrator
$temp = Join-Path ([IO.Path]::GetTempPath()) ('helix-hr-install-' + [guid]::NewGuid())
$helixRoot = Join-Path $env:ProgramData 'Helix'
$config = Join-Path $helixRoot 'helix-updater.toml'
New-Item -ItemType Directory -Force -Path $temp, $helixRoot | Out-Null

try {
    $hrRelease = Get-VerifiedRelease -ReleaseRepository $Repository -Package 'helix-releases'
    $hrWheel = Save-VerifiedArtifact $hrRelease $temp
    $hr = Install-HrRuntime $hrWheel $hrRelease $helixRoot

    $huRelease = Get-VerifiedRelease -ReleaseRepository $Repository -Package 'helix-updater' -SkipSourceVerification
    $serviceHost = Install-WindowsServiceHost $huRelease $temp $helixRoot

    $env:HELIX_WINDOWS_SERVICE_HOST = $serviceHost
    $env:HELIX_UPDATER_CONFIG = $config
    $env:HELIX_DEVELOPMENT_CATALOG = Join-Path $helixRoot 'development\catalog'

    & $hr install hu --profile production --repository "$Owner/$Repository"
    if ($LASTEXITCODE -ne 0) { throw 'HR failed to install HU.' }

    $bin = Join-Path ${env:ProgramFiles} 'Helix\bin'
    New-Item -ItemType Directory -Force -Path $bin | Out-Null
    $shim = Join-Path $bin 'hr.cmd'
    Set-Content -LiteralPath $shim -Encoding ascii -Value "@echo off`r`n`"$hr`" %*`r`n"
    $machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    if (($machinePath -split ';') -notcontains $bin) {
        [Environment]::SetEnvironmentVariable('Path', (($machinePath.TrimEnd(';') + ';' + $bin)), 'Machine')
    }

    Write-Output "HR $($hrRelease.Version) installed under $helixRoot."
    Write-Output "HU production installation was delegated to HR; service host: $serviceHost"
}
finally {
    Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue
}
