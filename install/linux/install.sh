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
curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 "$api/contents/releases/helix-releases?ref=$catalog_commit" -o "$tmp/versions.json"
version=$(python3 -c 'import json,sys; v=json.load(open(sys.argv[1])); x=[i["name"] for i in v if i.get("type")=="dir"]; print(max(x,key=lambda s:tuple((0,int("".join(c for c in p if c.isdigit()))) if any(c.isdigit() for c in p) else (1,p) for p in s.split("."))))' "$tmp/versions.json")
base="https://raw.githubusercontent.com/$owner/$repo/$catalog_commit/releases/helix-releases/$version"
curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 "$base/manifest.json" -o "$tmp/manifest.json"
read -r artifact digest source_commit <<EOF
$(python3 -c 'import json,re,sys; v=json.load(open(sys.argv[1])); assert v.get("schema")==1 and v.get("package")=="helix-releases" and v.get("channel")=="stable"; a=(v.get("artifacts") or {}).get("linux-x86_64") or (v.get("artifacts") or {}).get("any"); assert re.fullmatch(r"[A-Za-z0-9_.+-]+",a["file"]) and re.fullmatch(r"[0-9a-fA-F]{64}",a["sha256"]) and re.fullmatch(r"[0-9a-fA-F]{7,40}",v["commit"]); print(a["file"],a["sha256"].lower(),v["commit"])' "$tmp/manifest.json")
EOF
curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 "$api/commits/$source_commit" -o "$tmp/source.json"
python3 -c 'import json,sys; v=json.load(open(sys.argv[1])); assert "Yongyiphan" in {(v.get("author") or {}).get("login"),(v.get("committer") or {}).get("login")}' "$tmp/source.json"
wheel="$tmp/$artifact"
curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 "$base/$artifact" -o "$wheel"
printf '%s  %s\n' "$digest" "$wheel" | sha256sum --check --status
curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 "https://raw.githubusercontent.com/$owner/$repo/$catalog_commit/install/linux/install-hr.sh" -o "$tmp/install-hr.sh"
chmod 700 "$tmp/install-hr.sh"
"$tmp/install-hr.sh" "$wheel"
