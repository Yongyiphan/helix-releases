import json
from pathlib import Path

from helix_releases.cli import packages


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
        "component": "demo-package", "repository": "demo-package", "branch": "main", "source_root": str(source), "source_commit": commit, "version": "1.0.0", "channel": "dev", "artifact_format": "python_wheel", "platforms": ["linux-x86_64"], "source_files": ["pyproject.toml", "src/demo.py"], "required_paths": ["pyproject.toml", "src"], "build_command": ["python", "-m", "pip", "wheel", "--no-build-isolation", "--no-deps", "--wheel-dir", "{output}", "."], "test_commands": [["python", "-m", "pytest", "-q"]], "owner_controller": "test", "verification": {"hermes": "passed"}
    }), encoding="utf-8")
    result = packages(handoff, tmp_path / "dist", catalog=tmp_path / "catalog")
    assert result["published"] is True
    assert Path(result["manifest"]).exists()
