from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import subprocess
from typing import Iterable


class ReleaseError(ValueError):
    pass


@dataclass(frozen=True)
class PublishedArtifact:
    package: str
    version: str
    channel: str
    file: str
    sha256: str
    commit: str
    manifest: Path


@dataclass(frozen=True)
class PublishedGitHubRelease:
    package: str
    version: str
    channel: str
    tag: str
    file: str
    sha256: str
    manifest_file: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_name(value: str) -> str:
    if not value or Path(value).name != value or value in {".", ".."} or any(char in value for char in "/\\"):
        raise ReleaseError(f"invalid release filename: {value!r}")
    return value


def release_tag(package: str, version: str) -> str:
    package_name = _safe_name(package)
    version_name = _safe_name(version)
    parts = version_name.split(".")
    if len(parts) != 3 or any(
        not part.isdigit() or (part != "0" and part.startswith("0"))
        for part in parts
    ):
        raise ReleaseError("published versions must use MAJOR.MINOR.PATCH (for example 1.2.3)")
    return f"{package_name}-v{version_name}"


def _manifest(
    *, package: str, version: str, channel: str, commit: str, filename: str,
    digest: str, updater_requirement: str | None = None,
    runtime_assets: dict | None = None,
) -> dict:
    manifest = {
        "schema": 1,
        "package": package,
        "version": version,
        "channel": channel,
        "commit": commit,
        "published_at": _now(),
        "artifacts": {
            "linux-x86_64": {"file": filename, "sha256": digest},
            "windows-x86_64": {"file": filename, "sha256": digest},
        },
        "requirements": {"updater": updater_requirement} if updater_requirement else {},
        "healthcheck": {"type": "service"},
        "rollback": {"supported": True},
        "install": {"strategy": "python_wheel", "component": package},
    }
    if runtime_assets:
        manifest["runtime_assets"] = runtime_assets
    return manifest


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def publish(
    *,
    catalog_root: Path,
    package: str,
    version: str,
    channel: str,
    commit: str,
    artifact: Path,
    updater_requirement: str | None = None,
) -> PublishedArtifact:
    """Write one independent package release into an explicit local catalog.

    This path is for isolated development runtime rehearsals. Production
    publication uses :func:`publish_github_release` and GitHub Release assets.
    """
    if not artifact.is_file():
        raise ReleaseError(f"artifact does not exist: {artifact}")
    filename = _safe_name(artifact.name)
    target = catalog_root / "releases" / package / version
    target.mkdir(parents=True, exist_ok=True)
    destination = target / filename
    digest = _sha256(artifact)
    existing = target / "manifest.json"
    if existing.exists():
        raw = json.loads(existing.read_text(encoding="utf-8"))
        old_digests = {item.get("sha256") for item in raw.get("artifacts", {}).values() if isinstance(item, dict)}
        if old_digests and digest not in old_digests:
            raise ReleaseError("release version already exists with a different artifact")
    temporary = destination.with_suffix(destination.suffix + ".new")
    shutil.copyfile(artifact, temporary)
    temporary.replace(destination)
    manifest = _manifest(package=package, version=version, channel=channel, commit=commit,
                         filename=filename, digest=digest, updater_requirement=updater_requirement)
    temporary_manifest = existing.with_suffix(".json.new")
    temporary_manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary_manifest.replace(existing)
    return PublishedArtifact(package, version, channel, filename, digest, commit, existing)


def publish_github_release(
    *, repository: str, package: str, version: str, channel: str, commit: str,
    artifact: Path, updater_requirement: str | None = None,
    extra_artifacts: Iterable[Path] = (),
    target: str = "main",
    runner=subprocess.run,
) -> PublishedGitHubRelease:
    """Publish one immutable component release through the authenticated gh CLI.

    The release contains the artifact and its HU manifest. No catalog commit is
    required; the public GitHub Releases API is the discovery surface.
    """
    if not artifact.is_file():
        raise ReleaseError(f"artifact does not exist: {artifact}")
    if not repository or repository.count("/") != 1:
        raise ReleaseError(f"invalid GitHub repository: {repository!r}")
    filename = _safe_name(artifact.name)
    tag = release_tag(package, version)
    manifest_name = f"{package}-{version}.manifest.json"
    digest = _sha256(artifact)
    extras = []
    for extra in extra_artifacts:
        if not extra.is_file():
            raise ReleaseError(f"release companion artifact does not exist: {extra}")
        extras.append((_safe_name(extra.name), extra, _sha256(extra)))
    runtime_assets = {
        "windows-x86_64": {"file": name, "sha256": digest}
        for name, _, digest in extras
        if name.startswith("helix-updater-service-host-")
    }
    manifest = _manifest(package=package, version=version, channel=channel, commit=commit,
                         filename=filename, digest=digest, updater_requirement=updater_requirement,
                         runtime_assets=runtime_assets or None)
    with tempfile.TemporaryDirectory(prefix="hr-release-") as directory:
        manifest_path = Path(directory) / manifest_name
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        command = [
            "gh", "release", "create", tag, str(artifact),
            *(str(path) for _, path, _ in extras), str(manifest_path),
            "--repo", repository, "--title", f"{package} {version}",
            "--notes", f"Helix {package} {version} ({channel})", "--target", target,
        ]
        result = runner(command, check=False, capture_output=True, text=True)
        if result.returncode:
            detail = (result.stderr or result.stdout or "gh release create failed").strip()
            raise ReleaseError(detail[-2000:])
    return PublishedGitHubRelease(package, version, channel, tag, filename, digest, manifest_name)


def catalog_manifests(root: Path) -> Iterable[Path]:
    return root.glob("releases/*/*/manifest.json")
