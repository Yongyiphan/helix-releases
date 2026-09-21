# Helix Releases (HR)

HR is the on-demand build, publication, and public installation interface for
Helix components. It is not a background runtime service. HR and HU are
distributed together, while HU remains the privileged installation engine.
Build, release, and deployment are separate: ordinary development builds local artifacts for an
isolated dev runtime; only an intentional validated release enters the production distribution path.
See [HX-ADR-022](docs/decisions/HX-ADR-022-build-release-deploy-separation.md).

The automated HDC lane and the directly tasked Codex lane converge on HR's same handoff:

```text
HDC automation (Hermes optional) ─┐
                                  ├→ HR validates/tests/builds → intentional publication → HU installs
direct Codex handoff ─────────────┘
```

HR publishes a versioned contract under `contracts/`. Either lane gathers a complete handoff that
matches it; Hermes is optional tooling and its status is not required. HR never queries HDC. HR
refuses dirty source, commit drift, missing handoff files, contract/recipe mismatch, failed tests,
and ambiguous wheel output.

## Local rehearsal

```bash
hdc release request hdc --version 1.3.2 --channel dev
hr packages /path/to/handoff.json
```

The public release page contains one GitHub Release per component/version:

```text
<package>-v<version>/
  <package>-<version>.manifest.json
  <artifact>
```

Each release uses `<package>-v<MAJOR.MINOR.PATCH>` as its unique tag, such as
`helix-updater-v0.1.0`, and carries the manifest and build artifact as release assets. Production
discovery reads Release assets only. The checked-out `releases/<package>/<version>/` catalog is
reserved for explicit local development rehearsals (`--catalog`). HU and HR start from version
`0.1.0`; their previous checked-in catalog artifacts have been removed as part of the reset.
```

This allows HC, HEP, HDC, HR, and HU to release independently while sharing
one public repository. HU selects only packages subscribed on its host.

HR publishes this layout to the public GitHub repository through the authenticated
`gh` CLI. Under [HX-ADR-024](docs/decisions/HX-ADR-024-github-cli-publishing-auth.md),
HDC owns the normal PAT-backed `gh` login and passes that saved context to HR. A directly tasked
Codex workflow uses the operator's existing `gh` login. HU reads public releases anonymously and
never receives the publishing credential. Other publisher authentication methods are out of scope
until a concrete use case is accepted.

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

The public HR bootstrap is a self-fetching, verified production bootstrap. It installs the stable
HR CLI and uses it to install and start only the production HU runtime. The paired machine-local
TOML still defines both profiles, but the dev HU binary, service, state, and cache are not installed
by the public entrypoint:

```bash
curl -fsSL https://raw.githubusercontent.com/Yongyiphan/helix-releases/main/install/linux/install.sh | sudo bash
```

`hr` and `hu` are accepted aliases for `helix-releases` and `helix-updater`.
HR defaults to GitHub Releases in `Yongyiphan/helix-releases` and the `stable`
channel. `--repository`, `--catalog`, `--channel`, and `--profile` remain available
for mirrors and explicit development operations. HR itself is an on-demand CLI, not a daemon. It
selects and downloads the requested artifact and manifest, then hands both to HU. HR invokes HU
through the host elevation mechanism. HU owns verification, activation, health checks, rollback,
service lifecycle, polling, and self-update. HR's normal build and publication commands do not
require elevation.

To establish the isolated dev HU runtime, use an HR source checkout with its venv installed:

```bash
sudo bash install/linux/bootstrap-development.sh
```

This invokes the checkout's HR CLI and installs the dev-channel HU only into the development
profile; it leaves an active production HU service alone. For direct HU source iteration after that
bootstrap, use HU's `scripts/deploy-dev-runtime.sh`, which installs the checkout's code into the
dev service without publishing. HR itself remains an on-demand CLI, not a service.

Implemented production entry: `install/linux/install.sh`. Windows desktop bootstrap is deferred;
future PowerShell and batch entrypoints must install the production profile only. A separate Windows
source-checkout dev bootstrap remains a documentation handoff, not implemented behavior.

The installer pins the public catalog branch, checks that its latest commit is
GitHub-verified and associated with `Yongyiphan`, validates HR's manifest and
provenance, verifies the artifact SHA-256, and only then installs HR. The
Windows equivalent is planned; it is not currently a supported bootstrap path.

To remove Helix installations:

```bash
sudo install/linux/uninstall.sh
sudo install/linux/uninstall.sh --purge-state
```

The default preserves component state and the machine-local HU profile configuration; `--purge-state`
removes those as well. Both production and development HU services/runtimes are removed.

Recommended GitHub protections are provided in
`docs/github-ruleset-main.json` and `docs/github-ruleset-release-tags.json`.
Import both under Settings → Rules → Rulesets. With the `main` ruleset
enabled, publication must use a branch and pull request rather than push
directly to `main`.
