# Helix Releases (HR)

HR is the on-demand build and publication factory for Helix components. It is
not a runtime service and it does not install production software.

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
hdc release publish hdc --catalog /path/to/helix-releases
```

The catalog layout is independent per package and version:

```text
releases/<package>/<version>/manifest.json
releases/<package>/<version>/<artifact>
```

This allows HC, HEP, HDC, HR, and HU to release independently while sharing
one public repository. HU selects only packages subscribed on its host.

HR currently publishes to a local catalog checkout. A later GitHub adapter may
commit and push this same layout; HR must not contain GitHub credentials.

## Privileged bootstrap installation

Once HR itself is available on a host, it can install a published baseline
from a local clone of the public catalog:

```bash
sudo hr install list --catalog /path/to/helix-releases --channel stable
sudo hr install hu --catalog /path/to/helix-releases --channel stable
sudo hr install hdc --catalog /path/to/helix-releases --channel stable
```

The initial HR bootstrap is necessarily a one-time chicken-and-egg step:

```bash
sudo install/linux/install-hr.sh dist/helix_releases-0.1.0-py3-none-any.whl
```

`hr` and `hu` are accepted aliases for `helix-releases` and `helix-updater`.
Installation is elevated, checksum-verified, versioned, and atomic. HR does
not require GitHub credentials for this path. After HU is installed and
configured, normal updates should be performed by HU; HR's install command is
the bootstrap/recovery interface.
