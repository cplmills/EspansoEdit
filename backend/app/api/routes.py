from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends

from app.models.schemas import (
    BackupItem,
    AppSettings,
    EspansoStatus,
    FolderCreate,
    FolderDeleteResult,
    FolderExport,
    FolderExportResult,
    GitShortcutSyncDisable,
    GitShortcutSyncResult,
    GitShortcutSyncSource,
    GitShortcutSyncValidation,
    MacOSTextReplacementImport,
    MacOSTextReplacementImportResult,
    MacOSTextReplacementPreview,
    MutationResult,
    PackageActionResult,
    PackageInstall,
    PackageItem,
    SettingsUpdate,
    Shortcut,
    ShortcutCreate,
    ShortcutMove,
    ShortcutRawCreate,
    ShortcutRawUpdate,
    ShortcutUpdate,
    ValidationResult,
)
from app.services.package_service import EspansoPackageService
from app.services.settings_service import AppSettingsService
from app.services.shortcut_service import ShortcutService
from app.utils.errors import AppError, http_error

router = APIRouter(prefix="/api")

_service = ShortcutService()
_package_service = EspansoPackageService(_service.discovery, _service.reloader)
_settings_service = AppSettingsService(_service.discovery, _service.reloader)


def get_service() -> ShortcutService:
    return _service


def get_package_service() -> EspansoPackageService:
    return _package_service


def get_settings_service() -> AppSettingsService:
    return _settings_service


def sync_github_shortcuts_on_startup() -> None:
    _settings_service.sync_git_shortcuts_on_startup()


@router.get("/status", response_model=EspansoStatus)
def status(service: ShortcutService = Depends(get_service)) -> dict:
    return service.status()


@router.get("/settings", response_model=AppSettings)
def settings(service: AppSettingsService = Depends(get_settings_service)) -> AppSettings:
    try:
        return service.get_settings()
    except AppError as exc:
        raise http_error(exc) from exc


@router.put("/settings", response_model=AppSettings)
def update_settings(payload: SettingsUpdate, service: AppSettingsService = Depends(get_settings_service)) -> AppSettings:
    try:
        return service.update_settings(payload)
    except AppError as exc:
        raise http_error(exc) from exc


@router.post("/settings/git-sync/validate", response_model=GitShortcutSyncValidation)
def validate_git_sync(
    payload: GitShortcutSyncSource,
    service: AppSettingsService = Depends(get_settings_service),
) -> GitShortcutSyncValidation:
    try:
        return service.validate_git_sync(payload)
    except AppError as exc:
        raise http_error(exc) from exc


@router.post("/settings/git-sync/sync", response_model=GitShortcutSyncResult)
def sync_git_shortcuts(service: AppSettingsService = Depends(get_settings_service)) -> GitShortcutSyncResult:
    try:
        return service.sync_git_shortcuts()
    except AppError as exc:
        raise http_error(exc) from exc


@router.post("/settings/git-sync/sources/{source_id}/disable", response_model=GitShortcutSyncResult)
def disable_git_sync_source(
    source_id: str,
    payload: GitShortcutSyncDisable,
    service: AppSettingsService = Depends(get_settings_service),
) -> GitShortcutSyncResult:
    try:
        return service.disable_git_sync_source(source_id, payload.remove_shortcuts)
    except AppError as exc:
        raise http_error(exc) from exc


@router.get("/shortcuts", response_model=list[Shortcut])
def shortcuts(service: ShortcutService = Depends(get_service)) -> list[Shortcut]:
    try:
        return service.list_shortcuts()
    except AppError as exc:
        raise http_error(exc) from exc


@router.get("/folders", response_model=list[str])
def folders(service: ShortcutService = Depends(get_service)) -> list[str]:
    try:
        return service.list_folders()
    except AppError as exc:
        raise http_error(exc) from exc


@router.post("/folders")
def create_folder(payload: FolderCreate, service: ShortcutService = Depends(get_service)) -> dict[str, str]:
    try:
        return {"folder": service.create_folder(payload.folder)}
    except AppError as exc:
        raise http_error(exc) from exc


@router.delete("/folders/{folder_path:path}", response_model=FolderDeleteResult)
def delete_folder(
    folder_path: str,
    shortcut_service: ShortcutService = Depends(get_service),
    settings_service: AppSettingsService = Depends(get_settings_service),
) -> FolderDeleteResult:
    try:
        synced_sources = settings_service.enabled_sources_for_folder(folder_path)
        if synced_sources:
            raise AppError(
                "FOLDER_SYNC_ENABLED",
                "This folder is managed by GitHub sync. Disable the sync source before deleting the folder.",
                [{"id": source.id, "repo_url": source.repo_url, "folder": source.folder} for source in synced_sources],
                422,
            )
        return shortcut_service.delete_folder(folder_path)
    except AppError as exc:
        raise http_error(exc) from exc


@router.post("/folders/export", response_model=FolderExportResult)
def export_folder(payload: FolderExport, service: ShortcutService = Depends(get_service)) -> FolderExportResult:
    try:
        return service.export_folder(payload)
    except AppError as exc:
        raise http_error(exc) from exc


@router.get("/import/macos-text-replacements", response_model=MacOSTextReplacementPreview)
def preview_macos_text_replacements(service: ShortcutService = Depends(get_service)) -> MacOSTextReplacementPreview:
    try:
        return service.preview_macos_text_replacements()
    except AppError as exc:
        raise http_error(exc) from exc


