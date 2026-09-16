import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).parents[2] / "hdc" / "src"))

from typer.testing import CliRunner

from hdc.cli import app as hdc_app
sys.path.insert(0, str(Path(__file__).parents[2] / "helix-updater" / "src"))

from helix_updater.platform.linux import LinuxPlatform
from helix_updater.registry import Registry
from helix_updater.updater import Updater


def test_hdc_cli_query_to_hr_build_and_catalog(tmp_path):
    source = tmp_path / "component"
    source.mkdir()
    (source / "pyproject.toml").write_text(
        """[build-system]\nrequires = [\"setuptools>=68\"]\nbuild-backend = \"setuptools.build_meta\"\n\n[project]\nname = \"demo-component\"\nversion = \"1.0.0\"\n""",
        encoding="utf-8",
    )
    (source / "src").mkdir()
    (source / "src" / "demo_component.py").write_text("VALUE = 1\n", encoding="utf-8")
    (source / "tests").mkdir()
    (source / "tests" / "test_smoke.py").write_text("def test_smoke():\n    assert True\n", encoding="utf-8")
    subprocess.run(("git", "init", "-q", str(source)), check=True)
    subprocess.run(("git", "-C", str(source), "config", "user.email", "test@example.invalid"), check=True)
    subprocess.run(("git", "-C", str(source), "config", "user.name", "Test"), check=True)
    subprocess.run(("git", "-C", str(source), "add", "."), check=True)
    subprocess.run(("git", "-C", str(source), "commit", "-qm", "initial"), check=True)
    config = tmp_path / "hdc.toml"
    contract = tmp_path / "helix-releases" / "contracts"
    contract.mkdir(parents=True)
    contract_source = Path(__file__).parents[1] / "contracts" / "python-wheel-v1.toml"
    (contract / "python-wheel-v1.toml").write_bytes(contract_source.read_bytes())
    config.write_text(
        f'[repositories.component]\npath = "{source}"\nread_only = false\ngraphify = false\n'
        '[worker]\nid = "integration-hdc"\nhost = "test"\nplatform = "linux"\nrepositories = ["component"]\n',
        encoding="utf-8",
    )
    runner = CliRunner()
    request_result = runner.invoke(hdc_app, ["--config", str(config), "release", "request", "component"])
    assert request_result.exit_code == 0, request_result.output
    request = json.loads(request_result.output)
    publish_result = runner.invoke(hdc_app, [
        "--config", str(config), "release", "publish", "component",
        "--catalog", str(tmp_path / "catalog"), "--output", str(tmp_path / "dist"),
        "--hr-command", str(Path(sys.executable).parent / "hr"),
        "--hermes-validated",
    ])
    assert publish_result.exit_code == 0, publish_result.output
    manifests = list((tmp_path / "catalog").glob("releases/component/1.0.0/manifest.json"))
    assert len(manifests) == 1
    assert Path(manifests[0]).is_file()
    hu_config = tmp_path / "hu.toml"
    hu_config.write_text(
        f'state_root = "{tmp_path / "hu-state"}"\n'
        f'download_root = "{tmp_path / "hu-downloads"}"\n'
        '[packages.component]\nenabled = true\nchannel = "dev"\n'
        '[packages.component.source]\ntype = "catalog"\n'
        f'repository = "{tmp_path / "catalog"}"\n'
        '[packages.component.target]\ncomponent = "component"\n'
        f'root = "{tmp_path / "installed-component"}"\n',
        encoding="utf-8",
    )
    registry = Registry.from_file(hu_config)
    installed = Updater(registry, platform=LinuxPlatform()).update(registry.packages["component"])
    assert installed is not None
    assert (tmp_path / "installed-component" / "current").is_symlink()
