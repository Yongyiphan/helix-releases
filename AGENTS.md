# Helix Releases (HR)

HR is an on-demand build, publication, and public installation-interface CLI.
It does not modify source code or run a background service. HDC owns the
release handoff; HR validates and executes it. HR and HU are distributed
together; HU is the privileged installation engine and `hr install` is its
public frontend.

The initial HR installer requires elevation because it bootstraps HU. HR's
normal build and publication commands run as the operator. `hr install` reads
the public catalog and delegates verification, versioned activation, service
lifecycle, and rollback to elevated HU.

Keep builds reproducible, execute only structured command arguments, and use
temporary output directories in tests. HR may use the operator's authenticated
GitHub CLI context for publication; never embed credentials in source, logs,
artifacts, or examples.
