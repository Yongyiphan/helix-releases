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
import time
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
if platform.system().lower() == "windows":
    _WINDOWS_HELIX_ROOT = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "Helix"
    HU_CONFIG_PATH = _WINDOWS_HELIX_ROOT / "helix-updater.toml"
    LEGACY_HU_CONFIG_PATH = _WINDOWS_HELIX_ROOT / "Updater" / "helix-updater.toml"
else:
    HU_CONFIG_PATH = Path("/etc/helix/helix-updater.toml")
    LEGACY_HU_CONFIG_PATH = Path("/etc/helix/updater/helix-updater.toml")
HU_PROFILE_LAUNCHERS = {
    "production": Path("/usr/local/bin/helix-updater"),
    "development": Path("/usr/local/libexec/helix-development/helix-updater"),
}


def _development_catalog_path() -> Path:
    """Prefer the invoking user's dev catalog without making production bootstrap depend on sudo."""
    home = Path.home()
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        invoking_user = os.environ.get("SUDO_USER", "").strip()
        if not invoking_user or pwd is None:
            return Path("/var/lib/helix/development/catalog")
        try:
            home = Path(pwd.getpwnam(invoking_user).pw_dir)
        except KeyError as exc:
            raise ReleaseError(f"cannot resolve the invoking user for the development catalog: {invoking_user}") from exc
    return home / ".local" / "state" / "helix" / "development" / "catalog"


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


def _invoke_hu_update(package: str, catalog: Path | None = None, profile: str = "production",
                      artifact: Path | None = None, manifest: dict | None = None) -> dict:
    """Pass HR's verified-release candidate to the selected privileged HU runtime."""
    if platform.system().lower() == "windows":
        config = HU_CONFIG_PATH
        root = _configured_hu_root(config, profile) or default_root("helix-updater")
        activation = root / "installation.json"
        if not activation.is_file():
            raise ReleaseError(f"Windows HU activation record is missing: {activation}")
        try:
            active = Path(json.loads(activation.read_text(encoding="utf-8"))["active"])
        except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ReleaseError(f"Windows HU activation record is invalid: {activation}") from exc
        launcher = active / ".venv" / "Scripts" / "python.exe"
        if not launcher.is_file():
            raise ReleaseError(f"Windows HU runtime launcher is missing: {launcher}")
        if artifact is None or manifest is None:
            raise ReleaseError("HR-to-HU handoff requires both a downloaded artifact and its manifest")
        with tempfile.TemporaryDirectory(prefix="hr-hu-handoff-") as handoff_dir:
            manifest_path = Path(handoff_dir) / "manifest.json"
            manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
            command = [str(launcher), "-m", "helix_updater", "--config", str(config), "--profile", profile]
            if catalog is not None:
                command.extend(["--catalog", str(catalog)])
            command.extend(["install-artifact", package, "--artifact", str(artifact), "--manifest", str(manifest_path)])
            result = subprocess.run(command, check=False, text=True)
            if result.returncode:
                raise ReleaseError(f"HU installation for {package} exited with {result.returncode}")
            return {"package": package, "state": "artifact_handed_to_hu", "version": manifest.get("version"), "profile": profile}
    config = HU_CONFIG_PATH
    launcher = HU_PROFILE_LAUNCHERS.get(profile)
    if launcher is None:
        raise ReleaseError(f"unsupported HU profile: {profile}")
    command = [str(launcher), "--config", str(config), "--profile", profile]
    if catalog is not None:
        command.extend(["--catalog", str(catalog)])
    if artifact is None or manifest is None:
        raise ReleaseError("HR-to-HU handoff requires both a downloaded artifact and its manifest")
    with tempfile.TemporaryDirectory(prefix="hr-hu-handoff-") as handoff_dir:
        manifest_path = Path(handoff_dir) / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
        command.extend(["install-artifact", package, "--artifact", str(artifact), "--manifest", str(manifest_path)])
        result = subprocess.run(privileged_command(command), check=False, text=True)
        if result.returncode:
            raise ReleaseError(f"HU installation for {package} exited with {result.returncode}")
        return {"package": package, "state": "artifact_handed_to_hu", "version": manifest.get("version"), "profile": profile}


