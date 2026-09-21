#!/usr/bin/env bash
set -euo pipefail

# This entrypoint is intentionally available only from an HR source checkout.
# The public install.sh remains a production-only bootstrap.
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
python="$repo_root/.venv/bin/python"
if [[ ! -x "$python" ]]; then
    echo "HR source environment not found: $python" >&2
    echo "Create the checkout venv and install the HR project before bootstrapping dev." >&2
    exit 2
fi
if [[ $EUID -ne 0 ]]; then
    echo "Run the development bootstrap with sudo; it installs only the HU development profile." >&2
    exit 2
fi

export PYTHONPATH="$repo_root/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$python" -m helix_releases.cli install hu --profile development --channel dev "$@"
