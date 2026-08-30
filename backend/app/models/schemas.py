from __future__ import annotations

from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Any = None


class ApiResult(BaseModel):
    success: bool = True
    error: ErrorBody | None = None


class EspansoStatus(BaseModel):
    installed: bool
    version: str | None = None
    running: bool
    config_path: str | None = None
    match_path: str | None = None
    config_dir: str | None = None
    executable: str | None = None
    yaml_valid: bool = True
    duplicate_triggers: list[dict[str, Any]] = Field(default_factory=list)
    last_reload: dict[str, Any] | None = None


class Shortcut(BaseModel):
    id: str
    trigger: str | None = None
    replace: str | None = None
    form: str | None = None
    form_fields: Any = None
    form_fields_yaml: str | None = None
    label: str | None = None
    word: bool | None = None
    propagate_case: bool | None = None
    case_insensitive: bool | None = None
    uppercase_style: str | None = None
    force_mode: str | None = None
    folder: str
    file: str
    path: str
    editable: bool
    supported: bool
    kind: str = "basic"
    preview: str | None = None
    raw_yaml: str | None = None


class ShortcutCreate(BaseModel):
    trigger: str
    replace: str = ""
    form: str | None = None
    form_fields_yaml: str | None = None
    folder: str | None = None
    label: str | None = None
    word: bool = False
    propagate_case: bool = False
    case_insensitive: bool = False
    uppercase_style: str | None = None
    force_mode: str | None = None


class ShortcutUpdate(BaseModel):
    trigger: str
    replace: str = ""
    form: str | None = None
    form_fields_yaml: str | None = None
    label: str | None = None
    word: bool = False
    propagate_case: bool = False
    case_insensitive: bool = False
    uppercase_style: str | None = None
    force_mode: str | None = None


class ShortcutRawUpdate(BaseModel):
    yaml: str


class ShortcutRawCreate(BaseModel):
    yaml: str
    folder: str | None = None


class ShortcutMove(BaseModel):
    folder: str | None = None


class MacOSTextReplacementItem(BaseModel):
    trigger: str
    replacement: str
    enabled: bool = True


class MacOSTextReplacementPreview(ApiResult):
    available: bool
    macos_version: str | None = None
    source_path: str | None = None
    source_key: str | None = None
    items: list[MacOSTextReplacementItem] = Field(default_factory=list)
    unsupported_count: int = 0


class MacOSTextReplacementImport(BaseModel):
    folder: str | None = None
    replacements: list[MacOSTextReplacementItem] | None = None


class MacOSTextReplacementSkip(BaseModel):
    trigger: str | None = None
    replacement: str | None = None
    reason: str


class MacOSTextReplacementImportResult(ApiResult):
    source_path: str | None = None
    total_found: int = 0
    imported_count: int = 0
    skipped_count: int = 0
    imported: list[Shortcut] = Field(default_factory=list)
    skipped: list[MacOSTextReplacementSkip] = Field(default_factory=list)
    reload: dict[str, Any] | None = None


class GitShortcutSyncFile(BaseModel):
    file_path: str
    file_sha: str | None = None
    shortcut_count: int = 0


