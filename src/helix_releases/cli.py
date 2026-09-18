from __future__ import annotations

import argparse
from importlib.resources import files as package_files
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import tomllib

try:
    import pwd
except ImportError:  # pragma: no cover - Windows has no pwd module.
    pwd = None

from . import __version__
from .catalog import ReleaseError, publish, publish_github_release
from .installer import DEFAULT_RELEASE_CHANNEL, DEFAULT_RELEASE_REPOSITORY, DEFAULT_SERVICES, default_root, fetch_remote_candidate, install_candidate, latest_candidate, list_candidates, remote_candidates, require_elevation, privileged_command


DISPLAY_ALIASES = {
    "helix-releases": "hr",
    "helix-updater": "hu",
    "hdc": "hdc",
}


def _setup_hdc_auth() -> None:
    """Run HDC's interactive auth setup as the invoking user, not root."""
    command = ["hdc", "auth", "setup"]
    if platform.system().lower() != "windows" and hasattr(os, "geteuid") and os.geteuid() == 0:
        invoking_user = os.environ.get("SUDO_USER", "").strip()
        if invoking_user:
            try:
                home = pwd.getpwnam(invoking_user).pw_dir if pwd is not None else ""
            except KeyError as exc:
                raise ReleaseError(f"cannot resolve the invoking user for HDC GitHub authentication: {invoking_user}") from exc
            command = ["runuser", "-u", invoking_user, "--", "env", f"HOME={home}", "hdc", "auth", "setup"]
    print("HDC GitHub authentication setup follows. Existing gh status and login responses will be rendered below.")
    result = subprocess.run(command, check=False)
    if result.returncode:
        raise ReleaseError(f"HDC GitHub authentication setup exited with {result.returncode}")


def _invoke_hu_update(package: str, catalog: Path | None = None) -> dict:
    """Ask the privileged HU service to own a normal production update."""
    config = "/etc/helix/updater/helix-updater.toml" if platform.system().lower() != "windows" else r"C:\ProgramData\Helix\Updater\helix-updater.toml"
    command = ["helix-updater", "--config", config]
    if catalog is not None:
        command.extend(["--catalog", str(catalog)])
    command.extend(["update", package])
    command = privileged_command(command)
    result = subprocess.run(command, check=False, text=True)
    if result.returncode:
        raise ReleaseError(f"HU update for {package} exited with {result.returncode}")
    return {"package": package, "state": "delegated_to_hu"}


def _run(command: list[str], *, cwd: Path, label: str) -> subprocess.CompletedProcess[str]:
    # HDC recipes may use a portable interpreter name. HR owns the execution
    # environment, so bind that name to the interpreter running HR.
    if command and command[0] in {"python", "python3"}:
        command = [str(__import__("sys").executable), *command[1:]]
    result = subprocess.run(command, cwd=cwd, check=False, capture_output=True, text=True)
    if result.returncode:
        detail = (result.stderr or result.stdout or "command failed").strip()
        raise ReleaseError(f"{label} failed: {detail[-2000:]}")
    return result


