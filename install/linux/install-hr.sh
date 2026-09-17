#!/usr/bin/env bash
set -euo pipefail
if [ "${1-}" = "" ]; then exec "$(dirname "$0")/install.sh"; fi
if [ "$(id -u)" -ne 0 ]; then echo "Run with sudo." >&2; exit 1; fi
wheel=$(readlink -f "$1")
root=/opt/helix/helix-releases
mkdir -p "$root/releases"
version=$(python3 -c 'import sys,zipfile; from email.parser import BytesParser; z=zipfile.ZipFile(sys.argv[1]); n=next(x for x in z.namelist() if x.endswith(".dist-info/METADATA")); print(BytesParser().parsebytes(z.read(n))["Version"])' "$wheel")
release="$root/releases/$version"
if [ -e "$release" ]; then echo "HR release already installed: $version"; exit 0; fi
mkdir -p "$release"
python3 -m venv "$release/.venv"
"$release/.venv/bin/python" -m pip install --no-cache-dir --no-index --force-reinstall "$wheel"
ln -sfn "$release" "$root/current"
ln -sfn "$root/current/.venv/bin/hr" /usr/local/bin/hr
echo "Helix Releases $version installed. Use: hr install list"
