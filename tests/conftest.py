from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def use_disposable_install_lock(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """Keep test installs away from the privileged host-wide lock under /run."""
    monkeypatch.setenv("HELIX_INSTALL_LOCK_PATH", str(tmp_path / "helix-install.lock"))
