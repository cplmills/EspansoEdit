from __future__ import annotations

import json
import re
import shutil
import ssl
import urllib.error
import urllib.parse
import urllib.request
from base64 import b64decode, b64encode
from binascii import Error as Base64Error
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.models.schemas import (
    AppSettings,
    BackupClearResult,
    BackupGitHubValidation,
    BackupLocationMove,
    BackupSettings,
    BackupSyncResult,
    GitShortcutSyncFile,
    GitShortcutSyncResult,
    GitShortcutSyncSettings,
    GitShortcutSyncSource,
    GitShortcutSyncSourceResult,
    GitShortcutSyncValidation,
    SettingsUpdate,
)
from app.services.backup_service import BackupService
from app.services.espanso_discovery import EspansoDiscoveryService, EspansoPaths
from app.services.reloader import EspansoReloadService
from app.services.yaml_service import YamlMatchService, normalize_newlines
from app.utils.errors import AppError

try:
    import certifi
except ImportError:  # pragma: no cover - fallback for minimal development environments
    certifi = None

SETTINGS_FILE = "espansoedit-settings.json"
SYNC_FILE_PREFIX = "github"


@dataclass(frozen=True)
class GitHubRepoRef:
    owner: str
    repo: str
    branch: str | None = None
    file_path: str | None = None


