# HDC–HR release contract

Protocol version 1 uses two JSON records:

1. HDC reads the HR contract, verifies readiness, and writes a complete `handoff/<request-id>.json`.
2. HDC invokes `hr packages <handoff-path>`.
3. HR verifies the handoff's contract hash and source commit.
4. HR copies the exact source checkout into a temporary workspace, runs every test command,
   executes the build command, validates exactly one wheel, and publishes a manifest/checksum.

Before publication, the installed HR wheel must also pass a disposable rehearsal. The rehearsal
installs HR into a temporary virtual environment and runs a handoff against a temporary component;
it must not depend on the source checkout's sibling HDC/HU repositories or mutate a production root.

HR and HU share a cross-process installation lock (`/run/helix/install.lock` on Linux; the
equivalent shared path on Windows). HR's privileged bootstrap, HU staging, and HU activation hold
this lock across their mutation boundary. Rehearsals override it with a temporary path via
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
the tag `<component>-v<version>`, for example `helix-updater-v1.0.7`.

Each release contains the built artifact and one `<component>-<version>.manifest.json` asset. The
manifest remains the authoritative package identity, platform artifact filename, SHA-256 digest,
channel, source commit, health-check, and rollback metadata. A release does not require a commit
to the catalog repository.

The older `releases/<component>/<version>/` folder layout remains a read-compatible fallback during
migration. New HR publication uses `hr packages <handoff-path>` by default; use
`--no-publish-release` for a local-only rehearsal. Catalog commits are only needed when explicitly
requesting the legacy mirror with `--catalog`.
