from __future__ import annotations

from pathlib import Path

from app.services.espanso_discovery import EspansoPaths
from app.services.reloader import EspansoReloadService, ReloadResult


class FakeDiscovery:
    def discover(self) -> EspansoPaths:
        root = Path("/tmp/espanso")
        return EspansoPaths(
            installed=True,
            version="espanso 2.2.1",
            running=True,
            config_path=root,
            match_path=root / "match",
            config_dir=root / "config",
            executable="/usr/local/bin/espanso",
        )


class RecordingReloadService(EspansoReloadService):
    def __init__(self, help_text: str) -> None:
        super().__init__(FakeDiscovery())
        self.help_text = help_text
        self.commands: list[list[str]] = []

    def _run(self, command: list[str]) -> ReloadResult:
        self.commands.append(command)
        if command == ["/usr/local/bin/espanso", "--help"]:
            return ReloadResult(True, command, self.help_text, "", 0)
        return ReloadResult(True, command, "", "", 0)


def test_reload_without_reload_command_does_not_restart() -> None:
    service = RecordingReloadService("SUBCOMMANDS:\n    restart       Restart the espanso service\n")

    result = service.reload()

    assert result.success is True
    assert result.command == []
    assert ["/usr/local/bin/espanso", "restart"] not in service.commands


def test_reload_uses_reload_command_when_available() -> None:
    service = RecordingReloadService("SUBCOMMANDS:\n    reload        Reload config\n")

    result = service.reload()

    assert result.success is True
    assert result.command == ["/usr/local/bin/espanso", "reload"]
