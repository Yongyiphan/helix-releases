# Helix Releases (HR)

HR is the on-demand build, publication, and installation interface for Helix components. It is
not a background service. HU remains the privileged installation and runtime-management engine.

Build, release, and deployment are separate lifecycle stages:

```text
source and tests -> HR validates and builds -> intentional publication -> HU installs and operates
```

HR validates the source commit, release contract, recipe, tests, and artifact before publication.
Automation and direct operator workflows use the same validation path. HR does not query HDC and
does not move installation authority into HDC.

The current validated production baseline is:

| Component | Version |
| --- | --- |
| HR | 0.2.1 |
| HU | 0.2.0 |
| HN | 0.1.0 |

See [build/release/deploy separation](docs/decisions/HX-ADR-022-build-release-deploy-separation.md)
for the lifecycle decision.

## Release layout

Each published component version has one GitHub Release:

```text
<package>-v<version>/
  <package>-<version>.manifest.json
  <artifact>
```

Production discovery reads GitHub Release assets only. The checked-out
`releases/<package>/<version>/` catalog is for explicit local development rehearsals. Manifests
identify the package, version, commit, platform, artifact, and SHA-256 digest.

HR publishes through the authenticated `gh` CLI. HU reads public releases anonymously and never
receives publication credentials. HR's normal build and publication commands do not require
elevation.

## Installation

Linux production bootstrap:

```bash
curl -fsSL https://raw.githubusercontent.com/Yongyiphan/helix-releases/main/install/linux/install.sh | sudo bash
```

Windows production installation is provided by the HR-owned `install/windows/install.ps1` entry
point. It validates immutable GitHub Release assets, installs versioned HR and HU runtimes, and
installs the native Windows service-host companion before registering the production service.
The validated Windows baseline is HR `0.2.1` with HU `0.2.0`.

Both installers establish the production profile only. Windows source iteration uses the separate
checkout-based development runtime and must not replace or modify the production service.

HR invokes HU through the host elevation mechanism. HU owns verification, activation, health
checks, rollback, service lifecycle, polling, and self-update.

For an isolated local HU development runtime:

```bash
sudo bash install/linux/bootstrap-development.sh
```

The development bootstrap uses separate paths, state, service identity, and channel. It does not
publish a release or alter the production runtime.

## Removal

```bash
sudo install/linux/uninstall.sh
sudo install/linux/uninstall.sh --purge-state
```

The default preserves component state and machine-local configuration. `--purge-state` removes
those as well.

## Protected publication

Recommended GitHub protections are provided in `docs/github-ruleset-main.json` and
`docs/github-ruleset-release-tags.json`. Publication should use a branch and pull request rather
than a direct push to `main`.
