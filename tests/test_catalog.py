from pathlib import Path

from helix_releases.catalog import publish


def test_publish_is_independent_per_package_and_version(tmp_path):
    artifact = tmp_path / "demo-1.0.0-py3-none-any.whl"
    artifact.write_bytes(b"wheel")
    result = publish(catalog_root=tmp_path / "catalog", package="demo", version="1.0.0", channel="dev", commit="abc", artifact=artifact)
    assert result.manifest.exists()
    assert (tmp_path / "catalog" / "releases" / "demo" / "1.0.0" / artifact.name).read_bytes() == b"wheel"
