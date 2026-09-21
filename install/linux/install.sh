#!/usr/bin/env bash
set -euo pipefail
owner=Yongyiphan
repo=helix-releases
api="https://api.github.com/repos/$owner/$repo"
tmp=$(mktemp -d -t helix-hr-install.XXXXXX)
trap 'rm -rf "$tmp"' EXIT
if [ "$(id -u)" -ne 0 ]; then echo "Run with sudo." >&2; exit 1; fi
command -v curl >/dev/null || { echo "curl is required" >&2; exit 1; }
command -v python3 >/dev/null || { echo "python3 is required" >&2; exit 1; }
curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 "$api/branches/main" -o "$tmp/branch.json"
catalog_commit=$(python3 -c 'import json,sys; v=json.load(open(sys.argv[1])); c=v["commit"]; u={(c.get("author") or {}).get("login"),(c.get("committer") or {}).get("login")}; assert "Yongyiphan" in u and len(c["sha"])==40 and (c["commit"].get("verification") or {}).get("verified") is True; print(c["sha"])' "$tmp/branch.json")
curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 "$api/releases?per_page=100" -o "$tmp/releases.json"
read -r tag version manifest_url <<EOF
$(python3 -c 'import json,re,sys; releases=json.load(open(sys.argv[1])); rx=re.compile(r"^helix-releases-v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$"); found=[]
for release in releases:
 m=rx.fullmatch(release.get("tag_name", ""))
 if not m or release.get("draft") or release.get("prerelease"): continue
 version=".".join(m.groups()); assets=release.get("assets", [])
 manifest=next((a for a in assets if a.get("name")==f"helix-releases-{version}.manifest.json"), None)
 if manifest and manifest.get("browser_download_url"): found.append((tuple(map(int,m.groups())),release["tag_name"],version,manifest["browser_download_url"]))
assert found, "no stable helix-releases MAJOR.MINOR.PATCH release with a manifest asset"
_,tag,version,url=max(found); print(tag,version,url)' "$tmp/releases.json")
EOF
curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 "$manifest_url" -o "$tmp/manifest.json"
read -r artifact digest asset_url <<EOF
$(python3 -c 'import json,re,sys; v=json.load(open(sys.argv[1])); assert v.get("schema")==1 and v.get("package")=="helix-releases" and v.get("version")==sys.argv[2] and v.get("channel")=="stable"; a=(v.get("artifacts") or {}).get("linux-x86_64") or (v.get("artifacts") or {}).get("any"); assert re.fullmatch(r"[A-Za-z0-9_.+-]+",a["file"]) and re.fullmatch(r"[0-9a-fA-F]{64}",a["sha256"]); release=json.load(open(sys.argv[3])); item=next((r for r in release if r.get("tag_name")==sys.argv[4]),None); assert item; asset=next((x for x in item.get("assets",[]) if x.get("name")==a["file"]),None); assert asset and asset.get("browser_download_url"); print(a["file"],a["sha256"].lower(),asset["browser_download_url"])' "$tmp/manifest.json" "$version" "$tmp/releases.json" "$tag")
EOF
wheel="$tmp/$artifact"
curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 "$asset_url" -o "$wheel"
printf '%s  %s\n' "$digest" "$wheel" | sha256sum --check --status
curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 "https://raw.githubusercontent.com/$owner/$repo/$catalog_commit/install/linux/install-hr.sh" -o "$tmp/install-hr.sh"
chmod 700 "$tmp/install-hr.sh"
"$tmp/install-hr.sh" "$wheel"
