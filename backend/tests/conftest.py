from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from app.services.espanso_discovery import EspansoPaths
from app.services.reloader import ReloadResult
from app.services.shortcut_service import ShortcutService


class FakeDiscovery:
    def __init__(self, root: Path) -> None:
        self.root = root

    def discover(self) -> EspansoPaths:
        return EspansoPaths(
            installed=True,
            version="2.0-test",
            running=True,
            config_path=self.root,
            match_path=self.root / "match",
            config_dir=self.root / "config",
            executable="/usr/local/bin/espanso",
        )


class FakeReloader:
    def __init__(self, should_fail: bool = False) -> None:
        self.should_fail = should_fail
        self.calls = 0
        self.last_successful_reload = None

    def reload(self) -> ReloadResult:
        self.calls += 1
        if self.should_fail and self.calls == 1:
            return ReloadResult(False, ["espanso", "reload"], "", "simulated failure", 1)
        result = ReloadResult(True, ["espanso", "reload"], "ok", "", 0)
        self.last_successful_reload = result.to_dict()
        return result


@pytest.fixture
def espanso_root(tmp_path: Path) -> Path:
    root = tmp_path / "espanso"
    (root / "match").mkdir(parents=True)
    (root / "config").mkdir()
    return root


@pytest.fixture
def service(espanso_root: Path) -> ShortcutService:
    return ShortcutService(FakeDiscovery(espanso_root), FakeReloader())

