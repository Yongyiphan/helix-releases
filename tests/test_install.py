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
    monkeypatch.setattr("helix_releases.cli._invoke_hu_update", lambda package, catalog=None, profile="production", artifact=None, manifest=None: calls.append((package, catalog, profile, artifact, manifest)) or {"package": package})
    monkeypatch.setattr("helix_releases.cli._setup_hdc_auth", lambda: None)

    from helix_releases.cli import main
    assert main(["install", "hdc", "--catalog", str(tmp_path)]) == 0
    assert calls[0][:3] == ("hdc", tmp_path, "production")
    assert calls[0][3] == artifact
    assert calls[0][4]["version"] == "1.0.0"


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


def test_privileged_command_does_not_nest_sudo_for_root(monkeypatch):
    monkeypatch.setattr(installer.platform, "system", lambda: "Linux")
    monkeypatch.setattr(installer.os, "geteuid", lambda: 0)
    assert installer.privileged_command(["helix-updater", "status"]) == ["helix-updater", "status"]


def test_hu_bootstrap_reuses_configured_production_runtime_root(tmp_path):
    from helix_releases.cli import _configured_hu_root

    config = tmp_path / "helix-updater.toml"
    config.write_text(
        '[profiles.production]\nhelix_root = "/srv/helix"\n'
        '[profiles.production.packages.helix-updater.target]\nroot = "updater-prod"\n',
        encoding="utf-8",
    )
    assert _configured_hu_root(config) == Path("/srv/helix/updater-prod")


def test_installed_hu_updates_through_selected_runtime_instead_of_rebootstrapping(monkeypatch):
    from types import SimpleNamespace
    import helix_releases.cli as cli

    calls = []
    candidate = SimpleNamespace(package="helix-updater", artifact=Path("hu.whl"), manifest={"version": "1.2.0"})
    monkeypatch.setattr(cli, "_hu_profile_ready", lambda profile: profile == "development")
    monkeypatch.setattr(cli, "_invoke_hu_update", lambda package, catalog, profile, artifact, manifest:
                        calls.append((package, profile, artifact, manifest)) or {"state": "handed_off"})
    monkeypatch.setattr(cli, "_bootstrap_hu", lambda candidate, target: pytest.fail("ready HU should not be bootstrapped again"))

    result = cli._install_hu_candidate(candidate, "development", None, Path("catalog"))

    assert result == {"state": "handed_off"}
    assert calls == [("helix-updater", "development", Path("hu.whl"), {"version": "1.2.0"})]


def test_missing_development_hu_bootstraps_only_the_selected_profile(monkeypatch):
    from types import SimpleNamespace
    import helix_releases.cli as cli

    candidate = SimpleNamespace(package="helix-updater", artifact=Path("hu.whl"), manifest=None)
    monkeypatch.setattr(cli, "_hu_profile_ready", lambda _profile: False)
    monkeypatch.setattr(cli, "_bootstrap_hu", lambda _candidate, target, profile:
                        {"target": target, "profile": profile})

    assert cli._install_hu_candidate(candidate, "development", None, None) == {
        "target": None, "profile": "development",
    }


def test_development_bootstrap_does_not_touch_production(monkeypatch, tmp_path):
    from types import SimpleNamespace
    import helix_releases.cli as cli

    config = tmp_path / "helix-updater.toml"
    dev_root = tmp_path / "dev-updater"
    candidate = SimpleNamespace(package="helix-updater", version="1.2.0")
    installs, seeds, commands = [], [], []
    monkeypatch.setattr(cli, "_configured_hu_root", lambda _config, profile: dev_root if profile == "development" else None)
    monkeypatch.setattr(cli, "install_candidate", lambda _candidate, root, **kwargs:
                        installs.append((root, kwargs)) or {"state": "installed"})
    monkeypatch.setattr(cli, "_seed_hu_profiles", lambda *args, **kwargs: seeds.append(kwargs["profiles"]))
    monkeypatch.setattr(cli, "_development_catalog_path", lambda: tmp_path / "dev-catalog")
    monkeypatch.setattr(cli.subprocess, "run", lambda command, **kwargs: commands.append(command))

    legacy_config = tmp_path / "legacy.toml"
    result = cli._bootstrap_development_profile(candidate, config, legacy_config=legacy_config)

    assert result["production_touched"] is False
    assert installs == [(dev_root, {"restart": False, "launcher_dir": Path("/usr/local/libexec/helix-development")})]
    assert seeds == [("development",)]
    assert commands[0][commands[0].index("--legacy-config") + 1] == str(legacy_config)
    assert "--preserve-legacy-config" in commands[0]
    assert "profiles-init" in commands[0]
    assert commands[0][commands[0].index("--catalog") + 1] == str(tmp_path / "dev-catalog")
    assert commands[-2:] == [
        ("systemctl", "enable", "helix-updater-dev.service"),
        ("systemctl", "restart", "helix-updater-dev.service"),
    ]
    assert all("helix-updater.service" not in command for command in commands)


