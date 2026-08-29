from __future__ import annotations

import json
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from base64 import b64decode
from binascii import Error as Base64Error
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.models.schemas import (
    AppSettings,
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
        settings = AppSettings(theme=payload.theme, git_sync=self._normalized_git_settings(payload.git_sync))
        for index, source in enumerate(settings.git_sync.sources):
            if source.enabled and not source.repo_url:
                raise AppError("GIT_SYNC_NOT_CONFIGURED", "Enabled GitHub sync sources need a repository URL.", status_code=422)
            if not source.repo_url:
                continue
            validation = self.validate_git_sync(source)
            if not validation.shortcut_file_found:
                raise AppError("GIT_SYNC_VALIDATION_FAILED", validation.message, validation.model_dump(), 422)
            source.branch = validation.branch
            repo_ref = self._parse_github_repo(source.repo_url)
            if repo_ref.file_path and not source.file_paths:
                source.file_paths = [repo_ref.file_path]
            settings.git_sync.sources[index] = source
        self._write_settings(settings)
        return settings

    def validate_git_sync(self, source: GitShortcutSyncSource | None = None) -> GitShortcutSyncValidation:
        source = self._normalized_git_source(source or self._first_configured_source())
        if not source.repo_url:
            raise AppError("GIT_SYNC_NOT_CONFIGURED", "Enter a GitHub repository URL.", status_code=422)

        repo_ref = self._parse_github_repo(source.repo_url)
        branch_hint = source.branch or repo_ref.branch
        repo_payload = self._github_json(f"/repos/{repo_ref.owner}/{repo_ref.repo}", source)
        default_branch = self._string_value(repo_payload.get("default_branch")) or "main"
        branch = branch_hint or default_branch
        requested_paths = source.file_paths or ([repo_ref.file_path] if repo_ref.file_path else [])

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
                return self._validation_success(source, repo_ref, branch, files)
            joined = ", ".join(invalid_paths or requested_paths)
            return GitShortcutSyncValidation(
                source_id=source.id,
                exists=True,
                shortcut_file_found=False,
                repo=f"{repo_ref.owner}/{repo_ref.repo}",
                branch=branch,
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
            return self._validation_success(source, repo_ref, branch, files)

        return GitShortcutSyncValidation(
            source_id=source.id,
            exists=True,
            shortcut_file_found=False,
            repo=f"{repo_ref.owner}/{repo_ref.repo}",
            branch=branch,
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
        target_paths: list[str] = []
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
                    target_paths.extend(result.target_paths)
            source_results.append(result)

        if changed:
            reload_result = self.reloader.reload()

        settings.git_sync = git_settings
        self._write_settings(settings)
        return GitShortcutSyncResult(
            settings=settings,
            changed=changed,
            installed=changed,
            target_path=target_paths[0] if target_paths else None,
            target_paths=target_paths,
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
        next_shas = dict(source.last_file_shas)
        next_installed = dict(source.installed_files)
        current_paths = {file.file_path for file in validation.files}

        for remote_path, target_name in list(next_installed.items()):
            if remote_path in current_paths:
                continue
            target = self._sync_target(source.folder, target_name)
            if target.exists():
                BackupService(self._backup_root()).backup_file(target, "github-sync-remove")
                target.unlink()
                changed = True
            next_installed.pop(remote_path, None)
            next_shas.pop(remote_path, None)

        for file in validation.files:
            target_name = self._sync_filename(repo_ref, file.file_path)
            target = self._sync_target(source.folder, target_name)
            next_installed[file.file_path] = target_name
            if target.exists() and next_shas.get(file.file_path) == file.file_sha:
                continue
            content = self._download_match_file(repo_ref, branch, file.file_path, source)
            self._validate_match_text(content)
            target.parent.mkdir(parents=True, exist_ok=True)
            BackupService(self._backup_root()).backup_file(target, "github-sync")
            target.write_text(normalize_newlines(content), encoding="utf-8")
            next_shas[file.file_path] = file.file_sha or ""
            target_paths.append(str(target))
            changed = True

        source.branch = branch
        source.last_file_shas = {path: sha for path, sha in next_shas.items() if sha}
        source.installed_files = next_installed
        source.last_synced_at = datetime.now(ZoneInfo("Australia/Brisbane")).isoformat(timespec="seconds") if changed else source.last_synced_at
        source.last_sync_message = (
            f"Installed {len(target_paths)} file{'s' if len(target_paths) != 1 else ''}."
            if changed
            else "Already up to date."
        )

        return GitShortcutSyncSourceResult(
            source_id=source.id,
            changed=changed,
            installed=changed,
            target_paths=target_paths,
            validation=validation,
            message=source.last_sync_message,
        )

    def _remove_installed_sync_files(self, source: GitShortcutSyncSource) -> list[str]:
        removed_paths: list[str] = []
        backup = BackupService(self._backup_root())
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
            return AppSettings(theme=self._theme_from_payload(payload), git_sync=GitShortcutSyncSettings(enabled=bool(git_sync.get("enabled")), sources=[legacy_source]))
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
            enabled=source.enabled,
            repo_url=self._clean_optional(source.repo_url),
            access_token=self._clean_optional(source.access_token),
            branch=self._clean_optional(source.branch),
            folder=(source.folder or "GitHub").strip() or "GitHub",
            file_paths=[path for path in (self._clean_optional(path) for path in source.file_paths) if path],
            last_file_shas={path: sha for path, sha in source.last_file_shas.items() if path and sha},
            installed_files={path: name for path, name in source.installed_files.items() if path and name},
            last_synced_at=self._clean_optional(source.last_synced_at),
            last_sync_message=self._clean_optional(source.last_sync_message),
        )

    def _validation_success(
        self,
        source: GitShortcutSyncSource,
        repo_ref: GitHubRepoRef,
        branch: str,
        files: list[GitShortcutSyncFile],
    ) -> GitShortcutSyncValidation:
        shortcut_count = sum(file.shortcut_count for file in files)
        first = files[0]
        return GitShortcutSyncValidation(
            source_id=source.id,
            exists=True,
            shortcut_file_found=True,
            repo=f"{repo_ref.owner}/{repo_ref.repo}",
            branch=branch,
            file_path=first.file_path,
            file_sha=first.file_sha,
            files=files,
            shortcut_count=shortcut_count,
            message=f"Found {shortcut_count} shortcuts across {len(files)} file{'s' if len(files) != 1 else ''}.",
        )

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
        return self._paths_or_error().config_path / "shortcut-manager-backups"

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
        url = f"https://api.github.com{path}"
        request = urllib.request.Request(url, headers=self._github_headers(source))
        try:
            with self._urlopen(request) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise AppError("GITHUB_NOT_FOUND", "GitHub repository or file was not found. Private repositories require a GitHub access token with read access.", status_code=404) from exc
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
