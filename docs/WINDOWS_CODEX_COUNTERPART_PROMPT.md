# Windows Codex counterpart prompt: Helix HU/HR

Use this document as the implementation brief for the Windows counterpart of Helix HU and HR.
The Linux Milestone 1 baseline is complete; Windows is the next platform milestone.

## Starting baseline

The verified Linux baseline is HU/HR `0.1.1`:

- HU: `helix-updater-v0.1.1`
- HR: `helix-releases-v0.1.1`
- HU source: `Yongyiphan/helix-updater` merged main commit
  `47a3bbd2c0f851b043f89baae860ff7de986fb32`
- HR source: `Yongyiphan/helix-releases` merged main commit
  `750b941e0fab7f51e286f592d8f2a962df23f261`
- Linux production has successfully tested HR/HU discovery, download, digest verification,
  activation, HU self-update, HR update, trigger wake-up, service restart, and health status.

Pull both repositories before starting. Read the current HU Windows guide, HR release contract,
ADR-HR-HU-001, ADR-HR-HU-002, ADR-HR-HU-003, and the shared HX-ADR-022/HX-ADR-023 decisions.
Treat repository code as the source of truth when this prompt and an older example disagree.

## Mission

Implement and validate the Windows counterpart for:

```text
HR: build, validate, publish, and provide the installation CLI
HU: discover, verify, download, stage, activate, health-check, update, and roll back
```

Do not move update authority back into HDC. HDC remains outside this milestone except as a
release-target compatibility case. Do not claim Windows readiness from unit tests alone.

## Canonical Windows layout

Production component roots use the same namespace rule as Linux: the normal production root is
the Helix root itself, without a `production` component directory.

```text
Production payloads:
  C:\Program Files\Helix\updater
  C:\Program Files\Helix\helix-releases
  C:\Program Files\Helix\hdc

Development payloads:
  C:\Program Files\Helix\development\updater
  C:\Program Files\Helix\development\helix-releases
  C:\Program Files\Helix\development\hdc

Shared config:
  C:\ProgramData\Helix\helix-updater.toml

Production mutable data:
  C:\ProgramData\Helix\production\...

Development mutable data:
  C:\ProgramData\Helix\development\...
```

Use `installation.json` or an equivalent Windows activation record instead of Unix symlink
assumptions. Production and development must have separate services, state, caches, locks,
control pipes, catalogs, channels, and component targets.

## Required implementation

1. Complete the Windows HU lifecycle against the Windows service manager: stop and wait, stage,
   activate, start, wait for health, record state, and restore the previous release on failure.
2. Make Python-wheel staging safe on Windows. Generated virtual-environment launchers must point
   at the final release directory, not a temporary staging path.
3. Implement one explicit HR Windows bootstrap that installs HR and production HU together.
4. Implement a separate source-checkout development bootstrap that touches only the development
   profile.
5. Define service identities and ACLs for `HelixUpdater` and `HelixUpdaterDev`. Normal updates
   must be headless and must not require an interactive UAC/password prompt.
6. Preserve public HTTPS release discovery without credentials. Never copy HDC credentials into a
   service identity and never put tokens in source, config examples, logs, or service arguments.
7. Add Windows artifact/manifest handling and ensure HR publishes a Windows-compatible artifact
   only after it has passed a real Windows rehearsal.
8. Keep the Linux layout and behavior unchanged.

## Development-first test sequence

Use a local development catalog and a dev-channel candidate first:

```text
source change
  -> build a Windows artifact
  -> HR validates the handoff and writes a local dev catalog
  -> HU development downloads/verifies/activates it
  -> trigger the development profile
  -> inspect service health and activation state
  -> exercise failed activation and rollback
```

Do not publish a stable release merely to debug Windows. Production testing comes only after the
development rehearsal passes and requires an intentional versioned release.

## Acceptance evidence

On a real Windows machine, record commands, commits, artifact digests, paths, service identities,
and observed results for:

- clean HR bootstrap and production HU installation;
- production and development service start after reboot;
- profile path/ACL/source/channel isolation;
- HR updating HU through the production profile;
- HU downloading, digest-verifying, activating, and health-checking a component;
- trigger wake-up without treating the trigger as an artifact transport;
- failed health-check rollback and service recovery;
- preservation of active/previous releases and safe cleanup of older releases;
- headless operation when no interactive user is logged in;
- uninstall/preserve-state and explicit purge behavior.

Use fake service/filesystem boundaries for unit tests, then a bounded disposable Windows rehearsal
for SCM, ACL, reboot, service identity, download, activation, and rollback behavior.

## Deliverables

Return:

1. HU and HR source changes with focused and full test results.
2. Updated Windows installation, configuration, service, release, and rollback documentation.
3. A Windows rehearsal record containing exact commits, artifact SHA-256 values, service state,
   active/previous versions, and rollback evidence.
4. A clear list of remaining gaps. Do not mark Windows production-ready until the real-host
   acceptance evidence exists.

Do not modify or delete the Linux production installation while completing this work.
