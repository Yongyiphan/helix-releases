# Helix Releases (HR)

HR is the on-demand build, publication, and public installation interface for
Helix components. It is not a background runtime service. HR and HU are
distributed together, while HU remains the privileged installation engine.

The release ownership is deliberately split:

```text
HR contract → HDC validates readiness → HDC invokes HR → HR tests/builds → HR publishes → HU installs
```

HR publishes a versioned contract under `contracts/`. HDC reads that contract
during development and, after Hermes/readiness verification, creates a complete
handoff. HDC invokes HR with `hr packages <handoff.json>`; HR never queries HDC.
HR refuses dirty source, commit drift, missing handoff files, failed tests, and
ambiguous wheel output.

## Local rehearsal

```bash
hdc release request hdc --version 1.3.2 --channel dev
hr packages /path/to/handoff.json
```

The catalog layout is independent per package and version:

```text
GitHub Release `<package>-v<version>`:
  <package>-<version>.manifest.json
  <artifact>

The legacy `releases/<package>/<version>/` layout remains readable during migration but is no
longer required for new GitHub Release publication.
```

This allows HC, HEP, HDC, HR, and HU to release independently while sharing
one public repository. HU selects only packages subscribed on its host.

HR publishes this layout to the public GitHub repository using the publisher's
authenticated Git transport. HR installation reads it anonymously. HDC and HR
may use the operator's authenticated `gh` context; HU never receives those
write credentials.

## Privileged bootstrap installation

Once HR itself is available on a host, it can install a published baseline
from a local clone of the public catalog:

```bash
hr install list
hr install hu
hr install hdc
# or install every published component:
hr install all
```

The initial HR bootstrap is a self-fetching, verified one-time bootstrap:

```bash
curl -fsSL https://raw.githubusercontent.com/Yongyiphan/helix-releases/main/install/linux/install.sh | sudo bash
```

`hr` and `hu` are accepted aliases for `helix-releases` and `helix-updater`.
HR defaults to the public `Yongyiphan/helix-releases` catalog and the `stable`
channel. `--repository`, `--catalog`, and `--channel` remain available for
testing, mirrors, and development releases. HR itself stays unprivileged and
invokes HU through the host elevation mechanism. Only the private HU bootstrap
is elevated, because it bootstraps HU and performs the first privileged
activation. After
bootstrap, HU owns ongoing installation, verification, activation, health checks,
rollback, and service lifecycle. HR's normal build and publication commands do
not require elevation.

The installer pins the public catalog branch, checks that its latest commit is
GitHub-verified and associated with `Yongyiphan`, validates HR's manifest and
provenance, verifies the artifact SHA-256, and only then installs HR. The
Windows equivalent is `install/windows/install.ps1`.

To remove Helix installations:

```bash
sudo install/linux/uninstall.sh
sudo install/linux/uninstall.sh --purge-state
```

The default preserves HDC and HU state; `--purge-state` removes it too.

Recommended GitHub protections are provided in
`docs/github-ruleset-main.json` and `docs/github-ruleset-release-tags.json`.
Import both under Settings → Rules → Rulesets. With the `main` ruleset
enabled, publication must use a branch and pull request rather than push
directly to `main`.
