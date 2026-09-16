from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import tomllib

from . import __version__
from .catalog import ReleaseError, publish
from .installer import DEFAULT_SERVICES, default_root, fetch_remote_candidate, install_candidate, latest_candidate, list_candidates, remote_candidates, require_elevation


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
    if not contract_path.is_file():
        raise ReleaseError(f"HR contract is unavailable: {contract_path}")
    try:
        local = tomllib.loads(contract_path.read_text(encoding="utf-8")).get("contract")
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ReleaseError(f"HR contract is invalid: {contract_path}") from exc
    if local != handoff["contract"]:
        raise ReleaseError("HDC handoff was generated from a different HR contract")


def packages(handoff_path: Path, output: Path, *, catalog: Path | None = None, keep_workspace: bool = False) -> dict:
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
    packages_parser.add_argument("--keep-workspace", action="store_true")
    install_parser = subparsers.add_parser("install", help="privileged bootstrap installation from an HR catalog")
    install_parser.add_argument("package", help="package alias (hr, hu, hdc), or 'list'")
    install_parser.add_argument("--catalog", type=Path, help="local checkout of the public HR catalog")
    install_parser.add_argument("--repository", default=None, help="public GitHub repository, owner/name")
    install_parser.add_argument("--channel", default="stable")
    install_parser.add_argument("--target", type=Path, help="installation root; defaults to the host Helix root")
    install_parser.add_argument("--service", help="service to restart after activation")
    install_parser.add_argument("--no-restart", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "packages":
            result = packages(args.handoff, args.output, catalog=args.catalog, keep_workspace=args.keep_workspace)
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0
        if args.command == "install":
            require_elevation()
            repository = args.repository or __import__("os").environ.get("HR_RELEASE_REPOSITORY")
            if args.catalog is None and not repository:
                raise ReleaseError("provide --repository owner/name or --catalog PATH")
            if args.package.lower() == "list":
                if repository:
                    for item in remote_candidates(repository, args.channel):
                        print(f"{item.candidate.package}\t{item.candidate.version}\t{item.candidate.channel}\t{item.manifest_url}")
                else:
                    for item in list_candidates(args.catalog, args.channel):
                        print(f"{item.package}\t{item.version}\t{item.channel}\t{item.artifact}")
                return 0
            if repository:
                remote = fetch_remote_candidate(repository, args.package, args.channel)
                try:
                    candidate = remote.candidate
                    result = install_candidate(candidate, args.target or default_root(candidate.package), args.service if args.service is not None else DEFAULT_SERVICES.get(candidate.package), restart=not args.no_restart)
                finally:
                    __import__("shutil").rmtree(remote.temporary_root, ignore_errors=True)
            else:
                candidate = latest_candidate(args.catalog, args.package, args.channel)
                result = install_candidate(candidate, args.target or default_root(candidate.package), args.service if args.service is not None else DEFAULT_SERVICES.get(candidate.package), restart=not args.no_restart)
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0
    except ReleaseError as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
