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


def test_install_requires_elevation(monkeypatch):
    monkeypatch.setattr(installer.platform, "system", lambda: "Linux")
    monkeypatch.setattr(installer.os, "geteuid", lambda: 1000)
    with pytest.raises(ReleaseError, match="sudo or as root"):
        installer.require_elevation()


def test_aliases_are_canonical():
    assert installer.canonical_package("hr") == "helix-releases"
    assert installer.canonical_package("hu") == "helix-updater"
    with pytest.raises(ReleaseError):
        installer.canonical_package("unknown")
