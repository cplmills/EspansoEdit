from __future__ import annotations

from app.services.espanso_discovery import EspansoDiscoveryService


def test_discovery_uses_configured_espanso_executable(tmp_path, monkeypatch) -> None:
    executable = tmp_path / "espanso"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o755)
    monkeypatch.setenv("ESPANSO_EXECUTABLE", str(executable))
    monkeypatch.setattr("app.services.espanso_discovery.which", lambda _: None)

    assert EspansoDiscoveryService()._executable() == str(executable)
