import hashlib
import json
from pathlib import Path

import pytest

from helix_releases import installer
from helix_releases.catalog import ReleaseError


def _release(root: Path, package: str = "hdc") -> None:
    artifact = root / "releases" / package / "1.0.0" / f"{package}.whl"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"wheel")
    (artifact.parent / "manifest.json").write_text(json.dumps({
        "schema": 1,
        "package": package,
        "version": "1.0.0",
        "channel": "stable",
        "commit": "a" * 40,
        "published_at": "2026-09-16T00:00:00Z",
        "artifacts": {
            "linux-x86_64": {"file": artifact.name, "sha256": hashlib.sha256(b"wheel").hexdigest()},
        },
    }), encoding="utf-8")


def test_install_list_reads_the_platform_release(tmp_path):
    _release(tmp_path)
    candidates = installer.list_candidates(tmp_path)
    assert [(item.package, item.version) for item in candidates] == [("hdc", "1.0.0")]
    assert installer.latest_candidate(tmp_path, "hdc", "stable").artifact.name == "hdc.whl"


def test_single_component_install_with_catalog_uses_local_candidate(monkeypatch, tmp_path):
    release = tmp_path / "releases" / "hdc" / "1.0.0"
    release.mkdir(parents=True)
    artifact = release / "hdc.whl"
    artifact.write_bytes(b"local-release")
    manifest = {
        "package": "hdc",
        "version": "1.0.0",
        "channel": "stable",
        "artifacts": {"linux-x86_64": {"file": artifact.name, "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest()}},
    }
    (release / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    calls = []
    monkeypatch.setattr("helix_releases.cli._invoke_hu_update", lambda package, catalog=None: calls.append((package, catalog)) or {"package": package})
    monkeypatch.setattr("helix_releases.cli._setup_hdc_auth", lambda: None)

    from helix_releases.cli import main
    assert main(["install", "hdc", "--catalog", str(tmp_path)]) == 0
    assert calls == [("hdc", tmp_path)]


def test_install_requires_elevation(monkeypatch):
    monkeypatch.setattr(installer.platform, "system", lambda: "Linux")
    monkeypatch.setattr(installer.os, "geteuid", lambda: 1000)
    with pytest.raises(ReleaseError, match="sudo or as root"):
        installer.require_elevation()


def test_aliases_are_canonical():
    assert installer.canonical_package("hr") == "helix-releases"
    assert installer.canonical_package("hu") == "helix-updater"
    with pytest.raises(ReleaseError):
        installer.canonical_package("bad/name")


def test_github_release_candidates_are_preferred(monkeypatch):
    digest = hashlib.sha256(b"wheel").hexdigest()
    manifest = {
        "package": "hdc",
        "version": "1.2.0",
        "channel": "stable",
        "artifacts": {"linux-x86_64": {"file": "hdc.whl", "sha256": digest}},
    }
    responses = {
        "https://api.github.com/repos/Yongyiphan/helix-releases/releases?per_page=100": [
            {"tag_name": "hdc-v1.2.0", "draft": False, "prerelease": False, "assets": [
                {"name": "hdc-1.2.0.manifest.json", "browser_download_url": "https://assets.test/manifest"},
                {"name": "hdc.whl", "browser_download_url": "https://assets.test/hdc.whl"},
            ]}
        ],
        "https://assets.test/manifest": manifest,
    }
    monkeypatch.setattr(installer, "_public_json", lambda url: responses.get(url, []))
    candidates = installer.remote_candidates("Yongyiphan/helix-releases")
    assert [(item.candidate.package, item.candidate.version) for item in candidates] == [("hdc", "1.2.0")]
    assert candidates[0].artifact_url == "https://assets.test/hdc.whl"


def test_github_release_candidates_fall_back_to_public_atom_feed(monkeypatch):
    digest = hashlib.sha256(b"wheel").hexdigest()
    manifest = {
        "package": "hdc",
        "version": "1.2.0",
        "channel": "stable",
        "artifacts": {"linux-x86_64": {"file": "hdc.whl", "sha256": digest}},
    }
    feed = b'''<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
      <entry><link href="https://github.com/Yongyiphan/helix-releases/releases/tag/hdc-v1.2.0" /></entry>
    </feed>'''

    def public_json(url):
        if url.endswith("/hdc-1.2.0.manifest.json"):
            return manifest
        raise installer.ReleaseError("rate limited")

    monkeypatch.setattr(installer, "_public_json", public_json)
    monkeypatch.setattr(installer, "_public_bytes", lambda url: feed)
    candidates = installer.remote_candidates("Yongyiphan/helix-releases")
    assert [(item.candidate.package, item.candidate.version) for item in candidates] == [("hdc", "1.2.0")]
    assert candidates[0].artifact_url.endswith("/hdc.whl")
