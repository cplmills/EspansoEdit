from __future__ import annotations

from pathlib import Path

from app.models.schemas import EspansoConfigUpdate, EspansoConfigValue
from app.services.config_service import EspansoConfigService
from conftest import FakeDiscovery, FakeReloader


def test_config_service_reads_default_config(espanso_root: Path) -> None:
    (espanso_root / "config" / "default.yml").write_text(
        "backend: inject\nshow_icon: false\ncustom_key: keep-me\n",
        encoding="utf-8",
    )
    service = EspansoConfigService(FakeDiscovery(espanso_root), FakeReloader())

    config = service.get_config()

    assert config.default_path == str(espanso_root / "config" / "default.yml")
    assert config.values["backend"].enabled is True
    assert config.values["backend"].value == "inject"
    assert config.values["show_icon"].enabled is True
    assert config.values["show_icon"].value is False
    assert config.unknown_values == {"custom_key": "keep-me"}


def test_config_service_writes_enabled_settings_and_preserves_unknown_keys(espanso_root: Path) -> None:
    default_path = espanso_root / "config" / "default.yml"
    default_path.write_text(
        "backend: clipboard\nshow_icon: false\ncustom_key: keep-me\n",
        encoding="utf-8",
    )
    reloader = FakeReloader()
    service = EspansoConfigService(FakeDiscovery(espanso_root), reloader)

    config = service.update_config(
        EspansoConfigUpdate(
            values=[
                EspansoConfigValue(key="backend", enabled=True, value="inject"),
                EspansoConfigValue(key="show_icon", enabled=False, value=True),
                EspansoConfigValue(key="clipboard_threshold", enabled=True, value=250),
            ]
        )
    )

    text = default_path.read_text(encoding="utf-8")
    assert "backend: inject" in text
    assert "clipboard_threshold: 250" in text
    assert "show_icon:" not in text
    assert "custom_key: keep-me" in text
    assert config.reload is not None
    assert reloader.calls == 1


def test_config_service_creates_default_config_when_missing(espanso_root: Path) -> None:
    service = EspansoConfigService(FakeDiscovery(espanso_root), FakeReloader())

    service.update_config(
        EspansoConfigUpdate(
            values=[
                EspansoConfigValue(key="toggle_key", enabled=True, value="RIGHT_CTRL"),
                EspansoConfigValue(key="word_separators", enabled=True, value=[" ", ".", "\\n"]),
            ]
        )
    )

    text = (espanso_root / "config" / "default.yml").read_text(encoding="utf-8")
    assert "toggle_key: RIGHT_CTRL" in text
    assert "word_separators:" in text
    assert "- ' '" in text
