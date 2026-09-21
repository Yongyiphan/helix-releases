# HX-ADR-024: GitHub CLI publishing authentication

- Status: Accepted direction; implementation alignment pending
- Date: 2026-09-21
- Shared decision ID: `HX-ADR-024`
- Affected components: HDC, HR, HU, and the directly tasked Codex manual workflow
- Supersedes: The future GitHub App direction in ADR-008 as a current plan, and any deployment guidance that selects direct API tokens or SSH as HR release authentication. It does not remove HU's anonymous public-release reads.

## Context and rationale

Helix has two release handoff producers: the normal automated HDC workflow and a directly tasked
Codex workflow. Both invoke HR. HR currently publishes through the authenticated `gh` CLI. The
operator already uses a PAT-backed `gh` login, and adding a second publisher transport or credential
system would make clean HDC installation and support harder without a demonstrated need.

SSH keys authenticate Git transport such as clone, fetch, and push. They do not authenticate HR's
GitHub Release API request. A PAT is separate from the SSH key and is held by the `gh` CLI login.

## Decision

1. HDC is the owner of GitHub access for the normal automated development workflow. During a fresh
   HDC installation, provision the operator PAT into the `gh` CLI authentication store for the exact
   operating-system identity that runs HDC and invokes HR. Use the headless token-input flow; do not
   require browser login or a `GH_TOKEN`/`GITHUB_TOKEN` environment variable.
2. HR always uses the authenticated `gh` CLI for release publication. In the HDC lane, HR inherits
   HDC's `gh` executable and saved authentication context. HR does not own a second credential store
   or implement a separate publisher transport.
3. For directly tasked Codex work, HR uses the operator's existing authenticated `gh` CLI context
   under that invocation's operating-system identity. The same `gh` mechanism applies; this does not
   create another publisher integration.
4. The PAT identity must have write access to `Yongyiphan/helix-releases`. The PAT and saved `gh`
   credential must not enter source, configuration examples, TaskPackets, handoffs, logs, or
   artifacts. Setup verifies the saved login with `gh auth status`; an operator may also inspect
   repository permission with `gh repo view`. HR does not require a separate write-access preflight:
   it calls `gh release create` and surfaces GitHub's failure if the credential cannot publish.
5. HU receives no write credential. Public releases are read anonymously. Any exceptional private
   read path for HU is a separate read-only distribution concern and does not authorize publication.
6. Do not select GitHub Apps, raw REST API authentication, `GH_TOKEN`/`GITHUB_TOKEN` runtime
   injection, or SSH-based release authentication for this workflow until a concrete use case is
   recorded and accepted as a new shared decision.

GitHub still carries API and asset-upload traffic over HTTPS. The decision excludes an interactive
browser login and alternate application-level publisher/authentication methods; it does not change
the network protocol used by GitHub's API.

## Contract and implementation alignment

The architectural contract is one publisher path: `hr packages ... --publish-release` calls the
authenticated `gh` CLI. HDC's fresh-install setup provisions the PAT-backed `gh` login for its runtime
identity and checks it with `gh auth status`. When HDC invokes HR, the child process must run as that
identity or receive its `GH_CONFIG_DIR` so it resolves the same saved login. HR does not separately
preflight repository write permission; GitHub's response to the publish command is authoritative.

Current HDC code still contains an opt-in direct API transport selected with
`HDC_GITHUB_AUTH=token` and `GITHUB_TOKEN`. This is an implementation-alignment gap, not an approved
deployment path under this decision. Remove or retire that branch only through a separately reviewed
implementation task that preserves required HDC issue and coordination behavior.

## Migration and compatibility

1. Update shared, HDC, HR, and HU canonical documentation with this decision.
2. Align HDC authentication setup and service-account deployment with the saved `gh` PAT login.
3. Verify `gh auth status`, repository write access, and one disposable HR release publication from
   the HDC execution identity; remove the disposable release and tag after verification.
4. Keep HR publication failure handling intact: `gh` errors surface to the caller, and no failed
   attempt may be reported as published.
5. Review the existing direct API transport for removal after HDC's other GitHub coordination and
   issue capabilities have been proven over the selected `gh` path.

Existing local `gh` logins remain usable. No PAT migration is required when the HDC runtime identity
already has a working PAT-backed `gh` login with the required repository access. HU public-read
behavior and the HR release manifest format do not change.

## Tests and rehearsals

Evidence from 2026-09-21: the worker's saved `gh` login had admin/write access to
`Yongyiphan/helix-releases`. HR built and published a disposable probe release through `gh`, including
the wheel and manifest assets. The release `helix-hr-write-probe-20260921-v0.0.1` and its tag were
deleted afterward; GitHub confirmed both were absent. No production component version was used.

- Fresh HDC install provisions `gh` authentication headlessly for the HDC runtime identity without
  logging token contents.
- `gh auth status` and a read-only repository-permission check pass under that identity.
- HR creates a disposable tagged release and uploads artifact plus manifest through its `gh` path;
  cleanup deletes both release and tag and confirms they are absent.
- Missing, expired, or insufficient credentials cause the workflow to stop with the `gh` failure
  surfaced and no successful-publication record.
- HR invoked by HDC resolves the same saved `gh` login; HU receives no publisher credential.

## Rollout and rollback

Roll out the HDC credential setup and HR inherited-context check before relying on unattended
publication. If headless setup or credential lookup fails, stop publication and repair the saved
`gh` login under the HDC runtime identity. Do not silently switch to direct API tokens, a GitHub App,
or SSH authentication. Reconsider alternatives only through a new evidence-backed shared decision.

## GitHub execution references

The one-time disposable publication rehearsal is completed in the 2026-09-21 Codex session. Add an
execution issue here if implementation alignment is scheduled; this decision is the durable design
truth.
