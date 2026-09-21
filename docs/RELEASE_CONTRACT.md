# HR release handoff contract

GitHub publishing authentication follows shared
[`HX-ADR-024`](decisions/HX-ADR-024-github-cli-publishing-auth.md): HR always publishes
through the authenticated `gh` CLI. HDC owns the normal PAT-backed saved login and HR inherits that
context; directly tasked Codex uses the operator's existing `gh` login. HR does not select a separate
API-token transport or credential store. HU never receives the publishing credential.

The shared actor and Hermes-optional decision is
[`HX-ADR-023`](decisions/HX-ADR-023-release-handoff-actors.md).

## Lifecycle boundary (HX-ADR-022)

Build, release, and deployment are separate operations. HR must support building and validating a
local artifact without publishing it; a build or Git push alone does not imply production readiness.
The ordinary development loop installs local artifacts into an isolated, production-like development
runtime. GitHub Releases are intentional production-distribution outputs, not a runtime debugging
mechanism. Production consumes an official release through the HU/HR installation path.

Release handoff records should identify the exact source commit, artifact digest, validation evidence,
and intentional release version. Publication is explicit and must not be an implicit side effect of a
local build. See the shared [HX-ADR-022 decision](../../docs/decisions/ADR-022-development-build-release-deploy.md).

The current Linux HR CLI/build and HU dev-profile features are foundations, not by themselves proof
that every component has production-fidelity service validation. Windows remains documentation-only.

Protocol version 1 uses a contract-bound JSON handoff. Either lane may assemble it:

1. Automated HDC may read the HR contract and assemble the handoff, optionally using Hermes as a
   reasoning or evidence-gathering tool.
2. When Codex is directly tasked by a user, it may assemble the same handoff manually and invoke HR
   directly. No HDC task state or Hermes result is required for this lane.
3. HR verifies the handoff's contract hash, recipe, required paths, and source commit. Optional
   `verification` metadata is informational; HR's own checks determine whether packaging proceeds.
4. HR copies the exact source checkout into a temporary workspace, runs every contract test command,
   executes the build command, validates exactly one wheel, and publishes a manifest/checksum.

Hermes is not a release gate. HR does not trust a `hermes: passed` marker as a substitute for
contract validation, source checks, tests, or artifact validation. Both handoff producers must
provide the same complete inputs; HR remains the authority for deterministic build validation.

Before publication, the installed HR wheel must also pass a disposable rehearsal. The rehearsal
installs HR into a temporary virtual environment and runs a handoff against a temporary component;
it must not depend on the source checkout's sibling HDC/HU repositories or mutate a production root.

HR and HU share profile-scoped cross-process installation locks (`/run/helix/production/install.lock`
and `/run/helix/development/install.lock` on Linux. A future Windows port must define equivalent
ProgramData paths; Windows support is deferred and not implemented by the current bootstrap.
HR's privileged bootstrap, HU staging, and HU activation hold the selected lock across their
mutation boundary. Rehearsals override it with a temporary path via
`HELIX_INSTALL_LOCK_PATH` and exercise two concurrent requests for the same artifact. An identical
already-staged artifact is idempotent; a same-version artifact with a different digest is rejected.

The handoff is not a shell script. Commands are argument arrays and execute with `shell=False`.
This keeps HR reproducible and prevents a release contract from becoming an unreviewed arbitrary
privileged command path.

Two failed release hotfix attempts transition the request to
`REINVESTIGATION_REQUIRED`. HDC automatically collects a diagnostic bundle containing host,
Python, repository status, and commit evidence. Reinvestigation or explicit human intervention
must happen before the release lock can be considered complete.
## GitHub Release publication

The production publication surface is the public GitHub Releases page of
`Yongyiphan/helix-releases`. HR creates one independent release per component and version using
the tag `<component>-v<version>`, for example `helix-updater-v0.1.0`.

Official release versions use `MAJOR.MINOR.PATCH` (three numeric components, such as `1.2.3`).
Increase MAJOR for an incompatible change to a component's published contract; MINOR for a
backward-compatible capability; and PATCH for a backward-compatible correction. Each component
versions independently. A published tag is unique and immutable: publishing must not replace an
existing component/version release. Routine local development iterations do not bump the package
version; HR rebuilds the local artifact and HU replaces the development runtime's working build.
Temporary local build IDs are not release versions. Version changes are reserved for intentional
release preparation, not debugging attempts.

Each release contains the built artifact and one `<component>-<version>.manifest.json` asset. The
manifest remains the authoritative package identity, platform artifact filename, SHA-256 digest,
channel, source commit, health-check, and rollback metadata. A release does not require a commit
to the catalog repository.

Production HR and HU discovery reads GitHub Release metadata and downloads the artifact and
manifest from that release's assets. It does not read `releases/<component>/<version>/` from the
repository's source branch. That directory remains an explicit local catalog for development
runtime rehearsals only (`--catalog`); new HR publication uses `hr packages <handoff-path>` by
default, and `--no-publish-release` keeps a rehearsal local. Historical source-tree catalog entries
are migration input and should be removed only after their required assets have been verified on the
Release page.

During stabilization, the development HU service consumes the local HR catalog. Explicit HR
component installs select and download the artifact plus manifest, then pass both to the selected
HU profile for revalidation and installation. `--profile development` selects the persistent dev
runtime; production is the default and is never synchronized automatically. The machine-local
combined HU TOML and migration behavior are specified by ADR-HR-HU-001 in HR and HU.

Publishing a GitHub Release does not itself broadcast a trigger. After a release is published and
verified, the release operator (or Codex acting in place of HDC for a development workflow) invokes
HU's profile-scoped `trigger` command. The local HU listener broadcasts the wake-up pulse; receiving
HU services then independently discover and verify against their configured source and channel.
For a production release, Codex invokes:

```bash
helix-updater --config /etc/helix/helix-updater.toml --profile production \
  --source codex trigger PACKAGE
```

This is a separate post-publish action, not an HR publish side effect.
