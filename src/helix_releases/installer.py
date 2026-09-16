from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import venv

from .catalog import ReleaseError


@dataclass(frozen=True)
class InstallCandidate:
    package: str
    version: str
    channel: str
    artifact: Path
    sha256: str


@dataclass(frozen=True)
class RemoteCandidate:
    candidate: InstallCandidate
    manifest_url: str


@dataclass(frozen=True)
class FetchedCandidate:
    candidate: InstallCandidate
    temporary_root: Path


PACKAGE_ALIASES = {
    "hr": "helix-releases",
    "helix-releases": "helix-releases",
    "hu": "helix-updater",
    "helix-updater": "helix-updater",
    "hdc": "hdc",
}

DEFAULT_SERVICES = {
    "hdc": "hdc-controller.service",
    "helix-updater": "helix-updater.service",
}


def canonical_package(value: str) -> str:
    try:
        return PACKAGE_ALIASES[value.strip().lower()]
    except KeyError as exc:
        raise ReleaseError(f"unsupported Helix install target: {value!r}") from exc


def platform_key() -> str:
    system = "windows" if platform.system().lower() == "windows" else "linux"
    machine = platform.machine().lower().replace("amd64", "x86_64").replace("x64", "x86_64")
    return f"{system}-{machine}"


def require_elevation() -> None:
    """Installation is a privileged bootstrap operation on every host."""
    if platform.system().lower() == "windows":
        try:
            import ctypes
            elevated = bool(ctypes.windll.shell32.IsUserAnAdmin())
        except (AttributeError, OSError):
            elevated = False
    else:
        elevated = hasattr(os, "geteuid") and os.geteuid() == 0
    if not elevated:
        if platform.system().lower() == "windows":
            raise ReleaseError("hr install must be run from an elevated PowerShell")
        raise ReleaseError("hr install must be run with sudo or as root")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_filename(value: str) -> str:
    if not value or Path(value).name != value or value in {".", ".."} or "/" in value or "\\" in value:
        raise ReleaseError(f"invalid catalog artifact filename: {value!r}")
    return value


def latest_candidate(catalog: Path, requested: str, channel: str) -> InstallCandidate:
    package = canonical_package(requested)
    base = catalog.expanduser().resolve() / "releases" / package
    candidates: list[InstallCandidate] = []
    if not base.is_dir():
        raise ReleaseError(f"catalog has no release for {requested}")
    for manifest_path in base.glob("*/manifest.json"):
        try:
            value = json.loads(manifest_path.read_text(encoding="utf-8"))
            if value.get("package") != package or value.get("channel") != channel:
                continue
            artifact_meta = value.get("artifacts", {}).get(platform_key())
            if artifact_meta is None:
                artifact_meta = value.get("artifacts", {}).get("any")
            if not isinstance(artifact_meta, dict):
                continue
            filename, digest = artifact_meta.get("file"), artifact_meta.get("sha256")
            if not isinstance(filename, str) or not isinstance(digest, str):
                continue
            filename = _safe_filename(filename)
            artifact = manifest_path.parent / filename
            if artifact.is_file() and len(digest) == 64:
                candidates.append(InstallCandidate(package, str(value["version"]), channel, artifact, digest.lower()))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    if not candidates:
        raise ReleaseError(f"no valid {channel} release for {requested} on {platform_key()}")
    return max(candidates, key=lambda item: _version_key(item.version))


def list_candidates(catalog: Path, channel: str = "stable") -> list[InstallCandidate]:
    root = catalog.expanduser().resolve() / "releases"
    candidates: list[InstallCandidate] = []
    for package_dir in sorted(root.iterdir()) if root.is_dir() else ():
        if package_dir.is_dir():
            try:
                candidates.append(latest_candidate(catalog, package_dir.name, channel))
            except ReleaseError:
                pass
    return candidates


def _repository(value: str) -> tuple[str, str]:
    parts = value.strip().strip("/").split("/")
    if len(parts) != 2 or any(not part or part in {".", ".."} for part in parts):
        raise ReleaseError(f"invalid public GitHub repository: {value!r}")
    return parts[0], parts[1]


