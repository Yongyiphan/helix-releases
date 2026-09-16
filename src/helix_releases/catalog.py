from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_name(value: str) -> str:
    if not value or Path(value).name != value or value in {".", ".."} or any(char in value for char in "/\\"):
        raise ReleaseError(f"invalid release filename: {value!r}")
    return value


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
    """Publish one independent package release into a public-catalog layout.

    The layout is intentionally compatible with a later GitHub-release adapter:
    each package/version has one manifest and one or more immutable artifacts.
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
        # HU's first contract uses the platform service boundary for the
        # post-activation check. Components without a service must provide a
        # later explicit health-check contract rather than inventing one.
        "healthcheck": {"type": "service"},
        "rollback": {"supported": True},
        "install": {"strategy": "python_wheel", "component": package},
    }
    temporary_manifest = existing.with_suffix(".json.new")
    temporary_manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary_manifest.replace(existing)
    return PublishedArtifact(package, version, channel, filename, digest, commit, existing)


def catalog_manifests(root: Path) -> Iterable[Path]:
    return root.glob("releases/*/*/manifest.json")