def test_development_catalog_path_uses_invoking_user_when_bootstrapped_as_root(monkeypatch, tmp_path):
    from types import SimpleNamespace
    import helix_releases.cli as cli

    monkeypatch.setattr(cli.os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setenv("SUDO_USER", "mcadmin")
    monkeypatch.setattr(cli, "pwd", SimpleNamespace(getpwnam=lambda _user: SimpleNamespace(pw_dir=str(tmp_path))))

    assert cli._development_catalog_path() == tmp_path / ".local/state/helix/development/catalog"


def test_production_bootstrap_has_system_catalog_fallback_without_sudo_user(monkeypatch):
    import helix_releases.cli as cli

    monkeypatch.setattr(cli.os, "geteuid", lambda: 0, raising=False)
    monkeypatch.delenv("SUDO_USER", raising=False)

    assert cli._development_catalog_path() == Path("/var/lib/helix/development/catalog")


def test_active_production_routes_development_bootstrap_to_dev_only(monkeypatch, tmp_path, capsys):
    from types import SimpleNamespace
    import helix_releases.cli as cli

    calls = []
    monkeypatch.setattr(cli, "require_elevation", lambda: None)
    monkeypatch.setattr(cli.platform, "system", lambda: "Linux")
    monkeypatch.setattr(cli, "_system_service_active", lambda service: service == "helix-updater.service")
    monkeypatch.setattr(cli, "_has_combined_profiles", lambda _config: True)
    monkeypatch.setattr(cli, "_bootstrap_development_profile", lambda candidate, config, legacy_config=None:
                        calls.append((candidate.package, candidate.version, config)) or
                        {"production_touched": False, "state": "development_service_started"})

    assert cli.main([
        "_bootstrap-hu", "--artifact", str(tmp_path / "hu.whl"), "--version", "1.2.0",
        "--sha256", "a" * 64, "--profile", "development",
    ]) == 0

    assert calls == [("helix-updater", "1.2.0", Path("/etc/helix/helix-updater.toml"))]
    assert json.loads(capsys.readouterr().out)["production_touched"] is False


def test_development_bootstrap_is_dev_only_even_without_production(monkeypatch, tmp_path, capsys):
    import helix_releases.cli as cli

    calls = []
    monkeypatch.setattr(cli, "require_elevation", lambda: None)
    monkeypatch.setattr(cli.platform, "system", lambda: "Linux")
    monkeypatch.setattr(cli, "_system_service_active", lambda _service: False)
    monkeypatch.setattr(cli, "_has_combined_profiles", lambda _config: False)
    monkeypatch.setattr(cli, "LEGACY_HU_CONFIG_PATH", tmp_path / "missing-legacy.toml")
    monkeypatch.setattr(cli, "_bootstrap_development_profile", lambda candidate, config, legacy_config=None:
                        calls.append((candidate.package, config, legacy_config)) or
                        {"production_touched": False, "state": "development_service_started"})

    assert cli.main([
        "_bootstrap-hu", "--artifact", str(tmp_path / "hu.whl"), "--version", "1.2.0",
        "--sha256", "a" * 64, "--profile", "development",
    ]) == 0

    assert calls == [("helix-updater", Path("/etc/helix/helix-updater.toml"), tmp_path / "missing-legacy.toml")]
    assert json.loads(capsys.readouterr().out)["production_touched"] is False


def test_production_hu_bootstrap_does_not_install_or_start_dev(monkeypatch, tmp_path, capsys):
    import helix_releases.cli as cli

    config = tmp_path / "helix-updater.toml"
    production_root = tmp_path / "production-updater"
    candidate_installs, seeded_profiles, commands = [], [], []
    monkeypatch.setattr(cli, "require_elevation", lambda: None)
    monkeypatch.setattr(cli.platform, "system", lambda: "Linux")
    monkeypatch.setattr(cli, "_system_service_active", lambda _service: False)
    monkeypatch.setattr(cli, "HU_CONFIG_PATH", config)
    monkeypatch.setattr(cli, "_configured_hu_root", lambda *_args: production_root)
    monkeypatch.setattr(cli, "_development_catalog_path", lambda: tmp_path / "catalog")
    monkeypatch.setattr(cli, "install_candidate", lambda candidate, root, **kwargs:
                        candidate_installs.append((root, kwargs)) or {"state": "installed"})
    monkeypatch.setattr(cli, "_seed_hu_profiles", lambda *args, **kwargs:
                        seeded_profiles.append(kwargs["profiles"]))
    monkeypatch.setattr(cli.subprocess, "run", lambda command, **kwargs: commands.append(command))

    assert cli.main([
        "_bootstrap-hu", "--artifact", str(tmp_path / "hu.whl"), "--version", "1.2.0",
        "--sha256", "a" * 64, "--profile", "production",
    ]) == 0

    assert candidate_installs == [(production_root, {"restart": False})]
    assert seeded_profiles == [("production",)]
    assert commands[1] == (
        str(production_root / "current/.venv/bin/helix-updater"), "--config", str(config),
        "--profile", "production", "runtime", "install-services",
    )
    assert commands[-2:] == [
        ("systemctl", "enable", "helix-updater.service"),
        ("systemctl", "restart", "helix-updater.service"),
    ]
    assert all("helix-updater-dev.service" not in command for command in commands)
    result = json.loads(capsys.readouterr().out)
    assert result["state"] == "production_service_started"
    assert result["development"] == "not_installed"


def test_active_production_stages_development_profile_from_legacy_config(monkeypatch, tmp_path):
    import helix_releases.cli as cli

    legacy_config = tmp_path / "legacy.toml"
    legacy_config.write_text('state_root = "/legacy/state"\n', encoding="utf-8")
    paired_config = tmp_path / "paired.toml"
    calls = []
    monkeypatch.setattr(cli, "require_elevation", lambda: None)
    monkeypatch.setattr(cli.platform, "system", lambda: "Linux")
    monkeypatch.setattr(cli, "_system_service_active", lambda _service: True)
    monkeypatch.setattr(cli, "HU_CONFIG_PATH", paired_config)
    monkeypatch.setattr(cli, "LEGACY_HU_CONFIG_PATH", legacy_config)
    monkeypatch.setattr(cli, "_bootstrap_development_profile", lambda candidate, config, legacy_config=None:
                        calls.append((candidate.package, config, legacy_config)) or {"production_touched": False})

    assert cli.main([
        "_bootstrap-hu", "--artifact", str(tmp_path / "hu.whl"), "--version", "1.2.0",
        "--sha256", "a" * 64, "--profile", "development",
    ]) == 0
    assert calls == [("helix-updater", paired_config, legacy_config)]


def test_seeding_development_profile_preserves_production_state(tmp_path):
    from helix_releases.cli import _seed_hu_profiles

    config = tmp_path / "helix-updater.toml"
    production_state = tmp_path / "production-state" / "packages" / "helix-updater.json"
    development_state = tmp_path / "development-state" / "packages" / "helix-updater.json"
    production_state.parent.mkdir(parents=True)
    production_state.write_text('{"state":"successful","current":"1.0.0"}\n', encoding="utf-8")
    original_production_state = production_state.read_bytes()
    config.write_text(
        f'[profiles.production]\nstate_root = "{tmp_path / "production-state"}"\n'
        f'[profiles.development]\nstate_root = "{tmp_path / "development-state"}"\n',
        encoding="utf-8",
    )

    _seed_hu_profiles(config, "1.2.0", tmp_path / "production-updater",
                      tmp_path / "development-updater", profiles=("development",))

    assert production_state.read_bytes() == original_production_state
    development = json.loads(development_state.read_text(encoding="utf-8"))
    assert development["current"] == "1.2.0"
    assert development["current_path"] == str(tmp_path / "development-updater" / "releases" / "1.2.0")


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


def test_github_release_candidates_reject_tag_manifest_identity_mismatch(monkeypatch):
    manifest = {
        "package": "hdc",
        "version": "1.2.0",
        "channel": "stable",
        "artifacts": {"linux-x86_64": {"file": "hdc.whl", "sha256": "a" * 64}},
    }
    responses = {
        "https://api.github.com/repos/Yongyiphan/helix-releases/releases?per_page=100": [
            {"tag_name": "v1.2.0", "draft": False, "prerelease": False, "assets": [
                {"name": "hdc-1.2.0.manifest.json", "browser_download_url": "https://assets.test/manifest"},
                {"name": "hdc.whl", "browser_download_url": "https://assets.test/hdc.whl"},
            ]}
        ],
        "https://assets.test/manifest": manifest,
    }
    monkeypatch.setattr(installer, "_public_json", lambda url: responses[url])
    assert installer.remote_candidates("Yongyiphan/helix-releases") == []


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
