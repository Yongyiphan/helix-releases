#!/usr/bin/env bash
set -eu

if [ "$(id -u)" -ne 0 ]; then
    echo "Run the HR bootstrap as root (for example: sudo $0 PATH_TO_HR_WHEEL)." >&2
    exit 1
fi

wheel=${1:?usage: install-hr.sh PATH_TO_HR_WHEEL}
wheel=$(readlink -f "$wheel")
root=/opt/helix/helix-releases
mkdir -p "$root/releases"
version=$(python3 -c 'import sys, zipfile; from email.parser import BytesParser; z=zipfile.ZipFile(sys.argv[1]); name=next(n for n in z.namelist() if n.endswith(".dist-info/METADATA")); print(BytesParser().parsebytes(z.read(name))["Version"])' "$wheel")
release="$root/releases/$version"
if [ -e "$release" ]; then
    echo "HR INSTALL ERROR: release already exists: $release" >&2
    exit 1
fi
mkdir -p "$release"
python3 -m venv "$release/.venv"
"$release/.venv/bin/python" -m pip install --no-cache-dir --force-reinstall "$wheel"
temporary_current="$root/.current.new"
ln -s "$release" "$temporary_current"
mv -Tf "$temporary_current" "$root/current"
ln -sfn "$root/current/.venv/bin/hr" /usr/local/bin/hr
echo "Helix Releases installed. Run: sudo hr install list --catalog /path/to/helix-releases"
