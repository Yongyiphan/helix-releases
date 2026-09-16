# HDC–HR release contract

Protocol version 1 uses two JSON records:

1. HDC reads the HR contract, verifies readiness, and writes a complete `handoff/<request-id>.json`.
2. HDC invokes `hr packages <handoff-path>`.
3. HR verifies the handoff's contract hash and source commit.
4. HR copies the exact source checkout into a temporary workspace, runs every test command,
   executes the build command, validates exactly one wheel, and publishes a manifest/checksum.

The handoff is not a shell script. Commands are argument arrays and execute with `shell=False`.
This keeps HR reproducible and prevents a release contract from becoming an unreviewed arbitrary
privileged command path.

Two failed release hotfix attempts transition the request to
`REINVESTIGATION_REQUIRED`. HDC automatically collects a diagnostic bundle containing host,
Python, repository status, and commit evidence. Reinvestigation or explicit human intervention
must happen before the release lock can be considered complete.