@router.post("/import/macos-text-replacements", response_model=MacOSTextReplacementImportResult)
def import_macos_text_replacements(
    payload: MacOSTextReplacementImport,
    service: ShortcutService = Depends(get_service),
) -> MacOSTextReplacementImportResult:
    try:
        return service.import_macos_text_replacements(payload)
    except AppError as exc:
        raise http_error(exc) from exc


@router.get("/packages", response_model=list[PackageItem])
def packages(service: EspansoPackageService = Depends(get_package_service)) -> list[PackageItem]:
    try:
        return service.list_packages()
    except AppError as exc:
        raise http_error(exc) from exc


@router.post("/packages", response_model=PackageActionResult)
def install_package(payload: PackageInstall, service: EspansoPackageService = Depends(get_package_service)) -> PackageActionResult:
    try:
        return PackageActionResult(**service.install_package(payload))
    except AppError as exc:
        raise http_error(exc) from exc


@router.post("/packages/{package_name}/update", response_model=PackageActionResult)
def update_package(package_name: str, service: EspansoPackageService = Depends(get_package_service)) -> PackageActionResult:
    try:
        return PackageActionResult(**service.update_package(package_name))
    except AppError as exc:
        raise http_error(exc) from exc


@router.delete("/packages/{package_name}", response_model=PackageActionResult)
def uninstall_package(package_name: str, service: EspansoPackageService = Depends(get_package_service)) -> PackageActionResult:
    try:
        return PackageActionResult(**service.uninstall_package(package_name))
    except AppError as exc:
        raise http_error(exc) from exc


@router.get("/shortcuts/{shortcut_id}", response_model=Shortcut)
def shortcut(shortcut_id: str, service: ShortcutService = Depends(get_service)) -> Shortcut:
    try:
        return service.get_shortcut(shortcut_id)
    except AppError as exc:
        raise http_error(exc) from exc


@router.post("/shortcuts", response_model=MutationResult)
def create_shortcut(payload: ShortcutCreate, service: ShortcutService = Depends(get_service)) -> MutationResult:
    try:
        shortcut, reload_result = service.add_shortcut(payload)
        return MutationResult(shortcut=shortcut, reload=reload_result.to_dict())
    except AppError as exc:
        raise http_error(exc) from exc


@router.post("/shortcuts/raw", response_model=MutationResult)
def create_shortcut_raw(payload: ShortcutRawCreate, service: ShortcutService = Depends(get_service)) -> MutationResult:
    try:
        shortcut, reload_result = service.add_shortcut_raw(payload)
        return MutationResult(shortcut=shortcut, reload=reload_result.to_dict())
    except AppError as exc:
        raise http_error(exc) from exc


@router.put("/shortcuts/{shortcut_id}", response_model=MutationResult)
def update_shortcut(shortcut_id: str, payload: ShortcutUpdate, service: ShortcutService = Depends(get_service)) -> MutationResult:
    try:
        shortcut, reload_result = service.update_shortcut(shortcut_id, payload)
        return MutationResult(shortcut=shortcut, reload=reload_result.to_dict())
    except AppError as exc:
        raise http_error(exc) from exc


@router.put("/shortcuts/{shortcut_id}/raw", response_model=MutationResult)
def update_shortcut_raw(shortcut_id: str, payload: ShortcutRawUpdate, service: ShortcutService = Depends(get_service)) -> MutationResult:
    try:
        shortcut, reload_result = service.update_shortcut_raw(shortcut_id, payload)
        return MutationResult(shortcut=shortcut, reload=reload_result.to_dict())
    except AppError as exc:
        raise http_error(exc) from exc


@router.put("/shortcuts/{shortcut_id}/move", response_model=MutationResult)
def move_shortcut(shortcut_id: str, payload: ShortcutMove, service: ShortcutService = Depends(get_service)) -> MutationResult:
    try:
        shortcut, reload_result = service.move_shortcut(shortcut_id, payload)
        return MutationResult(shortcut=shortcut, reload=reload_result.to_dict())
    except AppError as exc:
        raise http_error(exc) from exc


@router.delete("/shortcuts/{shortcut_id}", response_model=MutationResult)
def delete_shortcut(shortcut_id: str, service: ShortcutService = Depends(get_service)) -> MutationResult:
    try:
        shortcut, reload_result = service.delete_shortcut(shortcut_id)
        return MutationResult(shortcut=shortcut, reload=reload_result.to_dict())
    except AppError as exc:
        raise http_error(exc) from exc


@router.post("/validate", response_model=ValidationResult)
def validate(service: ShortcutService = Depends(get_service)) -> ValidationResult:
    return service.validate()


@router.get("/backups", response_model=list[BackupItem])
def backups(service: ShortcutService = Depends(get_service)) -> list[BackupItem]:
    try:
        return service.list_backups()
    except AppError as exc:
        raise http_error(exc) from exc


@router.post("/backups/{backup_id}/restore", response_model=MutationResult)
def restore_backup(backup_id: str, service: ShortcutService = Depends(get_service)) -> MutationResult:
    try:
        reload_result = service.restore_backup(backup_id)
        return MutationResult(reload=reload_result.to_dict())
    except AppError as exc:
        raise http_error(exc) from exc


@router.get("/config")
def config(service: ShortcutService = Depends(get_service)) -> dict:
    try:
        status_payload = service.status()
        files = []
        for path in service.config_yaml_files():
            files.append({"path": str(path), "file": path.name, "content": Path(path).read_text(encoding="utf-8")})
        return {"status": status_payload, "files": files}
    except AppError as exc:
        raise http_error(exc) from exc
