from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from app.models.schemas import BackupItem
from app.utils.errors import AppError


class BackupService:
    def __init__(self, root: Path, frequency: Literal["always", "daily", "manual"] = "always") -> None:
        self.root = root
        self.frequency = frequency

    def backup_file(self, original_path: Path, operation: str) -> BackupItem | None:
        if self.frequency == "manual":
            return None
        if self.frequency == "daily" and self._has_backup_today(original_path):
            return None

        base_timestamp = datetime.now(ZoneInfo("Australia/Brisbane")).strftime("%Y-%m-%dT%H%M%S%f")
        timestamp = base_timestamp
        backup_dir = self.root / timestamp
        suffix = 1
        while backup_dir.exists():
            timestamp = f"{base_timestamp}-{suffix}"
            backup_dir = self.root / timestamp
            suffix += 1
        backup_dir.mkdir(parents=True, exist_ok=False)
        backup_path = backup_dir / original_path.name
        if original_path.exists():
            shutil.copy2(original_path, backup_path)
        else:
            backup_path.write_text("matches:\n", encoding="utf-8")

        item = BackupItem(
            id=timestamp,
            timestamp=timestamp,
            original_path=str(original_path),
            backup_path=str(backup_path),
            operation=operation,
        )
        (backup_dir / "metadata.json").write_text(item.model_dump_json(indent=2), encoding="utf-8")
        return item

    def clear_backups(self) -> int:
        if not self.root.exists():
            return 0
        removed = 0
        for child in self.root.iterdir():
            if not child.is_dir():
                continue
            metadata = child / "metadata.json"
            if not metadata.exists():
                continue
            shutil.rmtree(child)
            removed += 1
        return removed

    def list_backups(self) -> list[BackupItem]:
        if not self.root.exists():
            return []
        items: list[BackupItem] = []
        for metadata in sorted(self.root.glob("*/metadata.json"), reverse=True):
            try:
                items.append(BackupItem.model_validate_json(metadata.read_text(encoding="utf-8")))
            except Exception:
                continue
        return items

    def get_backup(self, backup_id: str) -> BackupItem:
        if "/" in backup_id or ".." in backup_id:
            raise AppError("INVALID_BACKUP_ID", "Invalid backup id.", status_code=400)
        metadata = self.root / backup_id / "metadata.json"
        if not metadata.exists():
            raise AppError("BACKUP_NOT_FOUND", "Backup was not found.", status_code=404)
        try:
            return BackupItem.model_validate_json(metadata.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise AppError("BACKUP_METADATA_INVALID", "Backup metadata is invalid.", str(exc), 422) from exc

    def _has_backup_today(self, original_path: Path) -> bool:
        today = datetime.now(ZoneInfo("Australia/Brisbane")).date().isoformat()
        for backup in self.list_backups():
            if Path(backup.original_path) == original_path and backup.timestamp.startswith(today):
                return True
        return False
