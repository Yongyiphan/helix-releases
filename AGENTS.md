# Helix Releases (HR)

HR is an on-demand build, publication, and privileged bootstrap CLI. It does
not modify source code or run a background service. HDC owns the release
handoff; HR validates and executes it. HU remains the normal authority for
ongoing production installation and lifecycle management, while `hr install`
is the recovery/bootstrap path for a blank or legacy host.

`hr install` always requires elevation. It reads the public catalog, verifies
the platform artifact checksum, installs into a versioned target, atomically
switches `current` (or the Windows installation record), and restarts the
known service when one is already active. This makes `hr install hdc` a safe
way to replace an existing HDC baseline before HU is available.

Keep builds reproducible, execute only structured command arguments, and use
temporary output directories in tests. Do not add GitHub credentials to HR.
