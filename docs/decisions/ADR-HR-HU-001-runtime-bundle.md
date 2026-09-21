# ADR-HR-HU-001 — HR/HU bootstrap bundle and dual runtime profiles

Status: superseded by ADR-HR-HU-003; retained as the original bundle decision

HR and HU are one installation/distribution bundle with separate process roles. HR is the public,
on-demand CLI and only ecosystem entry point. HU is the elevated persistent service and owns
verification, staging, activation, service lifecycle, health checks, rollback, automatic polling,
and HU self-update. On explicit `hr install`, HR selects and downloads the immutable artifact and
manifest, then hands both to HU; HU revalidates identity and digest before mutation.

The implemented Linux HR entrypoint installs HR first, then bootstraps HU from the same public
release source. The bootstrap establishes production and development HU runtimes and services.
Future PowerShell and batch entrypoints must preserve this ordering and contract; Windows work is
deferred and not part of this implementation. HR remains a CLI and is managed as a HU package, not
a daemon.

One machine-local, untracked TOML contains `[profiles.production]` and `[profiles.development]`.
Each profile owns independent paths, source/channel, package subscriptions, state, downloads,
locks, control endpoint, and service identities. Production consumes stable public releases;
development consumes the local HR catalog on the dev channel. Legacy flat TOML is preserved as a
`.pre-profiles` backup and migrated into production; development entries are derived with isolated
roots and service suffixes. Existing production package roots and state are preserved during this
first config migration.

Migration order: validate the combined profile schema; back up/migrate any legacy HU TOML; install
the versioned HU wheel into each profile root; seed each profile's installed HU state; write/register
both services; then enable and start them. An invalid or partial config must fail before either
service starts. HR must never silently map a local/dev catalog into production. Promotion is an
explicit production-profile operation and is not an automatic dev-to-prod sync.

Staged development recovery on a host with an active legacy production HU is a separate path: create
the canonical paired TOML from the legacy production settings, keep the original legacy file and its
`.pre-profiles` backup in place, then install/enable/restart only the development unit. During this
staging window the old production process continues to use its legacy config; it is not yet consuming
the paired TOML. Do not remove or replace the legacy path until a separately approved production
cutover has registered the production unit against the paired TOML and the new HU runtime. This
temporary two-file migration bridge preserves production's automatic restart path while dev is
rehearsed; the steady state remains both HU services reading the same paired TOML.

After the paired config exists, adding or repairing the development runtime while production HU is
active must install/enable/restart only `helix-updater-dev.service`; it must not rewrite the
production unit or restart the production service. If production is still using a legacy flat
config, a development-only request fails with a migration-required message instead of implicitly
restarting production.

Compatibility: flat HU TOML remains readable as production-only for one migration window. Profile
TOML requires an explicit `--profile`. Artifacts remain immutable; HU rejects package/channel/hash
mismatch. GitHub publishing remains a separate explicit HR operation.

Windows requirements (documented, not implemented): provide one untracked TOML with the same
production/development segments; disjoint Program Files runtime roots and ProgramData state,
download, lock, and log paths; two independently managed elevated services; safe legacy-config
migration with backup; bootstrap HU alongside HR; and detached, health-acknowledged HU self-update
with rollback. The Windows uninstaller must remove both services and runtime binaries while
preserving state/configuration by default, with explicit purge semantics. Windows entrypoints must
not be advertised as production-ready before disposable install/update/rollback rehearsals pass.

Validation: parser/migration tests, HR artifact-handoff tests, HU digest/profile tests, full package
suites, then a bounded persistent dev-service rehearsal covering update, health, rollback, HU
self-update, restart, and HR update. Production promotion follows only after rehearsal evidence and
operator approval. Rollback retains the original TOML backup, previous versioned runtime, and
existing production component roots. No production services or public releases are changed by this
decision's implementation work.