def _seed_hu_profiles(config: Path, version: str, production_root: Path, development_root: Path,
                      profiles: tuple[str, ...] = ("production", "development")) -> None:
    """Record the bootstrapped HR/HU releases in production and HU in development."""
    raw = tomllib.loads(config.read_text(encoding="utf-8"))
    configured_profiles = raw.get("profiles", {})
    if not isinstance(configured_profiles, dict):
        raise ReleaseError("HU configuration profiles must be a table")
    missing_profiles = set(profiles) - configured_profiles.keys()
    if missing_profiles:
        raise ReleaseError(f"HU configuration is missing requested profiles: {', '.join(sorted(missing_profiles))}")
    for profile, root in ((name, production_root if name == "production" else development_root)
                          for name in profiles):
        profile_raw = configured_profiles[profile]
        state_root = Path(profile_raw.get("state_root", "state")).expanduser()
        state_path = state_root / "packages" / "helix-updater.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        existing = json.loads(state_path.read_text(encoding="utf-8")) if state_path.is_file() else {}
        prior = existing.get("current")
        release_path = root / "releases" / version
        existing.update({
            "state": "successful",
            "current": version,
            "current_path": str(release_path),
            "previous": prior if prior and prior != version else existing.get("previous"),
            "previous_path": existing.get("current_path") if prior and prior != version else existing.get("previous_path"),
            "failed_releases": existing.get("failed_releases", []),
        })
        temporary = state_path.with_suffix(".json.new")
        temporary.write_text(json.dumps(existing, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(state_path)
        if profile == "production":
            hr_root = default_root("helix-releases")
            hr_release = hr_root / "releases" / __version__
            if hr_release.is_dir():
                hr_state = Path(profile_raw.get("state_root", "state")).expanduser() / "packages" / "helix-releases.json"
                hr_state.parent.mkdir(parents=True, exist_ok=True)
                prior_hr = json.loads(hr_state.read_text(encoding="utf-8")) if hr_state.is_file() else {}
                prior_version = prior_hr.get("current")
                prior_hr.update({"state": "successful", "current": __version__, "current_path": str(hr_release),
                                 "previous": prior_version if prior_version and prior_version != __version__ else prior_hr.get("previous"),
                                 "previous_path": prior_hr.get("current_path") if prior_version and prior_version != __version__ else prior_hr.get("previous_path"),
                                 "failed_releases": prior_hr.get("failed_releases", [])})
                hr_tmp = hr_state.with_suffix(".json.new")
                hr_tmp.write_text(json.dumps(prior_hr, indent=2, sort_keys=True) + "\n", encoding="utf-8")
                hr_tmp.replace(hr_state)


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
        raise ReleaseError(f"invalid release handoff: {path}") from exc
    required = {"protocol", "handoff_id", "contract_id", "contract_hash", "contract", "component", "source_root", "source_commit", "version", "build_command", "test_commands", "source_files", "required_paths"}
    if not isinstance(value, dict) or not required.issubset(value) or value["protocol"] != 1:
        raise ReleaseError("release handoff is missing required fields or uses an unsupported protocol")
    verification = value.get("verification")
    if verification is not None and not isinstance(verification, dict):
        raise ReleaseError("release handoff verification evidence must be an object when provided")
    contract = value["contract"]
    if not isinstance(contract, dict):
        raise ReleaseError("release handoff contract is invalid")
    digest = __import__("hashlib").sha256(json.dumps(contract, sort_keys=True).encode("utf-8")).hexdigest()
    if digest != value["contract_hash"] or contract.get("id") != value["contract_id"]:
        raise ReleaseError("release handoff contract digest is invalid")

    def normalize_python_command(command):
        if not isinstance(command, list) or not command or not all(isinstance(item, str) for item in command):
            return None
        executable = Path(command[0]).name.lower()
        if executable not in {"python", "python3", "python.exe", "python3.exe"}:
            return None
        return ["python", *command[1:]]

    build_command = normalize_python_command(value["build_command"])
    contract_build = normalize_python_command(contract.get("build_command"))
    if build_command is None or contract_build is None or build_command != contract_build:
        raise ReleaseError("release handoff build command differs from the HR contract")
    test_commands = value["test_commands"]
    contract_tests = contract.get("test_commands")
    if not isinstance(test_commands, list) or not test_commands or not isinstance(contract_tests, list):
        raise ReleaseError("release handoff test commands are invalid")
    normalized_tests = [normalize_python_command(command) for command in test_commands]
    normalized_contract_tests = [normalize_python_command(command) for command in contract_tests]
    if any(command is None for command in normalized_tests + normalized_contract_tests) or normalized_tests != normalized_contract_tests:
        raise ReleaseError("release handoff test commands differ from the HR contract")
    if value["required_paths"] != contract.get("required_paths"):
        raise ReleaseError("release handoff required paths differ from the HR contract")
    if not isinstance(value["source_files"], list) or not value["source_files"]:
        raise ReleaseError("release handoff source file list is invalid")
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
        raise ReleaseError("release handoff was generated from a different HR contract")


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
        raise ReleaseError("source commit does not match release handoff")
    if _run(["git", "status", "--short"], cwd=source, label="source status").stdout.strip():
        raise ReleaseError("source checkout is dirty; refusing to package")
    workspace = Path(tempfile.mkdtemp(prefix=f"hr-{handoff['component']}-"))
    try:
        checkout = workspace / "source"
        checkout.mkdir()
        for relative in (*handoff["source_files"], *handoff["required_paths"]):
            relative_path = Path(relative)
            if relative_path.is_absolute() or ".." in relative_path.parts:
                raise ReleaseError(f"handoff source path is unsafe: {relative}")
        for relative in handoff["source_files"]:
            relative_path = Path(relative)
            source_path = source / relative_path
            destination = checkout / relative_path
            if not source_path.exists() or not source_path.resolve().is_relative_to(source):
                raise ReleaseError(f"handoff source path is missing or unsafe: {relative}")
            if source_path.is_dir():
                # Older handoffs may identify a source directory as one entry.
                # Current producers enumerate tracked files individually.
                shutil.copytree(source_path, destination, ignore=shutil.ignore_patterns(".git", ".venv", "__pycache__", "dist", "build"))
            elif source_path.is_file():
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_path, destination)
            else:
                raise ReleaseError(f"handoff source path is not a file or directory: {relative}")
        for relative in handoff["required_paths"]:
            if not (checkout / relative).exists():
                raise ReleaseError(f"contract-required path is missing from handoff source: {relative}")
        output = output.resolve()
        output.mkdir(parents=True, exist_ok=True)
        recipe = handoff["contract"]
        for command in recipe["test_commands"]:
            _run([item.replace("{output}", str(output)) for item in command], cwd=checkout, label="release test")
        _run([item.replace("{output}", str(output)) for item in recipe["build_command"]], cwd=checkout, label="release build")
        artifacts = sorted(output.glob("*.whl"))
        if len(artifacts) != 1:
            raise ReleaseError(f"expected exactly one wheel, found {len(artifacts)}")
        companion_artifacts = _build_companion_artifacts(handoff, checkout, output)
        result = {"handoff_id": handoff["handoff_id"], "component": handoff["component"], "version": handoff["version"], "channel": handoff.get("channel", "dev"), "commit": commit, "artifact": str(artifacts[0]), "companion_artifacts": [str(item) for item in companion_artifacts], "tests": "passed"}
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
                extra_artifacts=companion_artifacts,
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


def _build_companion_artifacts(handoff: dict, checkout: Path, output: Path) -> list[Path]:
    """Build non-wheel runtime payloads that HR must publish with the package.

    HU's Python wheel is portable, but its Windows SCM host is a separate native
    executable. Keeping this decision in HR makes the release boundary explicit:
    production installers consume a built, immutable host payload instead of
    downloading source or requiring a compiler on the target machine.
    """
    if handoff["component"] != "helix-updater":
        return []
    project = checkout / "service-host" / "HelixUpdater.ServiceHost.csproj"
    if not project.is_file():
        raise ReleaseError("HU release handoff is missing service-host/HelixUpdater.ServiceHost.csproj")
    publish_root = Path(tempfile.mkdtemp(prefix="hr-hu-service-host-"))
    try:
        _run(["dotnet", "publish", str(project), "-c", "Release", "-o", str(publish_root), "--nologo"], cwd=checkout, label="Windows service-host build")
        executable = publish_root / "HelixUpdaterService.exe"
        if not executable.is_file():
            raise ReleaseError("Windows service-host build did not produce HelixUpdaterService.exe")
        archive = output / f"helix-updater-service-host-{handoff['version']}-windows-x86_64.zip"
        shutil.make_archive(str(archive.with_suffix("")), "zip", root_dir=publish_root)
        return [archive]
    finally:
        shutil.rmtree(publish_root, ignore_errors=True)


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
    packages_parser = subparsers.add_parser("packages", help="validate and package a release handoff")
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
    install_parser.add_argument("--channel", default=None, help="override the release channel (defaults to stable for production or dev for development)")
    install_parser.add_argument("--profile", choices=("production", "development"), default="production", help="HU runtime profile that receives the component")
    install_parser.add_argument("--target", type=Path, help="installation root; defaults to the host Helix root")
    install_parser.add_argument("--service", help="service to restart after activation")
    install_parser.add_argument("--no-restart", action="store_true")
    bootstrap_parser = subparsers.add_parser("_bootstrap-hu", help=argparse.SUPPRESS)
    bootstrap_parser.add_argument("--artifact", type=Path, required=True)
    bootstrap_parser.add_argument("--version", required=True)
    bootstrap_parser.add_argument("--sha256", required=True)
    bootstrap_parser.add_argument("--profile", choices=("production", "development"), default="production")
    bootstrap_parser.add_argument("--target", type=Path)
    args = parser.parse_args(argv)
    if args.command == "install" and args.channel is None:
        args.channel = "dev" if args.profile == "development" else DEFAULT_RELEASE_CHANNEL
    try:
        if args.command == "packages":
            publish_release = args.publish_release if args.publish_release is not None else args.catalog is None
            result = packages(args.handoff, args.output, catalog=args.catalog, publish_release=publish_release, repository=args.repository, keep_workspace=args.keep_workspace)
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0
        if args.command == "_bootstrap-hu":
            require_elevation()
            candidate = __import__("helix_releases.installer", fromlist=["InstallCandidate"]).InstallCandidate("helix-updater", args.version, DEFAULT_RELEASE_CHANNEL, args.artifact, args.sha256)
            if platform.system().lower() == "windows":
                result = _bootstrap_windows_hu(candidate, args.target)
                print(json.dumps(result, sort_keys=True))
                return 0
            config = HU_CONFIG_PATH
            production_active = _system_service_active("helix-updater.service")
            combined_config = _has_combined_profiles(config)
            if args.profile == "development" and args.target is None:
                legacy_config = None if combined_config else LEGACY_HU_CONFIG_PATH
                if production_active and legacy_config is not None and not legacy_config.is_file():
                    raise ReleaseError("production HU is active but its legacy config could not be found; refusing development bootstrap")
                result = _bootstrap_development_profile(candidate, config, legacy_config=legacy_config)
                print(json.dumps(result, sort_keys=True))
                return 0
            root_prod = args.target or _configured_hu_root(config) or default_root("helix-updater")
            result = install_candidate(candidate, root_prod, restart=False)
            config.parent.mkdir(parents=True, exist_ok=True)
            hu = root_prod / "current" / ".venv" / "bin" / "helix-updater"
            subprocess.run((str(hu), "--config", str(config), "--legacy-config", "/etc/helix/updater/helix-updater.toml", "runtime", "profiles-init", "--catalog", str(_development_catalog_path())), check=True)
            _seed_hu_profiles(config, candidate.version, root_prod, Path("/opt/helix/development/updater"), profiles=("production",))
            subprocess.run((str(hu), "--config", str(config), "--profile", "production", "runtime", "install-services"), check=True)
            subprocess.run(("systemctl", "enable", "helix-updater.service"), check=True)
            subprocess.run(("systemctl", "restart", "helix-updater.service"), check=True)
            result = {"package": "helix-updater", "version": candidate.version, "state": "production_service_started", "production": result, "development": "not_installed", "config": str(config)}
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
                            results.append(_install_hu_candidate(candidate, args.profile, args.target, args.catalog) if candidate.package == "helix-updater" else _invoke_hu_update(candidate.package, args.catalog, args.profile, candidate.artifact, candidate.manifest))
                        finally:
                            __import__("shutil").rmtree(remote.temporary_root, ignore_errors=True)
                    else:
                        results.append(_install_hu_candidate(item, args.profile, args.target, args.catalog) if item.package == "helix-updater" else _invoke_hu_update(item.package, args.catalog, args.profile, item.artifact, item.manifest))
                if any(item["package"] == "hdc" for item in results):
                    _setup_hdc_auth()
                print(json.dumps(results, indent=2, sort_keys=True))
                return 0
            if args.catalog is not None:
                candidate = latest_candidate(args.catalog, args.package, args.channel)
                result = _install_hu_candidate(candidate, args.profile, args.target, args.catalog) if candidate.package == "helix-updater" else _invoke_hu_update(candidate.package, args.catalog, args.profile, candidate.artifact, candidate.manifest)
            else:
                remote = fetch_remote_candidate(repository, args.package, args.channel)
                try:
                    candidate = remote.candidate
                    result = _install_hu_candidate(candidate, args.profile, args.target, args.catalog) if candidate.package == "helix-updater" else _invoke_hu_update(candidate.package, args.catalog, args.profile, candidate.artifact, candidate.manifest)
                finally:
                    __import__("shutil").rmtree(remote.temporary_root, ignore_errors=True)
            if candidate.package == "hdc":
                _setup_hdc_auth()
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0
    except ReleaseError as exc:
        parser.error(str(exc))
    return 2


def _system_service_active(service: str) -> bool:
    if platform.system().lower() == "windows":
        return subprocess.run(("sc.exe", "query", service), check=False,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    return subprocess.run(("systemctl", "is-active", "--quiet", service), check=False,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def _bootstrap_development_profile(candidate, config: Path, legacy_config: Path | None = None) -> dict:
    """Stage paired config if needed, then install/restart only HU development."""
    dev_root = _configured_hu_root(config, "development") or Path("/opt/helix/development/updater")
    dev_result = install_candidate(candidate, dev_root, restart=False,
                                   launcher_dir=Path("/usr/local/libexec/helix-development"))
    dev_hu = dev_root / "current" / ".venv" / "bin" / "helix-updater"
    profiles_init = [str(dev_hu), "--config", str(config)]
    if legacy_config is not None:
        profiles_init.extend(("--legacy-config", str(legacy_config), "--preserve-legacy-config"))
    profiles_init.extend(("runtime", "profiles-init", "--catalog", str(_development_catalog_path())))
    subprocess.run(tuple(profiles_init), check=True)
    _seed_hu_profiles(config, candidate.version, default_root("helix-updater"),
                      dev_root, profiles=("development",))
    subprocess.run((str(dev_hu), "--config", str(config), "--profile", "development",
                    "runtime", "install-services"), check=True)
    subprocess.run(("systemctl", "enable", "helix-updater-dev.service"), check=True)
    subprocess.run(("systemctl", "restart", "helix-updater-dev.service"), check=True)
    return {"package": "helix-updater", "version": candidate.version,
            "state": "development_service_started", "development": dev_result,
            "config": str(config), "production_touched": False}


def _bootstrap_windows_hu(candidate, target: Path | None = None) -> dict:
    """Install production HU and register its native Windows SCM host."""
    host = Path(os.environ.get("HELIX_WINDOWS_SERVICE_HOST", "")).expanduser()
    if not host.is_file():
        raise ReleaseError("Windows HU bootstrap requires HELIX_WINDOWS_SERVICE_HOST to point to the native service host")
    config = HU_CONFIG_PATH
    root = target or _configured_hu_root(config) or default_root("helix-updater")
    result = install_candidate(candidate, root, restart=False)
    release = root / "releases" / candidate.version
    python = release / ".venv" / "Scripts" / "python.exe"
    if not python.is_file():
        raise ReleaseError(f"Windows HU runtime was installed without its Python launcher: {python}")
    catalog = Path(os.environ.get("HELIX_DEVELOPMENT_CATALOG", str(_WINDOWS_HELIX_ROOT / "development" / "catalog")))
    catalog.mkdir(parents=True, exist_ok=True)
    config.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run((str(python), "-m", "helix_updater", "--config", str(config),
                    "runtime", "profiles-init", "--catalog", str(catalog)), check=True)

    service = "HelixUpdater"
    log_root = _WINDOWS_HELIX_ROOT / "production" / "updater" / "logs"
    bin_path = f'"{host}" --service-name "{service}" --profile "production" --root "{root}" --config "{config}" --log-root "{log_root}"'
    query = subprocess.run(("sc.exe", "query", service), check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if query.returncode == 0:
        subprocess.run(("sc.exe", "stop", service), check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        command = ("sc.exe", "config", service, "binPath=", bin_path, "start=", "auto")
    else:
        command = ("sc.exe", "create", service, "binPath=", bin_path, "start=", "auto",
                   "DisplayName=", "Helix Updater")
    subprocess.run(command, check=True)
    subprocess.run(("sc.exe", "failure", service, "reset=", "86400",
                    "actions=", "restart/5000/restart/30000/restart/60000"), check=True)
    subprocess.run(("sc.exe", "start", service), check=True)
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        state = subprocess.run(("sc.exe", "query", service), check=False,
                               capture_output=True, text=True)
        if state.returncode == 0 and "RUNNING" in (state.stdout + state.stderr):
            return {"package": candidate.package, "version": candidate.version,
                    "state": "production_service_started", "path": str(release),
                    "config": str(config)}
        time.sleep(1)
    raise ReleaseError(f"Windows HU service did not reach RUNNING: {service}")


def _has_combined_profiles(config: Path) -> bool:
    if not config.is_file():
        return False
    try:
        raw = tomllib.loads(config.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ReleaseError(f"existing HU configuration is invalid: {config}") from exc
    profiles = raw.get("profiles")
    if profiles is None:
        return False
    if not isinstance(profiles, dict) or not {"production", "development"}.issubset(profiles):
        raise ReleaseError("HU profile configuration must define production and development")
    return True


def _bootstrap_hu(candidate, target: Path | None, profile: str = "production") -> dict:
    command_args = [sys.executable, "-m", "helix_releases.cli", "_bootstrap-hu", "--artifact", str(candidate.artifact), "--version", candidate.version, "--sha256", candidate.sha256, "--profile", profile]
    if target is not None:
        command_args.extend(("--target", str(target)))
    command = privileged_command(command_args)
    result = subprocess.run(command, check=False, text=True)
    if result.returncode:
        raise ReleaseError(f"HU bootstrap exited with {result.returncode}")
    return {"package": candidate.package, "version": candidate.version, "state": "bootstrapped"}


def _hu_profile_ready(profile: str) -> bool:
    """Return true only when the selected Linux HU runtime and service are already active."""
    if platform.system().lower() == "windows":
        service = "HelixUpdater" if profile == "production" else "HelixUpdaterDev"
        config = HU_CONFIG_PATH
        root = _configured_hu_root(config, profile) or default_root("helix-updater")
        activation = root / "installation.json"
        if not config.is_file() or not activation.is_file():
            return False
        result = subprocess.run(("sc.exe", "query", service), check=False, capture_output=True, text=True)
        return result.returncode == 0 and "RUNNING" in (result.stdout + result.stderr)
    if platform.system().lower() != "linux":
        return False
    launcher = HU_PROFILE_LAUNCHERS.get(profile)
    if launcher is None or not HU_CONFIG_PATH.is_file() or not launcher.is_file():
        return False
    service = "helix-updater.service" if profile == "production" else "helix-updater-dev.service"
    check = subprocess.run(("systemctl", "is-active", "--quiet", service), check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return check.returncode == 0


def _install_hu_candidate(candidate, profile: str, target: Path | None, catalog: Path | None) -> dict:
    if target is None and _hu_profile_ready(profile):
        return _invoke_hu_update(candidate.package, catalog, profile, candidate.artifact, candidate.manifest)
    return _bootstrap_hu(candidate, target, profile)


def _configured_hu_root(config: Path, profile: str = "production") -> Path | None:
    """Honor an existing HU target root so upgrade/migration keeps the service's runtime path."""
    if not config.is_file():
        return None
    try:
        raw = tomllib.loads(config.read_text(encoding="utf-8"))
        profiles = raw.get("profiles")
        selected = profiles.get(profile) if isinstance(profiles, dict) else raw
        target = selected["packages"]["helix-updater"]["target"]["root"]
        boundary = selected.get("helix_root")
        if not isinstance(target, str) or (boundary is not None and not isinstance(boundary, str)):
            raise ValueError("invalid HU target path")
        path = Path(target).expanduser()
        if not path.is_absolute() and boundary:
            path = Path(boundary).expanduser() / path
        return path.resolve()
    except (OSError, KeyError, TypeError, ValueError, tomllib.TOMLDecodeError) as exc:
        raise ReleaseError(f"existing HU configuration cannot be used for bootstrap: {config}") from exc


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
