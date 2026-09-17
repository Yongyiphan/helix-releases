$ErrorActionPreference = 'Stop'
$Owner = 'Yongyiphan'; $Repo = 'helix-releases'; $Api = "https://api.github.com/repos/$Owner/$Repo"
$Temp = Join-Path ([IO.Path]::GetTempPath()) ('helix-hr-install-' + [guid]::NewGuid())
New-Item -ItemType Directory -Path $Temp | Out-Null
try {
  $branch = Invoke-RestMethod "$Api/branches/main"
  if ($branch.commit.author.login -ne $Owner -and $branch.commit.committer.login -ne $Owner) { throw 'HR catalog main is not owned by Yongyiphan' }
  if (-not $branch.commit.commit.verification.verified) { throw 'HR catalog main commit is not GitHub-verified' }
  $catalog = $branch.commit.sha
  $versions = Invoke-RestMethod "$Api/contents/releases/helix-releases?ref=$catalog"
  $version = ($versions | Where-Object { $_.type -eq 'dir' } | ForEach-Object name | Sort-Object {[version]$_} -Descending | Select-Object -First 1)
  if (-not $version) { throw 'HR catalog has no HR release' }
  $base = "https://raw.githubusercontent.com/$Owner/$Repo/$catalog/releases/helix-releases/$version"
  $manifest = Invoke-RestMethod "$base/manifest.json"
  if ($manifest.schema -ne 1 -or $manifest.package -ne 'helix-releases' -or $manifest.channel -ne 'stable') { throw 'Invalid HR manifest identity' }
  $artifact = $manifest.artifacts.'windows-x86_64'; if (-not $artifact) { $artifact = $manifest.artifacts.any }
  if (-not $artifact.file -or $artifact.file -notmatch '^[A-Za-z0-9_.+-]+$' -or $artifact.sha256 -notmatch '^[0-9a-fA-F]{64}$') { throw 'Invalid HR artifact metadata' }
  $source = Invoke-RestMethod "$Api/commits/$($manifest.commit)"
  if ($source.author.login -ne $Owner -and $source.committer.login -ne $Owner) { throw 'HR provenance is not associated with Yongyiphan' }
  $wheel = Join-Path $Temp $artifact.file
  Invoke-WebRequest "$base/$($artifact.file)" -OutFile $wheel
  if ((Get-FileHash $wheel -Algorithm SHA256).Hash.ToLower() -ne $artifact.sha256.ToLower()) { throw 'HR artifact checksum mismatch' }
  $bootstrap = Join-Path $Temp 'install-hr.ps1'
  Invoke-WebRequest "https://raw.githubusercontent.com/$Owner/$Repo/$catalog/install/windows/install-hr.ps1" -OutFile $bootstrap
  & $bootstrap -Wheel $wheel
} finally { Remove-Item -LiteralPath $Temp -Recurse -Force -ErrorAction SilentlyContinue }
