# ADR-HR-HU-003: Production-only bootstrap and HU release pulses

Status: accepted for Linux implementation
Components: HR, HU
Supersedes: the bootstrap scope in ADR-HR-HU-001
Shared record: `helix-updater/docs/decisions/ADR-HR-HU-003-production-bootstrap-and-release-pulses.md`

## Decision

The public HR installer is a production entrypoint. It installs stable HR and stable HU, creates
the canonical machine-local TOML with both profile tables, and installs/enables/restarts only the
production HU runtime and service. It must not install a dev-channel binary, create the dev HU
runtime, or start the dev service. Configuring both profiles in the TOML does not activate both.

Development has a separate Linux bootstrap available only from an HR source checkout. It invokes
that checkout's HR CLI to install the HU development profile and must leave production untouched.
After initial setup, direct HU source iteration uses HU's `scripts/deploy-dev-runtime.sh`; it does
not require publishing a release. The public HR entrypoint never requires a development HR version
or a source checkout. Windows behavior remains documentation-only.

Publishing and broadcasting are separate actions. HR creates the GitHub Release; after publication
is confirmed, the release operator—or Codex acting in place of HDC for that workflow—invokes the
selected HU profile's trigger API. HU's local listener broadcasts the pulse. Peer listeners wake
and independently inspect their configured package, source, and channel. A pulse is only a wake-up
hint, is not rebroadcast by receivers, and cannot install the release by itself. HR publication
must not implicitly trigger production installation.

## Migration, validation, and rollback

Keep one paired untracked TOML. Existing production settings and legacy-config migration remain
authoritative. Production bootstrap seeds production HU state and installs only
`helix-updater.service`; source dev bootstrap seeds and installs only the development profile.
Regression tests must prove each path leaves its peer service and runtime untouched. Verify the
production installer on a disposable Linux host, then verify the separate dev bootstrap and the
HU trigger/listener round trip. No live production service, GitHub release, or HDC repository is
modified by this decision's implementation.

Rollback is profile-scoped: remove/restore only the profile being changed, preserve the paired TOML
and its migration backup, and never restart the peer service as a side effect.