def _load_handoff(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReleaseError(f"invalid HDC handoff: {path}") from exc
    required = {"protocol", "handoff_id", "contract_id", "contract_hash", "contract", "component", "source_root", "source_commit", "version", "build_command", "test_commands", "source_files", "required_paths", "verification"}
    if not isinstance(value, dict) or not required.issubset(value) or value["protocol"] != 1:
        raise ReleaseError("HDC handoff is missing required fields or uses an unsupported protocol")
    if value["verification"].get("hermes") != "passed":
        raise ReleaseError("HDC handoff does not contain successful Hermes validation")
    contract = value["contract"]
    digest = __import__("hashlib").sha256(json.dumps(contract, sort_keys=True).encode("utf-8")).hexdigest()
    if digest != value["contract_hash"] or contract.get("id") != value["contract_id"]:
        raise ReleaseError("HDC handoff contract digest is invalid")
    if not isinstance(value["build_command"], list) or not value["build_command"]:
        raise ReleaseError("HDC handoff build command is invalid")
    if not isinstance(value["test_commands"], list) or not value["test_commands"]:
        raise ReleaseError("HDC handoff test commands are invalid")
    return value


def _validate_local_contract(handoff: dict) -> None:
    contract_path = Path(__file__).resolve().parents[2] / "contracts" / f"{handoff['contract_id']}.toml"
    try:
        if contract_path.is_file():
            contract_text = contract_path.read_text(encoding="utf-8")
        else:
            contract_text = package_files("helix_releases").joinpath("contracts", f"{handoff['contract_id']}.toml").read_text(encoding="utf-8")
        local = tomllib.loads(contract_text).get("contract")
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ReleaseError(f"HR contract is unavailable or invalid: {handoff['contract_id']}") from exc
    if local != handoff["contract"]:
        raise ReleaseError("HDC handoff was generated from a different HR contract")


def packages(handoff_path: Path, output: Path, *, catalog: Path | None = None,
             publish_release: bool = False, repository: str = DEFAULT_RELEASE_REPOSITORY,
             keep_workspace: bool = False) -> dict:
    handoff = _load_handoff(handoff_path)
    _validate_local_contract(handoff)
    source = Path(handoff["source_root"]).resolve()
    if not source.is_dir():
        raise ReleaseError(f"handoff source root does not exist: {source}")
    commit = _run(["git", "rev-parse", "HEAD"], cwd=source, label="source commit").stdout.strip()
    if commit != handoff["source_commit"]:
        raise ReleaseError("source commit does not match HDC handoff")
    if _run(["git", "status", "--short"], cwd=source, label="source status").stdout.strip():
        raise ReleaseError("source checkout is dirty; refusing to package")
    workspace = Path(tempfile.mkdtemp(prefix=f"hr-{handoff['component']}-"))
    try:
        checkout = workspace / "source"
        shutil.copytree(source, checkout, ignore=shutil.ignore_patterns(".git", ".venv", "__pycache__", "dist", "build"))
        for relative in (*handoff["source_files"], *handoff["required_paths"]):
            relative_path = Path(relative)
            if relative_path.is_absolute() or ".." in relative_path.parts or not (checkout / relative_path).exists():
                raise ReleaseError(f"handoff source path is missing or unsafe: {relative}")
        output = output.resolve()
        output.mkdir(parents=True, exist_ok=True)
        for command in handoff["test_commands"]:
            _run([item.replace("{output}", str(output)) for item in command], cwd=checkout, label="release test")
        _run([item.replace("{output}", str(output)) for item in handoff["build_command"]], cwd=checkout, label="release build")
        artifacts = sorted(output.glob("*.whl"))
        if len(artifacts) != 1:
            raise ReleaseError(f"expected exactly one wheel, found {len(artifacts)}")
        result = {"handoff_id": handoff["handoff_id"], "component": handoff["component"], "version": handoff["version"], "channel": handoff.get("channel", "dev"), "commit": commit, "artifact": str(artifacts[0]), "tests": "passed"}
        if catalog is not None:
            published = publish(catalog_root=catalog, package=handoff["component"], version=handoff["version"], channel=handoff.get("channel", "dev"), commit=commit, artifact=artifacts[0])
            result.update({"published": True, "manifest": str(published.manifest), "sha256": published.sha256})
        else:
            result["published"] = False
        if publish_release:
            published = publish_github_release(
                repository=repository,
                package=handoff["component"],
                version=handoff["version"],
                channel=handoff.get("channel", "dev"),
                commit=commit,
                artifact=artifacts[0],
            )
            result.update({
                "published_release": True,
                "release_repository": repository,
                "release_tag": published.tag,
                "manifest_asset": published.manifest_file,
                "sha256": published.sha256,
            })
        return result
    finally:
        if not keep_workspace:
            shutil.rmtree(workspace, ignore_errors=True)


def publish_git(catalog: Path, *, push: bool = False) -> str:
    """Commit the catalog; optionally push using the host's existing Git auth."""
    if not (catalog / ".git").is_dir():
        raise ReleaseError(f"catalog is not a Git checkout: {catalog}")
    _run(["git", "add", "releases"], cwd=catalog, label="catalog stage")
    status = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=catalog, check=False, capture_output=True, text=True)
    if status.returncode == 0:
        return "catalog unchanged"
    _run(["git", "commit", "-m", "Publish Helix release catalog"], cwd=catalog, label="catalog commit")
    if push:
        _run(["git", "push"], cwd=catalog, label="catalog push")
        return "catalog committed and pushed"
    return "catalog committed"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="hr")
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    packages_parser = subparsers.add_parser("packages", help="package an HDC handoff")
    packages_parser.add_argument("handoff", type=Path)
    packages_parser.add_argument("--output", type=Path, default=Path("dist"))
    packages_parser.add_argument("--catalog", type=Path)
    publish_group = packages_parser.add_mutually_exclusive_group()
    publish_group.add_argument("--publish-release", dest="publish_release", action="store_true", default=None, help="publish artifact and HU manifest as a GitHub Release")
    publish_group.add_argument("--no-publish-release", dest="publish_release", action="store_false", default=None, help="build and test without publishing")
    packages_parser.add_argument("--repository", default=DEFAULT_RELEASE_REPOSITORY, help="GitHub repository for --publish-release")
    packages_parser.add_argument("--keep-workspace", action="store_true")
    install_parser = subparsers.add_parser("install", help="privileged bootstrap installation from an HR catalog")
    install_parser.add_argument("package", help="package alias, component ID, 'all', or 'list'")
    install_parser.add_argument("detail", nargs="?", help="for 'list', show every version of this package")
    install_parser.add_argument("--catalog", type=Path, help="local checkout of the public HR catalog")
    install_parser.add_argument("--repository", default=None, help=f"override the public catalog (default: {DEFAULT_RELEASE_REPOSITORY})")
    install_parser.add_argument("--channel", default=DEFAULT_RELEASE_CHANNEL, help=f"override the release channel (default: {DEFAULT_RELEASE_CHANNEL})")
    install_parser.add_argument("--target", type=Path, help="installation root; defaults to the host Helix root")
    install_parser.add_argument("--service", help="service to restart after activation")
    install_parser.add_argument("--no-restart", action="store_true")
    bootstrap_parser = subparsers.add_parser("_bootstrap-hu", help=argparse.SUPPRESS)
    bootstrap_parser.add_argument("--artifact", type=Path, required=True)
    bootstrap_parser.add_argument("--version", required=True)
    bootstrap_parser.add_argument("--sha256", required=True)
    bootstrap_parser.add_argument("--target", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "packages":
            publish_release = args.publish_release if args.publish_release is not None else args.catalog is None
            result = packages(args.handoff, args.output, catalog=args.catalog, publish_release=publish_release, repository=args.repository, keep_workspace=args.keep_workspace)
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0
        if args.command == "_bootstrap-hu":
            require_elevation()
            candidate = __import__("helix_releases.installer", fromlist=["InstallCandidate"]).InstallCandidate("helix-updater", args.version, DEFAULT_RELEASE_CHANNEL, args.artifact, args.sha256)
            result = install_candidate(candidate, args.target, DEFAULT_SERVICES["helix-updater"])
            if platform.system().lower() != "windows":
                config = Path("/etc/helix/updater/helix-updater.toml")
                config.parent.mkdir(parents=True, exist_ok=True)
                config.write_text(f'updater_version = "{__version__}"\nstate_root = "/var/lib/helix/updater"\ndownload_root = "/var/cache/helix/updater"\n\n[packages.helix-releases]\nenabled = true\nchannel = "stable"\n[packages.helix-releases.source]\ntype = "release"\nrepository = "Yongyiphan/helix-releases"\n[packages.helix-releases.target]\ncomponent = "helix-releases"\nroot = "/opt/helix/helix-releases"\nservice = ""\n\n[packages.helix-updater]\nenabled = true\nchannel = "stable"\n[packages.helix-updater.source]\ntype = "release"\nrepository = "Yongyiphan/helix-releases"\n[packages.helix-updater.target]\ncomponent = "helix-updater"\nroot = "/opt/helix/updater"\nservice = "helix-updater.service"\n\n[packages.hdc]\nenabled = true\nchannel = "stable"\n[packages.hdc.source]\ntype = "release"\nrepository = "Yongyiphan/helix-releases"\n[packages.hdc.target]\ncomponent = "hdc"\nroot = "/opt/helix/hdc"\nservice = "hdc-controller.service"\n', encoding="utf-8")
                unit = Path("/etc/systemd/system/helix-updater.service")
                unit.write_text("[Unit]\nDescription=Helix Updater\nAfter=network-online.target\n\n[Service]\nType=simple\nUser=root\nExecStart=/opt/helix/updater/current/.venv/bin/helix-updater --config /etc/helix/updater/helix-updater.toml serve\nRestart=on-failure\n\n[Install]\nWantedBy=multi-user.target\n", encoding="utf-8")
                subprocess.run(("systemctl", "daemon-reload"), check=True)
                subprocess.run(("systemctl", "enable", "helix-updater.service"), check=True)
                subprocess.run(("systemctl", "restart", "helix-updater.service"), check=True)
            print(json.dumps(result, sort_keys=True))
            return 0
        if args.command == "install":
            repository = args.repository or __import__("os").environ.get("HR_RELEASE_REPOSITORY") or DEFAULT_RELEASE_REPOSITORY
            if args.package.lower() == "list":
                if args.catalog is None:
                    candidates = remote_candidates(repository, args.channel)
                    if args.detail:
                        requested = __import__("helix_releases.installer", fromlist=["canonical_package"]).canonical_package(args.detail)
                        candidates = [item for item in candidates if item.candidate.package == requested]
                        for item in sorted(candidates, key=lambda value: _version_key(value.candidate.version)):
                            print(f"{_display_package(item.candidate.package)}\t{item.candidate.version}\t{item.candidate.channel}\t{item.manifest_url}")
                    else:
                        latest = {}
                        for item in candidates:
                            latest[item.candidate.package] = max(latest.get(item.candidate.package, item), item, key=lambda value: _version_key(value.candidate.version))
                        for item in sorted(latest.values(), key=lambda value: value.candidate.package):
                            print(f"{_display_package(item.candidate.package)}\t{item.candidate.version}\t{item.candidate.channel}")
                else:
                    candidates = list_candidates(args.catalog, args.channel)
                    if args.detail:
                        requested = __import__("helix_releases.installer", fromlist=["canonical_package"]).canonical_package(args.detail)
                        candidates = [item for item in candidates if item.package == requested]
                    for item in candidates:
                        print(f"{_display_package(item.package)}\t{item.version}\t{item.channel}" + (f"\t{item.artifact}" if args.detail else ""))
                return 0
            if args.package.lower() == "all":
                candidates = [item.candidate for item in remote_candidates(repository, args.channel)] if args.catalog is None else list_candidates(args.catalog, args.channel)
                latest = {}
                for item in candidates:
                    latest[item.package] = max(latest.get(item.package, item), item, key=lambda value: _version_key(value.version))
                results = []
                # HU must exist before any other package can be delegated to it.
                for item in sorted(latest.values(), key=lambda value: (value.package != "helix-updater", value.package)):
                    if args.catalog is None:
                        remote = fetch_remote_candidate(repository, item.package, args.channel)
                        try:
                            candidate = remote.candidate
                            results.append(_bootstrap_hu(candidate, args.target) if candidate.package == "helix-updater" else _invoke_hu_update(candidate.package, args.catalog))
                        finally:
                            __import__("shutil").rmtree(remote.temporary_root, ignore_errors=True)
                    else:
                        results.append(_bootstrap_hu(item, args.target) if item.package == "helix-updater" else _invoke_hu_update(item.package, args.catalog))
                if any(item["package"] == "hdc" for item in results):
                    _setup_hdc_auth()
                print(json.dumps(results, indent=2, sort_keys=True))
                return 0
            if args.catalog is not None:
                candidate = latest_candidate(args.catalog, args.package, args.channel)
                result = _bootstrap_hu(candidate, args.target) if candidate.package == "helix-updater" else _invoke_hu_update(candidate.package, args.catalog)
            else:
                remote = fetch_remote_candidate(repository, args.package, args.channel)
                try:
                    candidate = remote.candidate
                    result = _bootstrap_hu(candidate, args.target) if candidate.package == "helix-updater" else _invoke_hu_update(candidate.package, args.catalog)
                finally:
                    __import__("shutil").rmtree(remote.temporary_root, ignore_errors=True)
            if candidate.package == "hdc":
                _setup_hdc_auth()
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0
    except ReleaseError as exc:
        parser.error(str(exc))
    return 2


def _bootstrap_hu(candidate, target: Path | None) -> dict:
    target = target or default_root(candidate.package)
    command = privileged_command([sys.executable, "-m", "helix_releases.cli", "_bootstrap-hu", "--artifact", str(candidate.artifact), "--version", candidate.version, "--sha256", candidate.sha256, "--target", str(target)])
    result = subprocess.run(command, check=False, text=True)
    if result.returncode:
        raise ReleaseError(f"HU bootstrap exited with {result.returncode}")
    return {"package": candidate.package, "version": candidate.version, "state": "bootstrapped"}


def _version_key(value: str) -> tuple:
    parts = []
    for part in value.split("."):
        digits = "".join(char for char in part if char.isdigit())
        parts.append((0, int(digits)) if digits else (1, part))
    return tuple(parts)


def _display_package(package: str) -> str:
    alias = DISPLAY_ALIASES.get(package)
    return f"{package} ({alias})" if alias and alias != package else package


if __name__ == "__main__":
    raise SystemExit(main())