class GitShortcutSyncSource(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    name: str | None = None
    enabled: bool = False
    repo_url: str | None = None
    access_token: str | None = None
    branch: str | None = None
    folder: str = "GitHub"
    write_access: bool = False
    file_paths: list[str] = Field(default_factory=list)
    last_file_shas: dict[str, str] = Field(default_factory=dict)
    last_local_hashes: dict[str, str] = Field(default_factory=dict)
    installed_files: dict[str, str] = Field(default_factory=dict)
    last_synced_at: str | None = None
    last_sync_message: str | None = None


class GitShortcutSyncSettings(BaseModel):
    enabled: bool = False
    sources: list[GitShortcutSyncSource] = Field(default_factory=list)


class BackupSettings(BaseModel):
    location: str | None = None
    frequency: Literal["always", "daily", "manual"] = "always"
    github_enabled: bool = False
    github_repo_url: str | None = None
    github_access_token: str | None = None
    github_branch: str | None = None
    github_path: str = "espansoedit-backups"
    last_synced_at: str | None = None
    last_sync_message: str | None = None


class AppSettings(BaseModel):
    theme: Literal["dark", "light"] = "dark"
    git_sync: GitShortcutSyncSettings = Field(default_factory=GitShortcutSyncSettings)
    backup: BackupSettings = Field(default_factory=BackupSettings)


class SettingsUpdate(BaseModel):
    theme: Literal["dark", "light"] = "dark"
    git_sync: GitShortcutSyncSettings
    backup: BackupSettings = Field(default_factory=BackupSettings)


class GitShortcutSyncValidation(ApiResult):
    source_id: str | None = None
    exists: bool = False
    shortcut_file_found: bool = False
    write_access: bool = False
    repo: str | None = None
    branch: str | None = None
    branches: list[str] = Field(default_factory=list)
    file_path: str | None = None
    file_sha: str | None = None
    files: list[GitShortcutSyncFile] = Field(default_factory=list)
    shortcut_count: int = 0
    message: str = ""


class GitShortcutSyncSourceResult(BaseModel):
    source_id: str
    changed: bool = False
    installed: bool = False
    uploaded: bool = False
    target_paths: list[str] = Field(default_factory=list)
    uploaded_paths: list[str] = Field(default_factory=list)
    validation: GitShortcutSyncValidation | None = None
    message: str = ""


class GitShortcutSyncDisable(BaseModel):
    remove_shortcuts: bool = False


class GitShortcutSyncResult(ApiResult):
    changed: bool = False
    installed: bool = False
    uploaded: bool = False
    target_path: str | None = None
    target_paths: list[str] = Field(default_factory=list)
    uploaded_paths: list[str] = Field(default_factory=list)
    validation: GitShortcutSyncValidation | None = None
    validations: list[GitShortcutSyncValidation] = Field(default_factory=list)
    source_results: list[GitShortcutSyncSourceResult] = Field(default_factory=list)
    settings: AppSettings | None = None
    reload: dict[str, Any] | None = None


class BackupLocationMove(BaseModel):
    location: str


class BackupClearResult(ApiResult):
    removed_count: int = 0


class BackupSyncResult(ApiResult):
    uploaded_count: int = 0
    repo: str | None = None
    branch: str | None = None
    backup_path: str | None = None
    last_synced_at: str | None = None
    message: str = ""
    settings: BackupSettings | None = None


class BackupGitHubValidation(ApiResult):
    exists: bool = False
    write_access: bool = False
    repo: str | None = None
    branch: str | None = None
    branches: list[str] = Field(default_factory=list)
    message: str = ""


class FolderCreate(BaseModel):
    folder: str


class FolderDeleteResult(ApiResult):
    folder: str
    deleted_path: str
    removed_file_count: int = 0
    reload: dict[str, Any] | None = None


class FolderExport(BaseModel):
    folder: str | None = None
    destination_folder: str | None = None


class FolderExportResult(ApiResult):
    folder: str
    filename: str
    content: str
    shortcut_count: int
    saved_path: str | None = None


class PackageItem(BaseModel):
    name: str
    path: str
    file_count: int
    shortcut_count: int
    yaml_valid: bool
    version: str | None = None
    description: str | None = None
    source: str | None = None


class PackageInstall(BaseModel):
    name: str | None = None
    git: str | None = None
    version: str | None = None
    branch: str | None = None
    external: bool = False
    force: bool = False
    refresh_index: bool = False
    use_native_git: bool = False


class PackageActionResult(ApiResult):
    reload: dict[str, Any] | None = None
    command: list[str] = Field(default_factory=list)
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    package: PackageItem | None = None


class MutationResult(ApiResult):
    reload: dict[str, Any] | None = None
    shortcut: Shortcut | None = None


class ValidationResult(ApiResult):
    yaml_valid: bool
    duplicate_triggers: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)


class BackupItem(BaseModel):
    id: str
    timestamp: str
    original_path: str
    backup_path: str
    operation: str
