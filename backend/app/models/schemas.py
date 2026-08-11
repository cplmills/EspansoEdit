from __future__ import annotations

from typing import Any

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
    uppercase_style: str | None = None
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
    uppercase_style: str | None = None


class ShortcutUpdate(BaseModel):
    trigger: str
    replace: str = ""
    form: str | None = None
    form_fields_yaml: str | None = None
    label: str | None = None
    word: bool = False
    propagate_case: bool = False
    uppercase_style: str | None = None


class ShortcutRawUpdate(BaseModel):
    yaml: str


class ShortcutMove(BaseModel):
    folder: str | None = None


class FolderCreate(BaseModel):
    folder: str


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
