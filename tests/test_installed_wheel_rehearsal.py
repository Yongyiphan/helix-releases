import hashlib
import json
from pathlib import Path
import subprocess
import sys
import sysconfig
import venv


def _run(command, **kwargs):
    return subprocess.run(command, check=True, capture_output=True, text=True, **kwargs)


def test_installed_hr_wheel_rehearses_a_local_build(tmp_path):
    repository = Path(__file__).parents[1]
    wheelhouse = tmp_path / "wheelhouse"
    _run([
        sys.executable,
        "-m",
        "pip",
        "wheel",
        "--no-build-isolation",
        "--no-deps",
        "--wheel-dir",
        str(wheelhouse),
        str(repository),
    ])
    wheel = next(wheelhouse.glob("helix_releases-*.whl"))

    runtime = tmp_path / "runtime"
    venv.EnvBuilder(with_pip=True, system_site_packages=True).create(runtime)
    python = runtime / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    rehearsal_env = {**__import__("os").environ, "PYTHONPATH": sysconfig.get_paths()["purelib"]}
    _run([str(python), "-m", "pip", "install", "--no-index", str(wheel)], env=rehearsal_env)
    hr = runtime / ("Scripts/hr.exe" if sys.platform == "win32" else "bin/hr")
    assert _run([str(hr), "--version"], env=rehearsal_env).stdout.strip() == "0.2.2"

    source = tmp_path / "component"
    (source / "src" / "demo_component").mkdir(parents=True)
    (source / "tests").mkdir()
    (source / "pyproject.toml").write_text(
        """[build-system]\nrequires = [\"setuptools>=68\"]\nbuild-backend = \"setuptools.build_meta\"\n\n[project]\nname = \"demo-component\"\nversion = \"1.0.0\"\n""",
        encoding="utf-8",
    )
    (source / "src" / "demo_component" / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    (source / "tests" / "test_smoke.py").write_text("def test_smoke():\n    assert True\n", encoding="utf-8")
    # The isolated HR runtime deliberately has no third-party test tools.  A
    # tiny local module lets this rehearsal exercise HR's installed contract
    # and build path without downloading dependencies or touching production.
    (source / "pytest.py").write_text("# offline rehearsal test-runner shim\n", encoding="utf-8")
    _run(["git", "init", "-q", str(source)])
    _run(["git", "-C", str(source), "config", "user.email", "rehearsal@example.invalid"])
    _run(["git", "-C", str(source), "config", "user.name", "HR rehearsal"])
    _run(["git", "-C", str(source), "add", "."])
    _run(["git", "-C", str(source), "commit", "-qm", "rehearsal source"])
    commit = _run(["git", "-C", str(source), "rev-parse", "HEAD"]).stdout.strip()

    contract = {
        "id": "python-wheel-v1",
        "artifact_format": "python_wheel",
        "source_layout": "src",
        "required_paths": ["pyproject.toml", "src"],
        "supported_platforms": ["linux-x86_64", "windows-x86_64"],
        "test_commands": [["python", "-m", "pytest", "-q"]],
        "build_command": ["python", "-m", "pip", "wheel", "--no-build-isolation", "--no-deps", "--wheel-dir", "{output}", "."],
    }
    handoff = tmp_path / "handoff.json"
    handoff.write_text(json.dumps({
        "protocol": 1,
        "handoff_id": "hr-installed-wheel-rehearsal",
        "contract_id": contract["id"],
        "contract_hash": hashlib.sha256(json.dumps(contract, sort_keys=True).encode()).hexdigest(),
        "contract": contract,
        "component": "demo-component",
        "repository": "demo-component",
        "branch": "main",
        "source_root": str(source),
        "source_commit": commit,
        "version": "1.0.0",
        "channel": "stable",
        "artifact_format": "python_wheel",
        "platforms": ["linux-x86_64"],
        "source_files": ["pyproject.toml", "src", "tests/test_smoke.py"],
        "required_paths": contract["required_paths"],
        "build_command": contract["build_command"],
        "test_commands": contract["test_commands"],
        "owner_controller": "rehearsal",
        "verification": {"hermes": "passed"},
    }, indent=2), encoding="utf-8")

    result = _run([str(hr), "packages", str(handoff), "--no-publish-release", "--output", str(tmp_path / "dist")], env=rehearsal_env)
    payload = json.loads(result.stdout)
    assert payload["published"] is False
    assert Path(payload["artifact"]).is_file()
