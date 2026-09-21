# ADR-HR-HU-002: Isolated development runtime for HR and HU

- Status: Accepted for Linux-first implementation
- Date: 2026-09-20
- Components: HR, HU
- Supersedes: none

This is the shared HR copy of ADR-HR-HU-002. HU's canonical copy is maintained at
`helix-updater/docs/decisions/ADR-HR-HU-002-isolated-development-runtime.md`.

## Context and decision

Repeatedly publishing HU releases to discover basic integration defects is not an acceptable
development loop. HU must have a persistent development service that exercises the same update
logic as production while being unable to affect production. Production-feed mirroring is not a
requirement: the dev service may use a local candidate catalog and its own trigger/network. The
source of candidates is an implementation detail so long as the dev runtime can exercise update,
failure, rollback, and HU self-update paths before a stable release is promoted.

Use one machine-local, untracked TOML with `[profiles.production]` and
`[profiles.development]`. Keep both profiles' runtime roots, state, downloads, locks, control
sockets, services, and package targets disjoint. HU validates profile target boundaries before
performing privileged actions.

## Responsibilities and locations (Linux)

- HR checkout: `/home/mcadmin/MainPP/helix/helix-releases`; ordinary iteration runs
  `.venv/bin/hr` directly. HR is a CLI, not a daemon. Local patches do not require publication.
- HU checkout: `/home/mcadmin/MainPP/helix/helix-updater`; tests run from source, but the persistent
  dev service runs an installed HU runtime at `/opt/helix/development/updater`.
- Paired machine-local config: `/etc/helix/helix-updater.toml`, untracked. Production and
  development profiles share the file but not runtime authority or mutable paths.
- Dev service: `helix-updater-dev.service`; dev component targets remain below
  `/opt/helix/development/`; state/cache/locks/control sockets remain below their corresponding
  `/var/lib/helix/development`, `/var/cache/helix/development`, and `/run/helix/development`
  roots.
- A separate HU-managed HR target at `/opt/helix/development/helix-releases` is only for HR package
  lifecycle tests. It is not the working CLI checkout.
- The user-writable local dev catalog is
  `/home/mcadmin/.local/state/helix/development/catalog`; HU dev receives read access. Populate it
  from an explicit handoff with
  `.venv/bin/hr packages <handoff> --catalog /home/mcadmin/.local/state/helix/development/catalog
  --no-publish-release`, which builds without publishing a GitHub release.

Dev HU may use a local HR catalog and its own trigger/network. It is not required to listen to
production notifications or consume production's feed. It runs the same update, verification,
drain, health, rollback, and self-update logic, but must reject any target or service outside the
development profile before mutation. The production service/config remain untouched while dev is
installed, exercised, or rolled back.

For ordinary HU source iteration, run `bash scripts/deploy-dev-runtime.sh` from the HU checkout.
This locally builds and installs the current source into a uniquely named dev-only directory under
`/opt/helix/development/updater/releases/`, switches and restarts only
`helix-updater-dev.service`, waits for startup, and records the active build with HU's `adopt`
operation. If startup or adoption fails, it restores the previous dev link. Keeping local builds
inside `releases/` preserves HU's self-update containment and rollback checks. It does not publish a
release. HR remains directly runnable from its repository venv.

## Release and migration policy

Install local HR/HU candidates into dev for ordinary iteration. Publish a dev-channel release only
for an intentional remote discovery/download/verification/HU-self-update rehearsal. Publish or
promote a stable release only after the persistent dev service passes its acceptance checks. HR
remains the desktop bootstrap entrypoint; a development bootstrap may install only the dev profile
while production is active. Production cutover is a separate explicit operation.

A routine source iteration does not increment the package version. Rebuild the local artifact and
replace the development runtime's working build; an implementation-generated local build ID may
distinguish a rollback checkpoint but is not a package/release version. Record the artifact digest
and accurate source provenance, including any local uncommitted changes. A separate remote
discovery/self-update rehearsal must not consume or advance the official stable version sequence.

Migration order: preserve current production config/service; create the paired untracked TOML while
retaining the legacy config; install HU under the dev root; enable only the dev service; rehearse
local-catalog updates, task drain, health, rollback, reboot persistence, and dev HU self-update;
then consider stable promotion and a separate production cutover. Dev rollback removes/disables
only dev-owned files/service and never changes production.

## Lifecycle clarification (HX-ADR-022)

This ADR establishes the isolated HU dev profile but does not by itself establish production-fidelity
artifact validation. Ordinary HU source iteration should converge on locally built artifacts
installed into that isolated service, with production-like service identity and manager behavior.
The local-catalog-to-production promotion described above is superseded as the routine lifecycle:
normal production deployment follows an intentional GitHub Release. Local production promotion is
only an explicitly authorized migration/recovery exception. See the shared
[HX-ADR-022 decision](../../../docs/decisions/ADR-022-development-build-release-deploy.md).

## Compatibility and Windows handoff

Existing production runtime remains supported during the staged migration. Windows implementation
is deferred; its docs must carry this same responsibility/isolation contract to the Windows-host
Codex.
