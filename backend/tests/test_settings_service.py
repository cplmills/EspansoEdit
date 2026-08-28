from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.models.schemas import GitShortcutSyncSettings, GitShortcutSyncSource, SettingsUpdate
from app.services.settings_service import AppSettingsService
from app.utils.errors import AppError
from conftest import FakeDiscovery, FakeReloader


class FakeSettingsService(AppSettingsService):
    def __init__(self, root: Path, repos: dict[str, dict[str, tuple[str, str]]]) -> None:
        super().__init__(FakeDiscovery(root), FakeReloader())
        self.repos = repos

    def _github_json(self, path: str) -> Any:
        parts = path.split("/")
        if len(parts) >= 4 and parts[1] == "repos":
            repo_key = f"{parts[2]}/{parts[3]}"
            if repo_key not in self.repos:
                raise AppError("GITHUB_NOT_FOUND", "Not found.", status_code=404)
            if len(parts) == 4:
                return {"default_branch": "main"}
            if path == f"/repos/{repo_key}/git/trees/main?recursive=1":
                return {"tree": [{"type": "blob", "path": file_path} for file_path in self.repos[repo_key]]}
            contents_prefix = f"/repos/{repo_key}/contents/"
            if path.startswith(contents_prefix):
                file_path = path.removeprefix(contents_prefix).split("?ref=", 1)[0]
                if file_path not in self.repos[repo_key]:
                    raise AppError("GITHUB_NOT_FOUND", "Not found.", status_code=404)
                _, sha = self.repos[repo_key][file_path]
                return {"type": "file", "download_url": f"https://raw.test/{repo_key}/{file_path}", "sha": sha}
        raise AppError("GITHUB_NOT_FOUND", "Not found.", status_code=404)

    def _download_url(self, url: str) -> str:
        file_key = url.removeprefix("https://raw.test/")
        owner, repo, file_path = file_key.split("/", 2)
        return self.repos[f"{owner}/{repo}"][file_path][0]


def test_saving_git_sync_settings_validates_multiple_files(espanso_root: Path) -> None:
    service = FakeSettingsService(
        espanso_root,
        {
            "acme/shortcuts": {
                "base.yml": ('matches:\n  - trigger: ":hello"\n    replace: "Hello"\n', "sha-1"),
                "work.yml": ('matches:\n  - trigger: ":work"\n    replace: "Work"\n', "sha-2"),
            }
        },
    )

    settings = service.update_settings(
        SettingsUpdate(
            git_sync=GitShortcutSyncSettings(
                enabled=True,
                sources=[
                    GitShortcutSyncSource(
                        id="source-1",
                        enabled=True,
                        repo_url="https://github.com/acme/shortcuts",
                        folder="Shared",
                        file_paths=["base.yml", "work.yml"],
                    )
                ],
            )
        )
    )

    assert settings.git_sync.enabled is True
    assert settings.git_sync.sources[0].branch == "main"
    assert settings.git_sync.sources[0].file_paths == ["base.yml", "work.yml"]


def test_saving_settings_preserves_theme(espanso_root: Path) -> None:
    service = FakeSettingsService(espanso_root, {})

    settings = service.update_settings(SettingsUpdate(theme="light", git_sync=GitShortcutSyncSettings()))

    assert settings.theme == "light"
    assert service.get_settings().theme == "light"


def test_syncing_git_shortcuts_installs_multiple_files_and_repos(espanso_root: Path) -> None:
    service = FakeSettingsService(
        espanso_root,
        {
            "acme/shortcuts": {
                "match/base.yml": ('matches:\n  - trigger: ":hello"\n    replace: "Hello"\n', "sha-1"),
                "match/work.yml": ('matches:\n  - trigger: ":work"\n    replace: "Work"\n', "sha-2"),
            },
            "beta/snippets": {
                "base.yml": ('matches:\n  - trigger: ":beta"\n    replace: "Beta"\n', "sha-3"),
            },
        },
    )
    service.update_settings(
        SettingsUpdate(
            git_sync=GitShortcutSyncSettings(
                enabled=True,
                sources=[
                    GitShortcutSyncSource(
                        id="source-1",
                        enabled=True,
                        repo_url="https://github.com/acme/shortcuts",
                        folder="Shared",
                    ),
                    GitShortcutSyncSource(
                        id="source-2",
                        enabled=True,
                        repo_url="https://github.com/beta/snippets",
                        folder="Beta",
                    ),
                ],
            )
        )
    )

    first = service.sync_git_shortcuts()
    second = service.sync_git_shortcuts()

    assert first.changed is True
    assert first.installed is True
    assert len(first.target_paths) == 3
    assert (espanso_root / "match" / "Shared" / "github-acme-shortcuts-match-base-yml.yml").exists()
    assert (espanso_root / "match" / "Shared" / "github-acme-shortcuts-match-work-yml.yml").exists()
    assert (espanso_root / "match" / "Beta" / "github-beta-snippets-base-yml.yml").exists()
    assert second.changed is False
    assert second.installed is False


def test_rejecting_explicit_invalid_file_in_multi_file_source(espanso_root: Path) -> None:
    service = FakeSettingsService(
        espanso_root,
        {
            "acme/shortcuts": {
                "base.yml": ('matches:\n  - trigger: ":hello"\n    replace: "Hello"\n', "sha-1"),
                "notes.yml": ("name: docs\n", "sha-2"),
            }
        },
    )

    with pytest.raises(AppError) as exc:
        service.update_settings(
            SettingsUpdate(
                git_sync=GitShortcutSyncSettings(
                    enabled=True,
                    sources=[
                        GitShortcutSyncSource(
                            enabled=True,
                            repo_url="https://github.com/acme/shortcuts",
                            folder="Shared",
                            file_paths=["base.yml", "notes.yml"],
                        )
                    ],
                )
            )
        )

    assert exc.value.code == "GIT_SYNC_VALIDATION_FAILED"
    assert "notes.yml" in exc.value.message


def test_rejecting_git_repo_without_espanso_match_file(espanso_root: Path) -> None:
    service = FakeSettingsService(
        espanso_root,
        {"acme/shortcuts": {"README.yml": ("name: docs\n", "sha-1")}},
    )

    with pytest.raises(AppError) as exc:
        service.update_settings(
            SettingsUpdate(
                git_sync=GitShortcutSyncSettings(
                    enabled=True,
                    sources=[
                        GitShortcutSyncSource(
                            enabled=True,
                            repo_url="https://github.com/acme/shortcuts",
                            folder="Shared",
                        )
                    ],
                )
            )
        )

    assert exc.value.code == "GIT_SYNC_VALIDATION_FAILED"


def test_migrating_legacy_single_git_sync_settings(espanso_root: Path) -> None:
    settings_path = espanso_root / "espansoedit-settings.json"
    settings_path.write_text(
        '{"git_sync":{"enabled":true,"repo_url":"https://github.com/acme/shortcuts","branch":"main","file_path":"base.yml","folder":"Shared","last_file_sha":"sha-1"}}',
        encoding="utf-8",
    )
    service = FakeSettingsService(
        espanso_root,
        {"acme/shortcuts": {"base.yml": ('matches:\n  - trigger: ":hello"\n    replace: "Hello"\n', "sha-1")}},
    )

    settings = service.get_settings()

    assert settings.git_sync.enabled is True
    assert len(settings.git_sync.sources) == 1
    assert settings.git_sync.sources[0].repo_url == "https://github.com/acme/shortcuts"
    assert settings.git_sync.sources[0].file_paths == ["base.yml"]
