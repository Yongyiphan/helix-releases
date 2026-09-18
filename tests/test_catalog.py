from pathlib import Path

from types import SimpleNamespace

from helix_releases.catalog import publish, publish_github_release


def test_publish_is_independent_per_package_and_version(tmp_path):
    artifact = tmp_path / "demo-1.0.0-py3-none-any.whl"
    artifact.write_bytes(b"wheel")
    result = publish(catalog_root=tmp_path / "catalog", package="demo", version="1.0.0", channel="dev", commit="abc", artifact=artifact)
    assert result.manifest.exists()
    assert (tmp_path / "catalog" / "releases" / "demo" / "1.0.0" / artifact.name).read_bytes() == b"wheel"


def test_publish_github_release_uploads_artifact_and_manifest_without_catalog_commit(tmp_path):
    artifact = tmp_path / "demo-1.1.0-py3-none-any.whl"
    artifact.write_bytes(b"wheel")
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        manifest = next(path for path in command if str(path).endswith(".manifest.json"))
        assert manifest
        return SimpleNamespace(returncode=0, stdout="created", stderr="")

    result = publish_github_release(
        repository="Yongyiphan/helix-releases",
        package="demo",
        version="1.1.0",
        channel="stable",
        commit="a" * 40,
        artifact=artifact,
        runner=runner,
    )

    assert result.tag == "demo-v1.1.0"
    assert result.manifest_file == "demo-1.1.0.manifest.json"
    assert calls[0][0][:4] == ["gh", "release", "create", "demo-v1.1.0"]
    assert "--repo" in calls[0][0]
    assert calls[0][0][calls[0][0].index("--target") + 1] == "main"