class AppSettingsService:
    def __init__(
        self,
        discovery: EspansoDiscoveryService | None = None,
        reloader: EspansoReloadService | None = None,
    ) -> None:
        self.discovery = discovery or EspansoDiscoveryService()
        self.reloader = reloader or EspansoReloadService(self.discovery)
        self.yaml = YamlMatchService()
        self.https_context = self._create_https_context()

    def get_settings(self) -> AppSettings:
        path = self._settings_path()
        if not path.exists():
            return AppSettings()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return self._settings_from_payload(payload)
        except (json.JSONDecodeError, ValueError) as exc:
            raise AppError("SETTINGS_INVALID", "EspansoEdit settings could not be read.", str(exc), 422) from exc

    def update_settings(self, payload: SettingsUpdate) -> AppSettings:
        settings = AppSettings(
            theme=payload.theme,
            git_sync=self._normalized_git_settings(payload.git_sync),
            backup=self._normalized_backup_settings(payload.backup),
        )
        for index, source in enumerate(settings.git_sync.sources):
            if source.enabled and not source.repo_url:
                raise AppError("GIT_SYNC_NOT_CONFIGURED", "Enabled GitHub sync sources need a repository URL.", status_code=422)
            if not source.repo_url:
                continue
            validation = self.validate_git_sync(source)
            if not validation.shortcut_file_found:
                raise AppError("GIT_SYNC_VALIDATION_FAILED", validation.message, validation.model_dump(), 422)
            source.branch = validation.branch
            source.write_access = validation.write_access
            repo_ref = self._parse_github_repo(source.repo_url)
            if repo_ref.file_path and not source.file_paths:
                source.file_paths = [repo_ref.file_path]
            settings.git_sync.sources[index] = source
        self._write_settings(settings)
        return settings

    def update_backup_settings(self, payload: BackupSettings) -> BackupSettings:
        settings = self.get_settings()
        settings.backup = self._normalized_backup_settings(payload)
        if settings.backup.location:
            Path(settings.backup.location).expanduser().resolve().mkdir(parents=True, exist_ok=True)
        self._write_settings(settings)
        return settings.backup

    def move_backup_location(self, payload: BackupLocationMove) -> BackupSettings:
        location = self._clean_optional(payload.location)
        if not location:
            raise AppError("BACKUP_LOCATION_REQUIRED", "Choose a backup location.", status_code=422)
        settings = self.get_settings()
        old_root = self.backup_root(settings)
        new_root = Path(location).expanduser().resolve()
        new_root.mkdir(parents=True, exist_ok=True)

        if old_root.exists() and old_root.resolve() != new_root:
            for child in old_root.iterdir():
                destination = new_root / child.name
                if destination.exists():
                    destination = self._unique_destination(new_root, child.name)
                shutil.move(str(child), str(destination))

        settings.backup = self._normalized_backup_settings(settings.backup)
        settings.backup.location = str(new_root)
        self._write_settings(settings)
        return settings.backup

    def clear_backups(self) -> BackupClearResult:
        removed = BackupService(self.backup_root()).clear_backups()
        return BackupClearResult(removed_count=removed)

    def list_backups(self) -> list[Any]:
        return BackupService(self.backup_root()).list_backups()

    def get_backup(self, backup_id: str):
        return BackupService(self.backup_root()).get_backup(backup_id)

    def backup_root(self, settings: AppSettings | None = None) -> Path:
        paths = self._paths_or_error()
        backup_settings = self._normalized_backup_settings((settings or self.get_settings()).backup)
        if backup_settings.location:
            return Path(backup_settings.location).expanduser().resolve()
        return paths.config_path / "shortcut-manager-backups"

    def backup_frequency(self) -> str:
        return self._normalized_backup_settings(self.get_settings().backup).frequency

    def sync_backups_to_github(self) -> BackupSyncResult:
        settings = self.get_settings()
        backup = self._normalized_backup_settings(settings.backup)
        if not backup.github_enabled:
            return BackupSyncResult(settings=backup, message="Backup GitHub sync is disabled.")
        if not backup.github_repo_url:
            raise AppError("BACKUP_SYNC_NOT_CONFIGURED", "Enter a GitHub repository URL for backup sync.", status_code=422)
        if not backup.github_access_token:
            raise AppError("BACKUP_SYNC_TOKEN_REQUIRED", "Enter a GitHub access token with Contents read and write access.", status_code=422)

        source = GitShortcutSyncSource(
            repo_url=backup.github_repo_url,
            access_token=backup.github_access_token,
            branch=backup.github_branch,
        )
        repo_ref = self._parse_github_repo(backup.github_repo_url)
        repo_payload = self._github_json(f"/repos/{repo_ref.owner}/{repo_ref.repo}", source)
        branch = backup.github_branch or repo_ref.branch or self._string_value(repo_payload.get("default_branch")) or "main"
        root = self.backup_root(settings)
        if not root.exists():
            root.mkdir(parents=True, exist_ok=True)

        uploaded_count = 0
        base_path = self._normalize_backup_repo_path(backup.github_path)
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            relative = path.relative_to(root).as_posix()
            remote_path = f"{base_path}/{relative}" if base_path else relative
            sha = self._github_file_sha(repo_ref, branch, remote_path, source)
            self._upload_bytes_to_github(repo_ref, branch, remote_path, path.read_bytes(), sha, source)
            uploaded_count += 1

        backup.github_branch = branch
        backup.last_synced_at = datetime.now(ZoneInfo("Australia/Brisbane")).isoformat(timespec="seconds")
        backup.last_sync_message = f"Uploaded {uploaded_count} backup file{'s' if uploaded_count != 1 else ''}."
        settings.backup = backup
        self._write_settings(settings)
        return BackupSyncResult(
            uploaded_count=uploaded_count,
            repo=f"{repo_ref.owner}/{repo_ref.repo}",
            branch=branch,
            backup_path=base_path,
            last_synced_at=backup.last_synced_at,
            message=backup.last_sync_message,
            settings=backup,
        )

    def validate_backup_github(self, payload: BackupSettings) -> BackupGitHubValidation:
        backup = self._normalized_backup_settings(payload)
        if not backup.github_repo_url:
            raise AppError("BACKUP_SYNC_NOT_CONFIGURED", "Enter a GitHub repository URL for backup sync.", status_code=422)

        source = GitShortcutSyncSource(
            repo_url=backup.github_repo_url,
            access_token=backup.github_access_token,
            branch=backup.github_branch,
        )
        repo_ref = self._parse_github_repo(backup.github_repo_url)
        repo_payload = self._github_json(f"/repos/{repo_ref.owner}/{repo_ref.repo}", source)
        default_branch = self._string_value(repo_payload.get("default_branch")) or "main"
        branch = backup.github_branch or repo_ref.branch or default_branch
        branches = self._github_branches(repo_ref, source)
        if branch not in branches:
            branches = [branch, *branches]
        write_access = self._repo_write_access(repo_payload)
        if not write_access and backup.github_access_token:
            check_path = f"{self._normalize_backup_repo_path(backup.github_path)}/.espansoedit-write-check.yml"
            write_access = self._contents_write_access(repo_ref, branch, check_path, source)
        return BackupGitHubValidation(
            exists=True,
            write_access=write_access,
            repo=f"{repo_ref.owner}/{repo_ref.repo}",
            branch=branch,
            branches=branches,
            message="Repository found. Backup sync can write to this repository." if write_access else "Repository found. Token does not appear to have write access.",
        )

    def validate_git_sync(self, source: GitShortcutSyncSource | None = None) -> GitShortcutSyncValidation:
        source = self._normalized_git_source(source or self._first_configured_source())
        if not source.repo_url:
            raise AppError("GIT_SYNC_NOT_CONFIGURED", "Enter a GitHub repository URL.", status_code=422)

        repo_ref = self._parse_github_repo(source.repo_url)
        branch_hint = source.branch or repo_ref.branch
        repo_payload = self._github_json(f"/repos/{repo_ref.owner}/{repo_ref.repo}", source)
        default_branch = self._string_value(repo_payload.get("default_branch")) or "main"
        branch = branch_hint or default_branch
        branches = self._github_branches(repo_ref, source)
        if branch not in branches:
            branches = [branch, *branches]
        requested_paths = source.file_paths or ([repo_ref.file_path] if repo_ref.file_path else [])
        write_access = False

        if requested_paths:
            files: list[GitShortcutSyncFile] = []
            invalid_paths: list[str] = []
            for path in requested_paths:
                candidate = self._validate_file_candidate(repo_ref, branch, path, source)
                if candidate:
                    files.append(candidate)
                else:
                    invalid_paths.append(path)
            if files and not invalid_paths:
                write_access = self._contents_write_access(repo_ref, branch, files[0].file_path, source)
                return self._validation_success(source, repo_ref, branch, files, write_access, branches)
            joined = ", ".join(invalid_paths or requested_paths)
            return GitShortcutSyncValidation(
                source_id=source.id,
                exists=True,
                shortcut_file_found=False,
                write_access=write_access,
                repo=f"{repo_ref.owner}/{repo_ref.repo}",
                branch=branch,
                branches=branches,
                file_path=(invalid_paths or requested_paths)[0],
                message=f"{joined} did not contain an Espanso matches list.",
            )

        tree = self._github_json(f"/repos/{repo_ref.owner}/{repo_ref.repo}/git/trees/{urllib.parse.quote(branch, safe='')}?recursive=1", source)
        files = [
            candidate
            for candidate_path in self._candidate_paths(tree)
            if (candidate := self._validate_file_candidate(repo_ref, branch, candidate_path, source)) is not None
        ]
        if files:
            write_access = self._contents_write_access(repo_ref, branch, files[0].file_path, source)
            return self._validation_success(source, repo_ref, branch, files, write_access, branches)

        return GitShortcutSyncValidation(
            source_id=source.id,
            exists=True,
            shortcut_file_found=False,
            write_access=write_access,
            repo=f"{repo_ref.owner}/{repo_ref.repo}",
            branch=branch,
            branches=branches,
            message="Repository exists, but no Espanso match file with a matches list was found.",
        )

    def sync_git_shortcuts(self) -> GitShortcutSyncResult:
        settings = self.get_settings()
        git_settings = self._normalized_git_settings(settings.git_sync)
        if not git_settings.enabled:
            settings.git_sync = git_settings
            return GitShortcutSyncResult(settings=settings, changed=False, installed=False)

        source_results: list[GitShortcutSyncSourceResult] = []
        changed = False
        uploaded = False
        target_paths: list[str] = []
        uploaded_paths: list[str] = []
        reload_result = None

        for index, source in enumerate(git_settings.sources):
            source = self._normalized_git_source(source)
            if not source.enabled or not source.repo_url:
                git_settings.sources[index] = source
                continue
            try:
                result = self._sync_source(source)
            except AppError as exc:
                source.last_sync_message = exc.message
                git_settings.sources[index] = source
                result = GitShortcutSyncSourceResult(source_id=source.id, message=exc.message)
            else:
                git_settings.sources[index] = source
                if result.changed:
                    changed = True
                if result.installed:
                    target_paths.extend(result.target_paths)
                if result.uploaded:
                    uploaded = True
                    uploaded_paths.extend(result.uploaded_paths)
            source_results.append(result)

        if target_paths:
            reload_result = self.reloader.reload()

        settings.git_sync = git_settings
        self._write_settings(settings)
        return GitShortcutSyncResult(
            settings=settings,
            changed=changed,
            installed=bool(target_paths),
            uploaded=uploaded,
            target_path=target_paths[0] if target_paths else None,
            target_paths=target_paths,
            uploaded_paths=uploaded_paths,
            validation=source_results[0].validation if source_results and source_results[0].validation else None,
            validations=[result.validation for result in source_results if result.validation],
            source_results=source_results,
            reload=reload_result.to_dict() if reload_result else None,
        )

    def sync_git_shortcuts_on_startup(self) -> None:
        try:
            self.sync_git_shortcuts()
        except AppError:
            return

    def enabled_sources_for_folder(self, folder: str | None) -> list[GitShortcutSyncSource]:
        target_folder = self._normalize_folder(folder)
        settings = self.get_settings()
        return [
            source
            for source in self._normalized_git_settings(settings.git_sync).sources
            if source.enabled and self._normalize_folder(source.folder) == target_folder
        ]

    def disable_git_sync_source(self, source_id: str, remove_shortcuts: bool = False) -> GitShortcutSyncResult:
        settings = self.get_settings()
        git_settings = self._normalized_git_settings(settings.git_sync)
        changed = False
        removed_paths: list[str] = []
        reload_result = None

        for index, source in enumerate(git_settings.sources):
            if source.id != source_id:
                continue

            source.enabled = False
            if remove_shortcuts:
                removed_paths = self._remove_installed_sync_files(source)
                changed = bool(removed_paths)
                source.last_file_shas = {}
                source.last_local_hashes = {}
                source.installed_files = {}
                source.last_sync_message = f"Sync disabled. Removed {len(removed_paths)} synced file{'s' if len(removed_paths) != 1 else ''}."
            else:
                source.last_sync_message = "Sync disabled. Installed shortcuts were kept."

            git_settings.sources[index] = source
            settings.git_sync = git_settings
            self._write_settings(settings)
            if changed:
                reload_result = self.reloader.reload()
            return GitShortcutSyncResult(
                changed=changed,
                installed=False,
                target_path=removed_paths[0] if removed_paths else None,
                target_paths=removed_paths,
                settings=settings,
                reload=reload_result.to_dict() if reload_result else None,
            )

        raise AppError("GIT_SYNC_SOURCE_NOT_FOUND", "GitHub sync source was not found.", status_code=404)

    def _sync_source(self, source: GitShortcutSyncSource) -> GitShortcutSyncSourceResult:
        validation = self.validate_git_sync(source)
        if not validation.shortcut_file_found:
            source.last_sync_message = validation.message
            return GitShortcutSyncSourceResult(source_id=source.id, validation=validation, message=validation.message)

        repo_ref = self._parse_github_repo(source.repo_url or "")
        branch = validation.branch or source.branch or repo_ref.branch or "main"
        changed = False
        target_paths: list[str] = []
        uploaded_paths: list[str] = []
        conflict_paths: list[str] = []
        next_shas = dict(source.last_file_shas)
        next_local_hashes = dict(source.last_local_hashes)
        next_installed = dict(source.installed_files)
        current_paths = {file.file_path for file in validation.files}

        for remote_path, target_name in list(next_installed.items()):
            if remote_path in current_paths:
                continue
            target = self._sync_target(source.folder, target_name)
            if target.exists():
                BackupService(self.backup_root(), self.backup_frequency()).backup_file(target, "github-sync-remove")
                target.unlink()
                changed = True
            next_installed.pop(remote_path, None)
            next_shas.pop(remote_path, None)
            next_local_hashes.pop(remote_path, None)

        for file in validation.files:
            target_name = self._sync_filename(repo_ref, file.file_path)
            target = self._sync_target(source.folder, target_name)
            next_installed[file.file_path] = target_name
            remote_sha = file.file_sha or ""
            previous_remote_sha = next_shas.get(file.file_path)
            previous_local_hash = next_local_hashes.get(file.file_path)
            remote_changed = previous_remote_sha != remote_sha
            remote_content: str | None = None
            local_text: str | None = None
            local_hash: str | None = None
            local_changed = False

            if target.exists():
                local_text = target.read_text(encoding="utf-8")
                local_hash = self._content_hash(local_text)
                if previous_local_hash:
                    local_changed = local_hash != previous_local_hash
                elif validation.write_access:
                    remote_content = self._download_match_file(repo_ref, branch, file.file_path, source)
                    local_changed = normalize_newlines(local_text) != normalize_newlines(remote_content)

            if validation.write_access and target.exists() and local_changed:
                if remote_changed and previous_remote_sha:
                    conflict_paths.append(file.file_path)
                    continue
                assert local_text is not None
                self._validate_match_text(local_text)
                upload = self._upload_match_file(repo_ref, branch, file.file_path, local_text, remote_sha, source)
                next_shas[file.file_path] = upload.get("sha") or remote_sha
                next_local_hashes[file.file_path] = local_hash or self._content_hash(local_text)
                uploaded_paths.append(file.file_path)
                continue

            if target.exists() and not remote_changed:
                if local_hash:
                    next_local_hashes[file.file_path] = local_hash
                continue

            content = remote_content if remote_content is not None else self._download_match_file(repo_ref, branch, file.file_path, source)
            self._validate_match_text(content)
            normalized_content = normalize_newlines(content)
            target.parent.mkdir(parents=True, exist_ok=True)
            BackupService(self.backup_root(), self.backup_frequency()).backup_file(target, "github-sync")
            target.write_text(normalized_content, encoding="utf-8")
            next_shas[file.file_path] = remote_sha
            next_local_hashes[file.file_path] = self._content_hash(normalized_content)
            target_paths.append(str(target))
            changed = True

        source.branch = branch
        source.write_access = validation.write_access
        source.last_file_shas = {path: sha for path, sha in next_shas.items() if sha}
        source.last_local_hashes = {path: content_hash for path, content_hash in next_local_hashes.items() if content_hash}
        source.installed_files = next_installed
        source.last_synced_at = datetime.now(ZoneInfo("Australia/Brisbane")).isoformat(timespec="seconds") if changed or uploaded_paths else source.last_synced_at
        source.last_sync_message = self._sync_message(len(target_paths), len(uploaded_paths), len(conflict_paths), validation.write_access)

        return GitShortcutSyncSourceResult(
            source_id=source.id,
            changed=changed or bool(uploaded_paths),
            installed=changed,
            uploaded=bool(uploaded_paths),
            target_paths=target_paths,
            uploaded_paths=uploaded_paths,
            validation=validation,
            message=source.last_sync_message,
        )

    def _remove_installed_sync_files(self, source: GitShortcutSyncSource) -> list[str]:
        removed_paths: list[str] = []
        backup = BackupService(self.backup_root(), self.backup_frequency())
        for target_name in source.installed_files.values():
            target = self._sync_target(source.folder, target_name)
            if not target.exists() or not target.is_file():
                continue
            backup.backup_file(target, "github-sync-disable")
            target.unlink()
            removed_paths.append(str(target))
        return removed_paths

    def _settings_from_payload(self, payload: Any) -> AppSettings:
        if not isinstance(payload, dict):
            raise ValueError("Settings root must be an object.")
        git_sync = payload.get("git_sync")
        if isinstance(git_sync, dict) and ("repo_url" in git_sync or "file_path" in git_sync):
            legacy_source = GitShortcutSyncSource(
                name=self._string_value(git_sync.get("name")),
                enabled=bool(git_sync.get("enabled")),
                repo_url=self._string_value(git_sync.get("repo_url")),
                access_token=self._string_value(git_sync.get("access_token")),
                branch=self._string_value(git_sync.get("branch")),
                folder=self._string_value(git_sync.get("folder")) or "GitHub",
                file_paths=[git_sync["file_path"]] if isinstance(git_sync.get("file_path"), str) and git_sync["file_path"].strip() else [],
                last_file_shas={git_sync["file_path"]: git_sync["last_file_sha"]}
                if isinstance(git_sync.get("file_path"), str) and isinstance(git_sync.get("last_file_sha"), str)
                else {},
                last_synced_at=self._string_value(git_sync.get("last_synced_at")),
                last_sync_message=self._string_value(git_sync.get("last_sync_message")),
            )
            return AppSettings(
                theme=self._theme_from_payload(payload),
                git_sync=GitShortcutSyncSettings(enabled=bool(git_sync.get("enabled")), sources=[legacy_source]),
                backup=self._normalized_backup_settings(BackupSettings.model_validate(payload.get("backup", {}))),
            )
        return AppSettings.model_validate(payload)

    def _theme_from_payload(self, payload: dict[str, Any]) -> str:
        theme = payload.get("theme")
        return theme if theme in {"dark", "light"} else "dark"

    def _first_configured_source(self) -> GitShortcutSyncSource:
        settings = self.get_settings()
        for source in settings.git_sync.sources:
            if source.repo_url:
                return source
        return GitShortcutSyncSource()

    def _normalized_git_settings(self, settings: GitShortcutSyncSettings) -> GitShortcutSyncSettings:
        return GitShortcutSyncSettings(
            enabled=settings.enabled,
            sources=[self._normalized_git_source(source) for source in settings.sources],
        )

    def _normalized_git_source(self, source: GitShortcutSyncSource) -> GitShortcutSyncSource:
        return GitShortcutSyncSource(
            id=source.id,
            name=self._clean_optional(source.name),
            enabled=source.enabled,
            repo_url=self._clean_optional(source.repo_url),
            access_token=self._clean_optional(source.access_token),
            branch=self._clean_optional(source.branch),
            folder=(source.folder or "GitHub").strip() or "GitHub",
            write_access=source.write_access,
            file_paths=[path for path in (self._clean_optional(path) for path in source.file_paths) if path],
            last_file_shas={path: sha for path, sha in source.last_file_shas.items() if path and sha},
            last_local_hashes={path: content_hash for path, content_hash in source.last_local_hashes.items() if path and content_hash},
            installed_files={path: name for path, name in source.installed_files.items() if path and name},
            last_synced_at=self._clean_optional(source.last_synced_at),
            last_sync_message=self._clean_optional(source.last_sync_message),
        )

    def _normalized_backup_settings(self, settings: BackupSettings) -> BackupSettings:
        return BackupSettings(
            location=self._clean_optional(settings.location),
            frequency=settings.frequency,
            github_enabled=settings.github_enabled,
            github_repo_url=self._clean_optional(settings.github_repo_url),
            github_access_token=self._clean_optional(settings.github_access_token),
            github_branch=self._clean_optional(settings.github_branch),
            github_path=self._normalize_backup_repo_path(settings.github_path),
            last_synced_at=self._clean_optional(settings.last_synced_at),
            last_sync_message=self._clean_optional(settings.last_sync_message),
        )

    def _validation_success(
        self,
        source: GitShortcutSyncSource,
        repo_ref: GitHubRepoRef,
        branch: str,
        files: list[GitShortcutSyncFile],
        write_access: bool,
        branches: list[str],
    ) -> GitShortcutSyncValidation:
        shortcut_count = sum(file.shortcut_count for file in files)
        first = files[0]
        return GitShortcutSyncValidation(
            source_id=source.id,
            exists=True,
            shortcut_file_found=True,
            write_access=write_access,
            repo=f"{repo_ref.owner}/{repo_ref.repo}",
            branch=branch,
            branches=branches,
            file_path=first.file_path,
            file_sha=first.file_sha,
            files=files,
            shortcut_count=shortcut_count,
            message=f"Found {shortcut_count} shortcuts across {len(files)} file{'s' if len(files) != 1 else ''}.",
        )

    def writable_sync_target_for_folder(self, folder: str | None) -> Path | None:
        target_folder = self._normalize_folder(folder)
        try:
            sources = self._normalized_git_settings(self.get_settings().git_sync).sources
        except AppError:
            return None
        candidates = [
            self._sync_target(source.folder, next(iter(source.installed_files.values())))
            for source in sources
            if source.enabled
            and source.write_access
            and self._normalize_folder(source.folder) == target_folder
            and len(source.installed_files) == 1
        ]
        return candidates[0] if len(candidates) == 1 else None

    def _parse_github_repo(self, value: str) -> GitHubRepoRef:
        text = value.strip()
        ssh_match = re.match(r"^git@github\.com:([^/]+)/(.+?)(?:\.git)?$", text)
        if ssh_match:
            return GitHubRepoRef(ssh_match.group(1), ssh_match.group(2))

        parsed = urllib.parse.urlparse(text)
        if parsed.netloc.lower() not in {"github.com", "www.github.com"}:
            raise AppError("INVALID_GITHUB_REPO", "Only GitHub repository URLs are supported for shortcut sync.", status_code=422)
        parts = [urllib.parse.unquote(part) for part in parsed.path.strip("/").split("/") if part]
        if len(parts) < 2:
            raise AppError("INVALID_GITHUB_REPO", "GitHub URL must include an owner and repository.", status_code=422)
        owner = parts[0]
        repo = parts[1][:-4] if parts[1].endswith(".git") else parts[1]
        if len(parts) >= 5 and parts[2] in {"blob", "raw"}:
            return GitHubRepoRef(owner, repo, parts[3], "/".join(parts[4:]))
        return GitHubRepoRef(owner, repo)

    def _validate_file_candidate(self, repo_ref: GitHubRepoRef, branch: str, file_path: str, source: GitShortcutSyncSource) -> GitShortcutSyncFile | None:
        try:
            content_payload = self._github_json(
                f"/repos/{repo_ref.owner}/{repo_ref.repo}/contents/{urllib.parse.quote(file_path, safe='/')}?ref={urllib.parse.quote(branch, safe='')}",
                source,
            )
        except AppError:
            return None
        if not isinstance(content_payload, dict) or content_payload.get("type") != "file":
            return None
        file_sha = self._string_value(content_payload.get("sha"))
        try:
            content = self._match_content_from_payload(content_payload, source)
            shortcut_count = self._shortcut_count(content)
        except AppError:
            return None
        return GitShortcutSyncFile(file_path=file_path, file_sha=file_sha, shortcut_count=shortcut_count)

    def _github_branches(self, repo_ref: GitHubRepoRef, source: GitShortcutSyncSource) -> list[str]:
        try:
            payload = self._github_json(f"/repos/{repo_ref.owner}/{repo_ref.repo}/branches?per_page=100", source)
        except AppError:
            return []
        if not isinstance(payload, list):
            return []
        branches = [
            name
            for item in payload
            if isinstance(item, dict) and isinstance(name := item.get("name"), str) and name.strip()
        ]
        return sorted(dict.fromkeys(branches), key=str.lower)

    def _candidate_paths(self, tree_payload: Any) -> list[str]:
        tree = tree_payload.get("tree") if isinstance(tree_payload, dict) else None
        if not isinstance(tree, list):
            return []
        paths = [
            item.get("path")
            for item in tree
            if isinstance(item, dict)
            and item.get("type") == "blob"
            and isinstance(item.get("path"), str)
            and item.get("path", "").lower().endswith((".yml", ".yaml"))
        ]
        return sorted(paths, key=self._candidate_priority)

    def _candidate_priority(self, path: str) -> tuple[int, str]:
        lower = path.lower()
        if lower in {"base.yml", "base.yaml", "match.yml", "match.yaml"}:
            return (0, lower)
        if lower.startswith(("match/", "matches/")):
            return (1, lower)
        if lower.endswith(("/base.yml", "/base.yaml", "/match.yml", "/match.yaml")):
            return (2, lower)
        return (3, lower)

    def _download_match_file(self, repo_ref: GitHubRepoRef, branch: str, file_path: str, source: GitShortcutSyncSource) -> str:
        content_payload = self._github_json(
            f"/repos/{repo_ref.owner}/{repo_ref.repo}/contents/{urllib.parse.quote(file_path, safe='/')}?ref={urllib.parse.quote(branch, safe='')}",
            source,
        )
        if not isinstance(content_payload, dict):
            raise AppError("GIT_SYNC_DOWNLOAD_FAILED", "GitHub did not return a file for the shortcut path.", status_code=422)
        return self._match_content_from_payload(content_payload, source)

    def _match_content_from_payload(self, content_payload: dict[str, Any], source: GitShortcutSyncSource) -> str:
        content = self._string_value(content_payload.get("content"))
        encoding = self._string_value(content_payload.get("encoding"))
        if content and encoding == "base64":
            try:
                return b64decode(content).decode("utf-8")
            except (Base64Error, UnicodeDecodeError) as exc:
                raise AppError("GIT_SYNC_DOWNLOAD_FAILED", "GitHub returned an unreadable shortcut file.", str(exc), 502) from exc
        download_url = self._string_value(content_payload.get("download_url"))
        if not download_url:
            raise AppError("GIT_SYNC_DOWNLOAD_FAILED", "GitHub did not provide a download URL for the shortcut file.", status_code=422)
        return self._download_url(download_url, source)

    def _upload_match_file(self, repo_ref: GitHubRepoRef, branch: str, file_path: str, content: str, sha: str, source: GitShortcutSyncSource) -> dict[str, str]:
        payload = {
            "message": f"Update Espanso shortcuts in {file_path}",
            "content": b64encode(normalize_newlines(content).encode("utf-8")).decode("ascii"),
            "branch": branch,
        }
        if sha:
            payload["sha"] = sha
        response = self._github_request_json(
            "PUT",
            f"/repos/{repo_ref.owner}/{repo_ref.repo}/contents/{urllib.parse.quote(file_path, safe='/')}",
            source,
            payload,
        )
        content_payload = response.get("content") if isinstance(response, dict) else None
        if not isinstance(content_payload, dict):
            raise AppError("GIT_SYNC_UPLOAD_FAILED", "GitHub did not confirm the uploaded shortcut file.", status_code=502)
        next_sha = self._string_value(content_payload.get("sha"))
        if not next_sha:
            raise AppError("GIT_SYNC_UPLOAD_FAILED", "GitHub did not return an updated file SHA.", status_code=502)
        return {"sha": next_sha}

    def _github_file_sha(self, repo_ref: GitHubRepoRef, branch: str, file_path: str, source: GitShortcutSyncSource) -> str:
        try:
            payload = self._github_json(
                f"/repos/{repo_ref.owner}/{repo_ref.repo}/contents/{urllib.parse.quote(file_path, safe='/')}?ref={urllib.parse.quote(branch, safe='')}",
                source,
            )
        except AppError as exc:
            if exc.code == "GITHUB_NOT_FOUND":
                return ""
            raise
        if isinstance(payload, dict):
            return self._string_value(payload.get("sha")) or ""
        return ""

    def _upload_bytes_to_github(
        self,
        repo_ref: GitHubRepoRef,
        branch: str,
        file_path: str,
        content: bytes,
        sha: str,
        source: GitShortcutSyncSource,
    ) -> None:
        payload = {
            "message": f"Update EspansoEdit backup {file_path}",
            "content": b64encode(content).decode("ascii"),
            "branch": branch,
        }
        if sha:
            payload["sha"] = sha
        self._github_request_json(
            "PUT",
            f"/repos/{repo_ref.owner}/{repo_ref.repo}/contents/{urllib.parse.quote(file_path, safe='/')}",
            source,
            payload,
        )

    def _shortcut_count(self, text: str) -> int:
        data = self._validate_match_text(text)
        matches = data.get("matches") if isinstance(data, dict) else None
        return len(matches) if isinstance(matches, list) else 0

    def _validate_match_text(self, text: str) -> Any:
        data = self.yaml.loads(normalize_newlines(text))
        if not isinstance(data, dict) or not isinstance(data.get("matches"), list):
            raise AppError("GIT_SYNC_NO_MATCHES", "Shortcut file must contain a matches list.", status_code=422)
        return data

    def _sync_target(self, folder: str, filename: str) -> Path:
        paths = self._paths_or_error()
        relative = self._normalize_folder(folder)
        target_dir = paths.match_path if relative == "" else paths.match_path / relative
        target = (target_dir / filename).resolve()
        root = paths.match_path.resolve()
        if not (target == root or root in target.parents):
            raise AppError("PATH_NOT_ALLOWED", "Invalid sync folder.", status_code=403)
        return target

    def _sync_filename(self, repo_ref: GitHubRepoRef, file_path: str) -> str:
        basis = f"{repo_ref.owner}-{repo_ref.repo}-{file_path}"
        slug = "".join(character if character.isalnum() or character in {"-", "_"} else "-" for character in basis.lower())
        slug = "-".join(part for part in slug.split("-") if part)
        return f"{SYNC_FILE_PREFIX}-{slug or 'shortcuts'}.yml"

    def _contents_write_access(self, repo_ref: GitHubRepoRef, branch: str, file_path: str, source: GitShortcutSyncSource) -> bool:
        if not self._clean_optional(source.access_token):
            return False
        payload = {
            "message": "EspansoEdit write permission check",
            "content": b64encode(b"matches:\n").decode("ascii"),
            "branch": branch,
            "sha": "0" * 40,
        }
        try:
            self._github_request_json(
                "PUT",
                f"/repos/{repo_ref.owner}/{repo_ref.repo}/contents/{urllib.parse.quote(file_path, safe='/')}",
                source,
                payload,
            )
        except AppError as exc:
            if exc.code == "GIT_SYNC_UPLOAD_CONFLICT":
                return True
            return False
        return True

    def _repo_write_access(self, payload: Any) -> bool:
        permissions = payload.get("permissions") if isinstance(payload, dict) else None
        if not isinstance(permissions, dict):
            return False
        return bool(permissions.get("push") or permissions.get("admin"))

    def _sync_message(self, installed_count: int, uploaded_count: int, conflict_count: int, write_access: bool) -> str:
        parts: list[str] = []
        if installed_count:
            parts.append(f"Installed {installed_count} file{'s' if installed_count != 1 else ''}.")
        if uploaded_count:
            parts.append(f"Uploaded {uploaded_count} file{'s' if uploaded_count != 1 else ''} to GitHub.")
        if conflict_count:
            parts.append(f"Skipped {conflict_count} file{'s' if conflict_count != 1 else ''} with local and remote changes.")
        if parts:
            return " ".join(parts)
        if write_access:
            return "Already up to date. Two-way sync is enabled."
        return "Already up to date. Token is read-only."

    def _content_hash(self, text: str) -> str:
        return sha256(normalize_newlines(text).encode("utf-8")).hexdigest()

    def _settings_path(self) -> Path:
        paths = self._paths_or_error()
        paths.config_path.mkdir(parents=True, exist_ok=True)
        return paths.config_path / SETTINGS_FILE

    def _write_settings(self, settings: AppSettings) -> None:
        path = self._settings_path()
        path.write_text(settings.model_dump_json(indent=2), encoding="utf-8")

    def _paths_or_error(self) -> EspansoPaths:
        paths = self.discovery.discover()
        if not paths.config_path or not paths.match_path:
            raise AppError("ESPANSO_CONFIG_NOT_FOUND", "Espanso configuration directory could not be detected.", status_code=404)
        return paths

    def _backup_root(self) -> Path:
        return self.backup_root()

    def _normalize_backup_repo_path(self, value: str | None) -> str:
        cleaned = (value or "espansoedit-backups").strip().strip("/")
        if not cleaned:
            return "espansoedit-backups"
        parts = [part.strip() for part in cleaned.split("/") if part.strip()]
        if any(part in {".", ".."} or part.startswith(".") for part in parts):
            raise AppError("INVALID_BACKUP_SYNC_PATH", "Backup GitHub path cannot contain hidden or parent path segments.", status_code=422)
        return "/".join(parts)

    def _unique_destination(self, root: Path, name: str) -> Path:
        base = Path(name)
        stem = base.stem or base.name
        suffix = base.suffix
        counter = 1
        while True:
            candidate = root / f"{stem}-{counter}{suffix}"
            if not candidate.exists():
                return candidate
            counter += 1

    def _normalize_folder(self, folder: str | None) -> str:
        value = (folder or "").strip().strip("/")
        if not value or value.lower() == "root":
            return ""
        parts = [part.strip() for part in value.split("/") if part.strip()]
        if any(part in {".", ".."} or part.startswith(".") for part in parts):
            raise AppError("INVALID_FOLDER", "Folder names cannot contain hidden or parent path segments.", status_code=422)
        if parts and parts[0] == "packages":
            raise AppError("INVALID_FOLDER", "The packages folder is reserved by Espanso.", status_code=422)
        return "/".join(parts)

    def _github_json(self, path: str, source: GitShortcutSyncSource | None = None) -> Any:
        return self._github_request_json("GET", path, source)

    def _github_request_json(
        self,
        method: str,
        path: str,
        source: GitShortcutSyncSource | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        url = f"https://api.github.com{path}"
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(url, data=body, headers=self._github_headers(source), method=method)
        try:
            with self._urlopen(request) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise AppError("GITHUB_NOT_FOUND", "GitHub repository or file was not found. Private repositories require a GitHub access token with read access.", status_code=404) from exc
            if method == "PUT" and exc.code in {401, 403}:
                raise AppError("GIT_SYNC_UPLOAD_FORBIDDEN", "GitHub rejected the upload. Use an access token with repository Contents read and write access.", str(exc), exc.code) from exc
            if method == "PUT" and exc.code in {409, 422}:
                raise AppError("GIT_SYNC_UPLOAD_CONFLICT", "GitHub rejected the upload because the remote file changed. Sync again after reviewing the remote file.", str(exc), 409) from exc
            raise AppError("GITHUB_REQUEST_FAILED", "GitHub request failed.", str(exc), 502) from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise AppError("GITHUB_REQUEST_FAILED", "GitHub request failed.", str(exc), 502) from exc

    def _download_url(self, url: str, source: GitShortcutSyncSource | None = None) -> str:
        request = urllib.request.Request(url, headers=self._github_headers(source, accept_json=False))
        try:
            with self._urlopen(request) as response:
                return response.read().decode("utf-8")
        except (urllib.error.HTTPError, OSError, UnicodeDecodeError) as exc:
            raise AppError("GIT_SYNC_DOWNLOAD_FAILED", "Failed to download shortcut file from GitHub.", str(exc), 502) from exc

    def _urlopen(self, request: urllib.request.Request):
        return urllib.request.urlopen(request, timeout=10, context=self.https_context)

    def _create_https_context(self) -> ssl.SSLContext:
        if certifi is not None:
            return ssl.create_default_context(cafile=certifi.where())
        return ssl.create_default_context()

    def _github_headers(self, source: GitShortcutSyncSource | None = None, accept_json: bool = True) -> dict[str, str]:
        headers = {"User-Agent": "EspansoEdit"}
        if accept_json:
            headers["Accept"] = "application/vnd.github+json"
        token = self._clean_optional(source.access_token) if source else None
        if token:
            headers["Authorization"] = f"Bearer {token}"
            headers["X-GitHub-Api-Version"] = "2022-11-28"
        return headers

    def _clean_optional(self, value: str | None) -> str | None:
        if not value:
            return None
        cleaned = value.strip()
        return cleaned or None

    def _string_value(self, value: Any) -> str | None:
        return value if isinstance(value, str) and value.strip() else None