def _public_get(url: str):
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "helix-releases"})
    try:
        return urllib.request.urlopen(request, timeout=30)
    except (OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
        raise ReleaseError(f"public HR catalog request failed: {url}") from exc


def _public_json(url: str):
    try:
        with _public_get(url) as response:
            return json.loads(response.read().decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseError(f"public HR catalog returned invalid JSON: {url}") from exc


def remote_candidates(repository: str, channel: str = "stable") -> list[RemoteCandidate]:
    owner, name = _repository(repository)
    base = f"https://api.github.com/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(name)}/contents/releases"
    listing = _public_json(base)
    if not isinstance(listing, list):
        raise ReleaseError("public HR catalog releases directory is invalid")
    result: list[RemoteCandidate] = []
    for package_item in listing:
        if not isinstance(package_item, dict) or package_item.get("type") != "dir":
            continue
        package = package_item.get("name")
        if not isinstance(package, str):
            continue
        versions = _public_json(f"{base}/{urllib.parse.quote(package)}/")
        if not isinstance(versions, list):
            continue
        for version_item in versions:
            if not isinstance(version_item, dict) or version_item.get("type") != "dir":
                continue
            version = version_item.get("name")
            if not isinstance(version, str):
                continue
            manifest_url = f"https://raw.githubusercontent.com/{urllib.parse.quote(owner)}/{urllib.parse.quote(name)}/main/releases/{urllib.parse.quote(package)}/{urllib.parse.quote(version)}/manifest.json"
            try:
                manifest = _public_json(manifest_url)
                if manifest.get("package") != package or manifest.get("channel") != channel:
                    continue
                artifact_meta = manifest.get("artifacts", {}).get(platform_key()) or manifest.get("artifacts", {}).get("any")
                if not isinstance(artifact_meta, dict):
                    continue
                filename, digest = artifact_meta.get("file"), artifact_meta.get("sha256")
                if not isinstance(filename, str) or not isinstance(digest, str):
                    continue
                filename = _safe_filename(filename)
                result.append(RemoteCandidate(
                    InstallCandidate(package, version, channel, Path(filename), digest.lower()),
                    manifest_url,
                ))
            except (ReleaseError, AttributeError):
                continue
    return result


def fetch_remote_candidate(repository: str, requested: str, channel: str = "stable") -> FetchedCandidate:
    package = canonical_package(requested)
    matches = [item for item in remote_candidates(repository, channel) if item.candidate.package == package]
    if not matches:
        raise ReleaseError(f"no public {channel} release for {requested} on {platform_key()}")
    selected = max(matches, key=lambda item: _version_key(item.candidate.version))
    temporary_root = Path(tempfile.mkdtemp(prefix=f"hr-fetch-{package}-"))
    # Derive the sibling raw artifact URL from the validated manifest URL and
    # validated filename; no GitHub credential or gh CLI is consulted.
    artifact_url = selected.manifest_url.rsplit("/manifest.json", 1)[0] + "/" + urllib.parse.quote(selected.candidate.artifact.name)
    destination = temporary_root / selected.candidate.artifact.name
    try:
        with _public_get(artifact_url) as response:
            destination.write_bytes(response.read())
    except Exception:
        shutil.rmtree(temporary_root, ignore_errors=True)
        raise ReleaseError(f"could not download public release artifact: {artifact_url}")
    return FetchedCandidate(InstallCandidate(package, selected.candidate.version, channel, destination, selected.candidate.sha256), temporary_root)


def _version_key(value: str) -> tuple:
    result = []
    for part in value.split("."):
        digits = "".join(char for char in part if char.isdigit())
        result.append((0, int(digits)) if digits else (1, part))
    return tuple(result)


def _entrypoint(package: str) -> str:
    return {"hdc": "hdc", "helix-updater": "helix-updater", "helix-releases": "hr"}[package]


def default_root(package: str) -> Path:
    if platform.system().lower() == "windows":
        return Path(os.environ.get("PROGRAMFILES", r"C:\\Program Files")) / "Helix" / package
    return Path("/opt/helix") / package


def _run(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, cwd=cwd, check=False, capture_output=True, text=True)
    if result.returncode:
        detail = (result.stderr or result.stdout or "command failed").strip()
        raise ReleaseError(detail[-2000:])
    return result


def _restart_service(service: str | None) -> None:
    if not service:
        return
    if platform.system().lower() == "windows":
        query = subprocess.run(("sc.exe", "query", service), check=False, capture_output=True, text=True)
        if query.returncode == 0:
            _run(["sc.exe", "stop", service])
            _run(["sc.exe", "start", service])
        return
    active = subprocess.run(("systemctl", "is-active", "--quiet", service), check=False)
    if active.returncode == 0:
        _run(["systemctl", "restart", service])


def install_candidate(candidate: InstallCandidate, target: Path, service: str | None = None, *, restart: bool = True, launcher_dir: Path | None = None) -> dict:
    actual = _sha256(candidate.artifact)
    if actual != candidate.sha256:
        raise ReleaseError(f"artifact checksum mismatch for {candidate.artifact.name}")
    target = target.expanduser().resolve()
    release = target / "releases" / candidate.version
    target.mkdir(parents=True, exist_ok=True)
    (target / "releases").mkdir(parents=True, exist_ok=True)
    if release.exists():
        existing = release / ".artifact.sha256"
        if existing.is_file() and existing.read_text(encoding="utf-8").strip() == actual:
            return {"package": candidate.package, "version": candidate.version, "state": "already_installed", "path": str(release)}
        raise ReleaseError(f"release already exists with different contents: {release}")
    temporary = Path(tempfile.mkdtemp(prefix=f"{candidate.package}-", dir=target))
    staged = temporary / candidate.version
    try:
        staged.mkdir()
        environment = staged / ".venv"
        venv.EnvBuilder(with_pip=True, clear=True).create(environment)
        pip = environment / ("Scripts" if platform.system().lower() == "windows" else "bin") / ("pip.exe" if platform.system().lower() == "windows" else "pip")
        _run([str(pip), "install", "--no-cache-dir", "--force-reinstall", str(candidate.artifact)])
        (staged / ".artifact.sha256").write_text(actual + "\n", encoding="utf-8")
        staged.rename(release)
        current = target / "current"
        if platform.system().lower() == "windows":
            state = target / "installation.json"
            state.write_text(json.dumps({"schema": 1, "active": str(release), "package": candidate.package}, indent=2) + "\n", encoding="utf-8")
        else:
            link = target / ".current.new"
            link.symlink_to(release, target_is_directory=True)
            link.replace(current)
            launcher_root = launcher_dir or Path("/usr/local/bin")
            launcher_root.mkdir(parents=True, exist_ok=True)
            launcher = launcher_root / _entrypoint(candidate.package)
            launcher.write_text(f"#!/bin/sh\nexec {current}/.venv/bin/{_entrypoint(candidate.package)} \"$@\"\n", encoding="utf-8")
            launcher.chmod(0o755)
        if restart:
            _restart_service(service)
        return {"package": candidate.package, "version": candidate.version, "state": "installed", "path": str(release), "sha256": actual}
    except Exception:
        shutil.rmtree(staged, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
