#!/usr/bin/env bash
set -euo pipefail
if [ "${1-}" = "" ]; then exec "$(dirname "$0")/install.sh"; fi
if [ "$(id -u)" -ne 0 ]; then echo "Run with sudo." >&2; exit 1; fi
wheel=$(readlink -f "$1")
root=/opt/helix/production/helix-releases
mkdir -p "$root/releases"
version=$(python3 -c 'import sys,zipfile; from email.parser import BytesParser; z=zipfile.ZipFile(sys.argv[1]); n=next(x for x in z.namelist() if x.endswith(".dist-info/METADATA")); print(BytesParser().parsebytes(z.read(n))["Version"])' "$wheel")
release="$root/releases/$version"
digest=$(sha256sum "$wheel" | awk '{print $1}')
if [ -e "$release" ]; then
    marker="$release/.artifact.sha256"
    if [ -f "$marker" ] && [ "$(<"$marker")" != "$digest" ]; then
        echo "HR version $version is already installed with different artifact contents." >&2
        exit 1
    fi
    if [ ! -x "$release/.venv/bin/hr" ]; then
        python3 -m venv "$release/.venv"
        "$release/.venv/bin/python" -m pip install --no-cache-dir --no-index --force-reinstall "$wheel"
    fi
else
    mkdir -p "$release"
    python3 -m venv "$release/.venv"
    "$release/.venv/bin/python" -m pip install --no-cache-dir --no-index --force-reinstall "$wheel"
fi
printf '%s\n' "$digest" > "$release/.artifact.sha256"
ln -sfn "$release" "$root/current"
ln -sfn "$root/current/.venv/bin/hr" /usr/local/bin/hr
"$root/current/.venv/bin/hr" install hu --profile production
echo "Helix Release bundle $version installed. HR CLI and production HU service are ready."
