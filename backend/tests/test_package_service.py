from __future__ import annotations

from pathlib import Path

import pytest

from app.models.schemas import PackageInstall
from app.services.package_service import EspansoPackageService
from app.utils.errors import AppError
from conftest import FakeDiscovery, FakeReloader


class FakePackageService(EspansoPackageService):
    def __init__(self, root: Path) -> None:
        super().__init__(FakeDiscovery(root), FakeReloader())
        self.commands: list[list[str]] = []

    def _run(self, command: list[str], timeout: int) -> dict:
        self.commands.append(command)
        return {"command": command, "stdout": "ok", "stderr": "", "exit_code": 0}


def test_listing_installed_packages(espanso_root: Path) -> None:
    package_dir = espanso_root / "match" / "packages" / "basic-emojis"
    package_dir.mkdir(parents=True)
    (package_dir / "package.yml").write_text(
        'package:\n  version: "1.2.3"\n  description: Emoji shortcuts\nmatches:\n  - trigger: ":wave"\n    replace: "hello"\n',
        encoding="utf-8",
    )
    service = FakePackageService(espanso_root)

    packages = service.list_packages()

    assert len(packages) == 1
    assert packages[0].name == "basic-emojis"
    assert packages[0].version == "1.2.3"
    assert packages[0].shortcut_count == 1
    assert packages[0].yaml_valid is True


def test_install_package_builds_espanso_command(espanso_root: Path) -> None:
    service = FakePackageService(espanso_root)

    result = service.install_package(PackageInstall(name="basic-emojis", version="1.0.0", force=True, refresh_index=True))

    assert service.commands[0] == ["/usr/local/bin/espanso", "package", "install", "--force", "--refresh-index", "--version", "1.0.0", "basic-emojis"]
    assert result["exit_code"] == 0


def test_install_git_package_builds_espanso_command(espanso_root: Path) -> None:
    service = FakePackageService(espanso_root)

    service.install_package(
        PackageInstall(
            name="custom",
            git="https://example.com/repo.git",
            branch="main",
            external=True,
            use_native_git=True,
        )
    )

    assert service.commands[0] == [
        "/usr/local/bin/espanso",
        "package",
        "install",
        "--external",
        "--use-native-git",
        "--git",
        "https://example.com/repo.git",
        "--git-branch",
        "main",
        "custom",
    ]


def test_rejecting_invalid_package_name(espanso_root: Path) -> None:
    service = FakePackageService(espanso_root)

    with pytest.raises(AppError) as exc:
        service.install_package(PackageInstall(name="../bad"))

    assert exc.value.code == "INVALID_PACKAGE"
