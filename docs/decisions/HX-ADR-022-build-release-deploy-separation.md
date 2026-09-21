# HX-ADR-022: Build, release, and production deployment separation

- Status: Accepted architectural direction; implementation alignment is incremental
- Shared decision: HX-ADR-022
- Scope here: HR build, provenance, and publication responsibilities

HR must make local build/validation usable independently of GitHub publication. A local build or
source push is not a release and must not imply production readiness. Repeated development iterations
build local artifacts and validate them in isolated component development installations; they do not
consume production versions.

HR publication is an explicit later transition for an intentional version and exact validated commit
and artifact. The published immutable GitHub Release is the production distribution boundary consumed
by HU. Publication and deployment remain separate. HR's canonical details are in
[`RELEASE_CONTRACT.md`](../RELEASE_CONTRACT.md); the ecosystem decision record is
[`HX-ADR-022`](../../../docs/decisions/ADR-022-development-build-release-deploy.md).

This decision changes documentation/expected workflow only. It does not change HR contracts,
schemas, or implementation, and does not authorize publication. Windows remains documentation-only.
