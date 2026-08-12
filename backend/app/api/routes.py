from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends

from app.models.schemas import BackupItem, EspansoStatus, FolderCreate, MutationResult, PackageActionResult, PackageInstall, PackageItem, Shortcut, ShortcutCreate, ShortcutMove, ShortcutRawUpdate, ShortcutUpdate, ValidationResult
from app.services.package_service import EspansoPackageService
from app.services.shortcut_service import ShortcutService
from app.utils.errors import AppError, http_error

router = APIRouter(prefix="/api")

_service = ShortcutService()
_package_service = EspansoPackageService(_service.discovery, _service.reloader)


def get_service() -> ShortcutService:
    return _service


def get_package_service() -> EspansoPackageService:
    return _package_service


@router.get("/status", response_model=EspansoStatus)
def status(service: ShortcutService = Depends(get_service)) -> dict:
    return service.status()


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
