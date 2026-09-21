import json
from pathlib import Path

from helix_releases.cli import packages, _load_handoff, _validate_local_contract


def test_packages_validates_handoff_and_publishes_catalog(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    (source / "pyproject.toml").write_text(
        """[build-system]\nrequires = [\"setuptools>=68\"]\nbuild-backend = \"setuptools.build_meta\"\n\n[project]\nname = \"demo-package\"\nversion = \"1.0.0\"\n""",
        encoding="utf-8",
    )
    (source / "src").mkdir()
    (source / "src" / "demo.py").write_text("VALUE = 1\n", encoding="utf-8")
    (source / "tests").mkdir()
    (source / "tests" / "test_smoke.py").write_text("def test_smoke():\n    assert True\n", encoding="utf-8")
    import subprocess
    subprocess.run(("git", "init", "-q", str(source)), check=True)
    subprocess.run(("git", "-C", str(source), "config", "user.email", "test@example.invalid"), check=True)
    subprocess.run(("git", "-C", str(source), "config", "user.name", "Test"), check=True)
    subprocess.run(("git", "-C", str(source), "add", "."), check=True)
    subprocess.run(("git", "-C", str(source), "commit", "-qm", "initial"), check=True)
    commit = subprocess.check_output(("git", "-C", str(source), "rev-parse", "HEAD"), text=True).strip()
    contract = {"id": "python-wheel-v1", "artifact_format": "python_wheel", "source_layout": "src", "required_paths": ["pyproject.toml", "src"], "supported_platforms": ["linux-x86_64", "windows-x86_64"], "test_commands": [["python", "-m", "pytest", "-q"]], "build_command": ["python", "-m", "pip", "wheel", "--no-build-isolation", "--no-deps", "--wheel-dir", "{output}", "."]}
    import hashlib
    handoff = tmp_path / "handoff.json"
    handoff.write_text(json.dumps({
        "protocol": 1, "handoff_id": "release-test", "contract_id": "python-wheel-v1", "contract_hash": hashlib.sha256(json.dumps(contract, sort_keys=True).encode()).hexdigest(), "contract": contract,
        "component": "demo-package", "repository": "demo-package", "branch": "main", "source_root": str(source), "source_commit": commit, "version": "1.0.0", "channel": "dev", "artifact_format": "python_wheel", "platforms": ["linux-x86_64"], "source_files": ["pyproject.toml", "src/demo.py", "tests/test_smoke.py"], "required_paths": ["pyproject.toml", "src"], "build_command": ["python", "-m", "pip", "wheel", "--no-build-isolation", "--no-deps", "--wheel-dir", "{output}", "."], "test_commands": [["python", "-m", "pytest", "-q"]], "owner_controller": "test"
    }), encoding="utf-8")
    assert _load_handoff(handoff)["component"] == "demo-package"
    legacy_hdc_handoff = json.loads(handoff.read_text(encoding="utf-8"))
    legacy_hdc_handoff["verification"] = {"hermes": "passed"}
    handoff.write_text(json.dumps(legacy_hdc_handoff), encoding="utf-8")
    assert _load_handoff(handoff)["verification"]["hermes"] == "passed"
    result = packages(handoff, tmp_path / "dist", catalog=tmp_path / "catalog")
    assert result["published"] is True
    assert Path(result["manifest"]).exists()


def test_handoff_rejects_commands_that_differ_from_hr_contract(tmp_path):
    import hashlib
    import pytest
    from helix_releases.catalog import ReleaseError

    contract = {"id": "python-wheel-v1", "required_paths": ["pyproject.toml", "src"],
                "test_commands": [["python", "-m", "pytest", "-q"]],
                "build_command": ["python", "-m", "pip", "wheel", "--no-build-isolation", "--no-deps", "--wheel-dir", "{output}", "."]}
    value = {"protocol": 1, "handoff_id": "manual", "contract_id": contract["id"],
             "contract_hash": hashlib.sha256(json.dumps(contract, sort_keys=True).encode()).hexdigest(),
             "contract": contract, "component": "demo", "source_root": str(tmp_path),
             "source_commit": "commit", "version": "1.0.0", "build_command": ["python", "-c", "pass"],
             "test_commands": contract["test_commands"], "source_files": ["pyproject.toml"],
             "required_paths": contract["required_paths"]}
    handoff = tmp_path / "handoff.json"
    handoff.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ReleaseError, match="build command differs"):
        _load_handoff(handoff)


def test_installed_contract_is_packaged(monkeypatch, tmp_path):
    contract = {"id": "python-wheel-v1", "artifact_format": "python_wheel", "source_layout": "src", "required_paths": ["pyproject.toml", "src"], "supported_platforms": ["linux-x86_64", "windows-x86_64"], "test_commands": [["python", "-m", "pytest", "-q"]], "build_command": ["python", "-m", "pip", "wheel", "--no-build-isolation", "--no-deps", "--wheel-dir", "{output}", "."]}
    handoff = {"contract_id": "python-wheel-v1", "contract": contract}
    monkeypatch.setattr("helix_releases.cli.__file__", str(tmp_path / "installed" / "helix_releases" / "cli.py"))
    _validate_local_contract({**handoff, "contract_hash": "unused"})
