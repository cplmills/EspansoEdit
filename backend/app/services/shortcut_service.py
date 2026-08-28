from __future__ import annotations

import copy
import os
import tempfile
from pathlib import Path
from typing import Any, Callable

from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.scalarstring import LiteralScalarString

from app.models.schemas import (
    MacOSTextReplacementImport,
    MacOSTextReplacementImportResult,
    MacOSTextReplacementPreview,
    MacOSTextReplacementSkip,
    FolderExport,
    FolderExportResult,
    Shortcut,
    ShortcutCreate,
    ShortcutMove,
    ShortcutRawCreate,
    ShortcutRawUpdate,
    ShortcutUpdate,
    ValidationResult,
)
from app.services.backup_service import BackupService
from app.services.espanso_discovery import EspansoDiscoveryService, EspansoPaths
from app.services.macos_text_replacement_importer import MacOSTextReplacementImportService
from app.services.reloader import EspansoReloadService, ReloadResult
from app.services.yaml_service import YamlMatchService, case_insensitive_regex_for_trigger, normalize_newlines
from app.utils.errors import AppError

MANAGED_FILE = "espanso-shortcut-manager.yml"


class ShortcutService:
    def __init__(
        self,
        discovery: EspansoDiscoveryService | None = None,
        reloader: EspansoReloadService | None = None,
        macos_importer: MacOSTextReplacementImportService | None = None,
    ) -> None:
        self.discovery = discovery or EspansoDiscoveryService()
        self.reloader = reloader or EspansoReloadService(self.discovery)
        self.macos_importer = macos_importer or MacOSTextReplacementImportService()
        self.yaml = YamlMatchService()

    def status(self) -> dict[str, Any]:
        paths = self.discovery.discover()
        validation = self.validate()
        return {
            "installed": paths.installed,
            "version": paths.version,
            "running": paths.running,
            "config_path": str(paths.config_path) if paths.config_path else None,
            "match_path": str(paths.match_path) if paths.match_path else None,
            "config_dir": str(paths.config_dir) if paths.config_dir else None,
            "executable": paths.executable,
            "yaml_valid": validation.yaml_valid,
            "duplicate_triggers": validation.duplicate_triggers,
            "last_reload": self.reloader.last_successful_reload,
        }

    def list_shortcuts(self) -> list[Shortcut]:
        paths = self._paths_or_error()
        return [shortcut for path in self.match_files() for shortcut in self.yaml.parse_shortcuts(path, paths.match_path)]

    def get_shortcut(self, shortcut_id: str) -> Shortcut:
        for shortcut in self.list_shortcuts():
            if shortcut.id == shortcut_id:
                return shortcut
        raise AppError("SHORTCUT_NOT_FOUND", "Shortcut was not found.", status_code=404)

    def add_shortcut(self, payload: ShortcutCreate) -> tuple[Shortcut, ReloadResult]:
        self._validate_payload(payload.trigger, payload.replace, payload.form)
        managed = self._managed_file_for_folder(payload.folder)
        if not managed.exists():
            managed.parent.mkdir(parents=True, exist_ok=True)
            initial = CommentedMap({"matches": CommentedSeq()})
            return self._mutate_file(
                managed,
                "add",
                lambda data: self._append_shortcut(data, payload, managed),
                create_initial=initial,
            )
        return self._mutate_file(
            managed,
            "add",
            lambda data: self._append_shortcut(data, payload, managed),
        )

    def add_shortcut_raw(self, payload: ShortcutRawCreate) -> tuple[Shortcut, ReloadResult]:
        entry = self._raw_match_entry_from_yaml(payload.yaml)
        managed = self._managed_file_for_folder(payload.folder)
        if not managed.exists():
            managed.parent.mkdir(parents=True, exist_ok=True)
            initial = CommentedMap({"matches": CommentedSeq()})
            return self._mutate_file(
                managed,
                "raw-add",
                lambda data: self._append_raw_shortcut(data, entry, managed),
                create_initial=initial,
            )
        return self._mutate_file(
            managed,
            "raw-add",
            lambda data: self._append_raw_shortcut(data, entry, managed),
        )

    def update_shortcut(self, shortcut_id: str, payload: ShortcutUpdate) -> tuple[Shortcut, ReloadResult]:
        self._validate_payload(payload.trigger, payload.replace, payload.form)
        shortcut = self.get_shortcut(shortcut_id)
        if not shortcut.editable:
            raise AppError("SHORTCUT_UNSUPPORTED", "Unsupported shortcuts are read-only.", status_code=422)
        path = self._allowed_file(Path(shortcut.path))
        return self._mutate_file(
            path,
            "edit",
            lambda data: self._edit_shortcut(data, shortcut_id, path, payload),
            old_id=shortcut_id,
        )

    def update_shortcut_raw(self, shortcut_id: str, payload: ShortcutRawUpdate) -> tuple[Shortcut, ReloadResult]:
        shortcut = self.get_shortcut(shortcut_id)
        path = self._allowed_file(Path(shortcut.path))
        replacement = self._raw_match_entry_from_yaml(payload.yaml)
        return self._mutate_file(
            path,
            "raw-edit",
            lambda data: self._replace_shortcut_entry(data, shortcut_id, path, replacement),
            old_id=shortcut_id,
        )

    def move_shortcut(self, shortcut_id: str, payload: ShortcutMove) -> tuple[Shortcut, ReloadResult]:
        shortcut = self.get_shortcut(shortcut_id)
        source_path = self._allowed_file(Path(shortcut.path))
        target_path = self._managed_file_for_folder(payload.folder)
        if source_path == target_path:
            return shortcut, self.reloader.reload()

        source_text = source_path.read_text(encoding="utf-8")
        source_data = self.yaml.loads(source_text)
        target_text = target_path.read_text(encoding="utf-8") if target_path.exists() else self.yaml.dumps({"matches": []})
        target_data = self.yaml.loads(target_text)

        entry = self._pop_entry(source_data, shortcut_id, source_path)
        target_matches = target_data.setdefault("matches", CommentedSeq()) if isinstance(target_data, dict) else None
        if not isinstance(target_matches, list):
            raise AppError("INVALID_MATCH_FILE", "Target matches must be a list.", status_code=422)
        target_matches.append(copy.deepcopy(entry))

        self._validate_proposed(source_data)
        self._validate_proposed(target_data)
        self._reject_duplicate_across_proposals({source_path: source_data, target_path: target_data})

        changes = {
            source_path: (self.yaml.dumps(source_data), source_text),
            target_path: (self.yaml.dumps(target_data), target_text),
        }
        reload_result = self._replace_files_with_content(changes, "move")
        moved = self._resolve_moved_shortcut(target_path, entry)
        return moved, reload_result

    def delete_shortcut(self, shortcut_id: str) -> tuple[Shortcut, ReloadResult]:
        shortcut = self.get_shortcut(shortcut_id)
        if not shortcut.editable:
            raise AppError("SHORTCUT_UNSUPPORTED", "Unsupported shortcuts are read-only.", status_code=422)
        path = self._allowed_file(Path(shortcut.path))
        deleted = shortcut
        _, reload_result = self._mutate_file(
            path,
            "delete",
            lambda data: self._delete_shortcut(data, shortcut_id, path),
            old_id=shortcut_id,
        )
        return deleted, reload_result

    def validate(self) -> ValidationResult:
        errors: list[dict[str, Any]] = []
        for path in self.match_files():
            try:
                data = self.yaml.load_file(path)
                for error in self.yaml.validate_match_file(data, require_matches=False):
                    error["file"] = str(path)
                    errors.append(error)
            except AppError as exc:
                errors.append({"code": exc.code, "message": exc.message, "details": exc.details, "file": str(path)})
        duplicates = self.find_duplicate_triggers()
        return ValidationResult(
            yaml_valid=not errors,
            duplicate_triggers=duplicates,
            errors=errors,
            success=not errors and not duplicates,
        )

    def list_backups(self) -> list[Any]:
        return self._backup_service().list_backups()

    def list_folders(self) -> list[str]:
        paths = self._paths_or_error()
        folders = {"Root"}
        if paths.match_path.exists():
            for directory in paths.match_path.rglob("*"):
                if not directory.is_dir():
                    continue
                try:
                    relative = directory.resolve().relative_to(paths.match_path.resolve())
                except ValueError:
                    continue
                if not relative.parts or relative.parts[0] == "packages" or any(part.startswith(".") for part in relative.parts):
                    continue
                folders.add(relative.as_posix())
        return sorted(folders, key=lambda value: (value != "Root", value.lower()))

    def create_folder(self, folder: str) -> str:
        paths = self._paths_or_error()
        relative = self._normalize_folder(folder)
        if relative == "":
            return "Root"
        target = (paths.match_path / relative).resolve()
        root = paths.match_path.resolve()
        if not (target == root or root in target.parents):
            raise AppError("PATH_NOT_ALLOWED", "Invalid target folder.", status_code=403)
        target.mkdir(parents=True, exist_ok=True)
        return relative

    def export_folder(self, payload: FolderExport) -> FolderExportResult:
        folder = self._folder_label(payload.folder)
        folder_path = self._folder_path(payload.folder)
        matches = CommentedSeq()
        if folder_path.exists():
            for path in self._folder_match_files(folder_path):
                data = self.yaml.load_file(path)
                file_matches = data.get("matches") if isinstance(data, dict) else None
                if not isinstance(file_matches, list):
                    continue
                for entry in file_matches:
                    matches.append(copy.deepcopy(entry))
        if not matches:
            raise AppError("FOLDER_EMPTY", "No Espanso shortcuts were found in that folder.", status_code=404)

        export_data = CommentedMap({"matches": matches})
        filename = f"{self._export_filename(folder)}.yml"
        content = self.yaml.dumps(export_data)
        saved_path = self._save_export(payload.destination_folder, filename, content) if payload.destination_folder else None
        return FolderExportResult(
            folder=folder,
            filename=filename,
            content=content,
            shortcut_count=len(matches),
            saved_path=str(saved_path) if saved_path else None,
        )

    def _save_export(self, destination_folder: str, filename: str, content: str) -> Path:
        destination = Path(destination_folder).expanduser().resolve()
        if not destination.exists() or not destination.is_dir():
            raise AppError("EXPORT_DESTINATION_INVALID", "Choose an existing folder for the export.", status_code=422)
        target = (destination / filename).resolve()
        if target.parent != destination:
            raise AppError("EXPORT_DESTINATION_INVALID", "Invalid export destination.", status_code=422)
        try:
            target.write_text(normalize_newlines(content), encoding="utf-8")
        except OSError as exc:
            raise AppError("EXPORT_SAVE_FAILED", "The export could not be saved to that folder.", str(exc), 500) from exc
        return target

    def preview_macos_text_replacements(self) -> MacOSTextReplacementPreview:
        return self.macos_importer.preview()

    def import_macos_text_replacements(self, payload: MacOSTextReplacementImport) -> MacOSTextReplacementImportResult:
        preview = self.preview_macos_text_replacements()
        skipped: list[MacOSTextReplacementSkip] = []
        entries: list[CommentedMap] = []
        seen = {shortcut.trigger for shortcut in self.list_shortcuts() if shortcut.trigger}
        incoming_seen: set[str] = set()
        selected_counts = self._selected_replacement_counts(payload)

        for item in preview.items:
            if selected_counts is not None:
                selection_key = self._replacement_selection_key(item.trigger, item.replacement)
                selected_count = selected_counts.get(selection_key, 0)
                if selected_count <= 0:
                    skipped.append(MacOSTextReplacementSkip(trigger=item.trigger, replacement=item.replacement, reason="ignored"))
                    continue
                selected_counts[selection_key] = selected_count - 1

            trigger = item.trigger.strip()
            replacement = item.replacement
            if not item.enabled:
                skipped.append(MacOSTextReplacementSkip(trigger=item.trigger, replacement=item.replacement, reason="disabled"))
                continue
            if not trigger or replacement == "":
                skipped.append(MacOSTextReplacementSkip(trigger=item.trigger, replacement=item.replacement, reason="empty"))
                continue
            if trigger in seen:
                skipped.append(MacOSTextReplacementSkip(trigger=trigger, replacement=replacement, reason="duplicate_existing"))
                continue
            if trigger in incoming_seen:
                skipped.append(MacOSTextReplacementSkip(trigger=trigger, replacement=replacement, reason="duplicate_import"))
                continue

            incoming_seen.add(trigger)
            entries.append(CommentedMap({"trigger": trigger, "replace": replacement}))

        if not entries:
            return MacOSTextReplacementImportResult(
                source_path=preview.source_path,
                total_found=len(preview.items),
                imported_count=0,
                skipped_count=len(skipped),
                skipped=skipped,
                reload=None,
            )

        target = self._managed_file_for_folder(payload.folder)
        original_text = target.read_text(encoding="utf-8") if target.exists() else self.yaml.dumps({"matches": []})
        data = self.yaml.loads(original_text)
        if not isinstance(data, dict):
            raise AppError("INVALID_MATCH_FILE", "Match file root must be a mapping.", status_code=422)
        matches = data.setdefault("matches", CommentedSeq())
        if not isinstance(matches, list):
            raise AppError("INVALID_MATCH_FILE", "matches must be a list.", status_code=422)
        for entry in entries:
            matches.append(entry)

        self._validate_proposed(data)
        self._reject_duplicate_proposed(target, data, None)
        reload_result = self._replace_file_with_content(target, self.yaml.dumps(data), "import-macos", original_text=original_text)
        imported = self._resolve_imported_shortcuts(target, entries)
        return MacOSTextReplacementImportResult(
            source_path=preview.source_path,
            total_found=len(preview.items),
            imported_count=len(imported),
            skipped_count=len(skipped),
            imported=imported,
            skipped=skipped,
            reload=reload_result.to_dict(),
        )

    def _selected_replacement_counts(self, payload: MacOSTextReplacementImport) -> dict[tuple[str, str], int] | None:
        if payload.replacements is None:
            return None
        counts: dict[tuple[str, str], int] = {}
        for item in payload.replacements:
            key = self._replacement_selection_key(item.trigger, item.replacement)
            counts[key] = counts.get(key, 0) + 1
        return counts

    def _replacement_selection_key(self, trigger: str, replacement: str) -> tuple[str, str]:
        return (trigger, replacement)

    def restore_backup(self, backup_id: str) -> ReloadResult:
        backup = self._backup_service().get_backup(backup_id)
        original = self._allowed_file(Path(backup.original_path))
        backup_path = Path(backup.backup_path)
        if not backup_path.exists():
            raise AppError("BACKUP_FILE_MISSING", "Backup file is missing.", status_code=404)
        return self._replace_file_with_content(original, backup_path.read_text(encoding="utf-8"), "restore")

    def match_files(self) -> list[Path]:
        paths = self._paths_or_error()
        if not paths.match_path or not paths.match_path.exists():
            return []
        return sorted(
            path
            for path in paths.match_path.rglob("*")
            if path.is_file() and path.suffix.lower() in {".yml", ".yaml"} and not self._is_backup_path(path)
        )

    def config_yaml_files(self) -> list[Path]:
        paths = self._paths_or_error()
        if not paths.config_dir or not paths.config_dir.exists():
            return []
        return sorted(path for path in paths.config_dir.glob("*.yml")) + sorted(path for path in paths.config_dir.glob("*.yaml"))

    def find_duplicate_triggers(self, exclude: tuple[str, str] | None = None) -> list[dict[str, Any]]:
        seen: dict[str, list[dict[str, Any]]] = {}
        for path in self.match_files():
            try:
                shortcuts = self.yaml.parse_shortcuts(path)
            except AppError:
                continue
            for shortcut in shortcuts:
                if not shortcut.supported or not shortcut.trigger:
                    continue
                if exclude and shortcut.id == exclude[0] and shortcut.path == exclude[1]:
                    continue
                seen.setdefault(shortcut.trigger, []).append(
                    {"id": shortcut.id, "file": shortcut.file, "path": shortcut.path, "replace": shortcut.replace}
                )
        return [{"trigger": trigger, "entries": entries, "files": sorted({item["file"] for item in entries})} for trigger, entries in seen.items() if len(entries) > 1]

    def _append_shortcut(self, data: Any, payload: ShortcutCreate, path: Path) -> Shortcut:
        if not isinstance(data, dict):
            raise AppError("INVALID_MATCH_FILE", "Match file root must be a mapping.", status_code=422)
        matches = data.setdefault("matches", CommentedSeq())
        if not isinstance(matches, list):
            raise AppError("INVALID_MATCH_FILE", "matches must be a list.", status_code=422)
        entry = self._payload_entry(payload)
        matches.append(entry)
        return Shortcut(
            id="pending",
            trigger=payload.trigger,
            replace=payload.replace,
            form=payload.form,
            form_fields=self._parse_form_fields(payload.form_fields_yaml),
            form_fields_yaml=payload.form_fields_yaml,
            label=payload.label,
            word=payload.word,
            propagate_case=payload.propagate_case,
            case_insensitive=payload.case_insensitive,
            uppercase_style=payload.uppercase_style,
            force_mode=payload.force_mode,
            folder=self._folder_label_for_path(path),
            file=MANAGED_FILE,
            path=str(path),
            editable=True,
            supported=True,
            kind="form" if payload.form else "basic",
            preview=payload.replace or payload.form,
        )

    def _append_raw_shortcut(self, data: Any, entry: Any, path: Path) -> Shortcut:
        if not isinstance(data, dict):
            raise AppError("INVALID_MATCH_FILE", "Match file root must be a mapping.", status_code=422)
        matches = data.setdefault("matches", CommentedSeq())
        if not isinstance(matches, list):
            raise AppError("INVALID_MATCH_FILE", "matches must be a list.", status_code=422)
        matches.append(entry)
        return Shortcut(
            id=self.yaml.shortcut_id(path, entry),
            trigger=self.yaml.trigger_for_entry(entry),
            replace=entry.get("replace") if isinstance(entry.get("replace"), str) else None,
            form=entry.get("form") if isinstance(entry.get("form"), str) else None,
            case_insensitive=self.yaml.is_case_insensitive_entry(entry),
            folder=self._folder_label_for_path(path),
            file=path.name,
            path=str(path),
            editable=self.yaml.is_supported(entry),
            supported=self.yaml.is_supported(entry),
            kind="form" if self.yaml.is_supported(entry) and isinstance(entry.get("form"), str) else "basic" if self.yaml.is_supported(entry) else "advanced",
            preview=entry.get("replace") if isinstance(entry.get("replace"), str) else entry.get("form") if isinstance(entry.get("form"), str) else None,
            raw_yaml=self.yaml.dumps(entry),
        )

    def _edit_shortcut(self, data: Any, shortcut_id: str, path: Path, payload: ShortcutUpdate) -> Shortcut:
        entry = self._entry_for_id(data, shortcut_id, path)
        updated = self._payload_entry(payload)
        entry.clear()
        entry.update(updated)
        return Shortcut(
            id=self.yaml.shortcut_id(path, entry),
            trigger=payload.trigger,
            replace=payload.replace,
            form=payload.form,
            form_fields=self._parse_form_fields(payload.form_fields_yaml),
            form_fields_yaml=payload.form_fields_yaml,
            label=payload.label,
            word=payload.word,
            propagate_case=payload.propagate_case,
            case_insensitive=payload.case_insensitive,
            uppercase_style=payload.uppercase_style,
            force_mode=payload.force_mode,
            folder=self._folder_label_for_path(path),
            file=path.name,
            path=str(path),
            editable=True,
            supported=True,
            kind="form" if payload.form else "basic",
            preview=payload.replace or payload.form,
        )

    def _replace_shortcut_entry(self, data: Any, shortcut_id: str, path: Path, replacement: Any) -> Shortcut:
        matches = data.get("matches") if isinstance(data, dict) else None
        if not isinstance(matches, list):
            raise AppError("SHORTCUT_NOT_FOUND", "Shortcut was not found.", status_code=404)
        for index, entry in enumerate(matches):
            if self.yaml.shortcut_id(path, entry) == shortcut_id:
                matches[index] = replacement
                return Shortcut(
                    id=self.yaml.shortcut_id(path, replacement),
                    trigger=self.yaml.trigger_for_entry(replacement),
                    replace=replacement.get("replace") if isinstance(replacement.get("replace"), str) else None,
                    form=replacement.get("form") if isinstance(replacement.get("form"), str) else None,
                    form_fields=replacement.get("form_fields") if isinstance(replacement.get("form_fields"), dict) else None,
                    form_fields_yaml=self.yaml.dumps(replacement.get("form_fields")) if isinstance(replacement.get("form_fields"), dict) else None,
                    label=replacement.get("label") if isinstance(replacement.get("label"), str) else None,
                    word=replacement.get("word") if isinstance(replacement.get("word"), bool) else None,
                    propagate_case=replacement.get("propagate_case") if isinstance(replacement.get("propagate_case"), bool) else None,
                    case_insensitive=self.yaml.is_case_insensitive_entry(replacement),
                    uppercase_style=replacement.get("uppercase_style") if isinstance(replacement.get("uppercase_style"), str) else None,
                    force_mode=replacement.get("force_mode") if isinstance(replacement.get("force_mode"), str) else None,
                    folder=self._folder_label_for_path(path),
                    file=path.name,
                    path=str(path),
                    editable=self.yaml.is_supported(replacement),
                    supported=self.yaml.is_supported(replacement),
                    kind="form" if self.yaml.is_supported(replacement) and isinstance(replacement.get("form"), str) else "basic" if self.yaml.is_supported(replacement) else "advanced",
                    preview=replacement.get("replace") if isinstance(replacement.get("replace"), str) else replacement.get("form") if isinstance(replacement.get("form"), str) else None,
                    raw_yaml=self.yaml.dumps(replacement),
                )
        raise AppError("SHORTCUT_NOT_FOUND", "Shortcut was not found.", status_code=404)

    def _payload_entry(self, payload: ShortcutCreate | ShortcutUpdate) -> CommentedMap:
        if payload.case_insensitive:
            entry = CommentedMap({"regex": case_insensitive_regex_for_trigger(payload.trigger)})
        else:
            entry = CommentedMap({"trigger": payload.trigger})
        if payload.form:
            entry["form"] = self._yaml_text(payload.form)
            form_fields = self._parse_form_fields(payload.form_fields_yaml)
            if form_fields:
                entry["form_fields"] = form_fields
        else:
            entry["replace"] = self._yaml_text(payload.replace)
        if payload.label:
            entry["label"] = payload.label
        if payload.word:
            entry["word"] = payload.word
        if payload.propagate_case:
            entry["propagate_case"] = payload.propagate_case
        if payload.uppercase_style:
            entry["uppercase_style"] = payload.uppercase_style
        if payload.force_mode:
            entry["force_mode"] = payload.force_mode
        return entry

    def _parse_form_fields(self, text: str | None) -> Any:
        if not text or not text.strip():
            return None
        data = self.yaml.loads(normalize_newlines(text))
        if not isinstance(data, dict):
            raise AppError("INVALID_FORM_FIELDS", "Form fields YAML must be a mapping.", status_code=422)
        return data

    def _yaml_text(self, text: str) -> str | LiteralScalarString:
        normalized = normalize_newlines(text)
        if "\n" in normalized:
            return LiteralScalarString(normalized)
        return normalized

    def _delete_shortcut(self, data: Any, shortcut_id: str, path: Path) -> Shortcut:
        matches = data.get("matches") if isinstance(data, dict) else None
        if not isinstance(matches, list):
            raise AppError("SHORTCUT_NOT_FOUND", "Shortcut was not found.", status_code=404)
        for index, entry in enumerate(matches):
            if self.yaml.shortcut_id(path, entry) == shortcut_id:
                del matches[index]
                return Shortcut(id=shortcut_id, folder=self._folder_label_for_path(path), file=path.name, path=str(path), editable=True, supported=True)
        raise AppError("SHORTCUT_NOT_FOUND", "Shortcut was not found.", status_code=404)

    def _pop_entry(self, data: Any, shortcut_id: str, path: Path) -> Any:
        matches = data.get("matches") if isinstance(data, dict) else None
        if not isinstance(matches, list):
            raise AppError("SHORTCUT_NOT_FOUND", "Shortcut was not found.", status_code=404)
        for index, entry in enumerate(matches):
            if self.yaml.shortcut_id(path, entry) == shortcut_id:
                del matches[index]
                return entry
        raise AppError("SHORTCUT_NOT_FOUND", "Shortcut was not found.", status_code=404)

    def _entry_for_id(self, data: Any, shortcut_id: str, path: Path) -> Any:
        matches = data.get("matches") if isinstance(data, dict) else None
        if not isinstance(matches, list):
            raise AppError("SHORTCUT_NOT_FOUND", "Shortcut was not found.", status_code=404)
        for entry in matches:
            if self.yaml.shortcut_id(path, entry) == shortcut_id:
                if not self.yaml.is_supported(entry):
                    raise AppError("SHORTCUT_UNSUPPORTED", "Unsupported shortcuts are read-only.", status_code=422)
                return entry
        raise AppError("SHORTCUT_NOT_FOUND", "Shortcut was not found.", status_code=404)

    def _mutate_file(
        self,
        path: Path,
        operation: str,
        mutator: Callable[[Any], Shortcut],
        create_initial: Any | None = None,
        old_id: str | None = None,
    ) -> tuple[Shortcut, ReloadResult]:
        path = self._allowed_file(path)
        original_text = path.read_text(encoding="utf-8") if path.exists() else self.yaml.dumps(create_initial or {"matches": []})
        data = self.yaml.loads(original_text)
        shortcut = mutator(data)
        self._validate_proposed(data)
        proposed_text = self.yaml.dumps(data)
        self._reject_duplicate_proposed(path, data, old_id)
        reload_result = self._replace_file_with_content(path, proposed_text, operation, original_text=original_text)
        updated = self._resolve_mutated_shortcut(path, shortcut, old_id, operation)
        return updated, reload_result

    def _replace_file_with_content(
        self,
        path: Path,
        proposed_text: str,
        operation: str,
        original_text: str | None = None,
    ) -> ReloadResult:
        path = self._allowed_file(path)
        original_text = path.read_text(encoding="utf-8") if original_text is None and path.exists() else (original_text or "")
        self.yaml.loads(proposed_text)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(proposed_text)
            self.yaml.load_file(tmp_path)
            self._backup_service().backup_file(path, operation)
            os.replace(tmp_path, path)
            reload_result = self.reloader.reload()
            if reload_result.success:
                return reload_result
            rollback = original_text if original_text else "matches:\n"
            path.write_text(rollback, encoding="utf-8")
            rollback_reload = self.reloader.reload()
            raise AppError(
                "ESPANSO_RELOAD_FAILED",
                "Espanso reload failed. The file was rolled back.",
                {"reload": reload_result.to_dict(), "rollback_reload": rollback_reload.to_dict()},
                500,
            )
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

    def _replace_files_with_content(self, changes: dict[Path, tuple[str, str]], operation: str) -> ReloadResult:
        temp_paths: list[Path] = []
        try:
            for path, (proposed_text, _) in changes.items():
                path = self._allowed_file(path)
                self.yaml.loads(proposed_text)
                path.parent.mkdir(parents=True, exist_ok=True)
                fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
                tmp_path = Path(tmp_name)
                temp_paths.append(tmp_path)
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(proposed_text)
                self.yaml.load_file(tmp_path)

            for path in changes:
                self._backup_service().backup_file(path, operation)

            for path, (proposed_text, _) in changes.items():
                tmp_path = temp_paths.pop(0)
                os.replace(tmp_path, path)

            reload_result = self.reloader.reload()
            if reload_result.success:
                return reload_result

            for path, (_, original_text) in changes.items():
                path.write_text(original_text, encoding="utf-8")
            rollback_reload = self.reloader.reload()
            raise AppError(
                "ESPANSO_RELOAD_FAILED",
                "Espanso reload failed. The files were rolled back.",
                {"reload": reload_result.to_dict(), "rollback_reload": rollback_reload.to_dict()},
                500,
            )
        finally:
            for tmp_path in temp_paths:
                if tmp_path.exists():
                    tmp_path.unlink()

    def _validate_proposed(self, data: Any) -> None:
        errors = self.yaml.validate_match_file(data)
        if errors:
            raise AppError("MATCH_VALIDATION_FAILED", "The proposed match file is invalid.", errors, 422)

    def _reject_duplicate_proposed(self, target_path: Path, proposed_data: Any, old_id: str | None) -> None:
        by_trigger: dict[str, list[dict[str, Any]]] = {}
        excluded = (old_id, str(target_path)) if old_id else None

        for path in self.match_files():
            if path.resolve() == target_path.resolve():
                continue
            for shortcut in self.yaml.parse_shortcuts(path):
                if not shortcut.supported or not shortcut.trigger:
                    continue
                if excluded and shortcut.id == excluded[0] and shortcut.path == excluded[1]:
                    continue
                by_trigger.setdefault(shortcut.trigger, []).append(
                    {"id": shortcut.id, "file": shortcut.file, "path": shortcut.path, "replace": shortcut.replace}
                )

        matches = proposed_data.get("matches") if isinstance(proposed_data, dict) else None
        if isinstance(matches, list):
            for entry in matches:
                if not self.yaml.is_supported(entry):
                    continue
                entry_id = self.yaml.shortcut_id(target_path, entry)
                if excluded and entry_id == excluded[0]:
                    continue
                trigger = self.yaml.trigger_for_entry(entry)
                by_trigger.setdefault(trigger, []).append(
                    {
                        "id": entry_id,
                        "file": target_path.name,
                        "path": str(target_path),
                        "replace": entry.get("replace"),
                    }
                )

        duplicates = [
            {"trigger": trigger, "entries": entries, "files": sorted({item["file"] for item in entries})}
            for trigger, entries in by_trigger.items()
            if len(entries) > 1
        ]
        if duplicates:
            raise AppError("DUPLICATE_TRIGGER", "Duplicate triggers are not allowed.", duplicates, 409)

    def _reject_duplicate_across_proposals(self, proposed: dict[Path, Any]) -> None:
        by_trigger: dict[str, list[dict[str, Any]]] = {}
        proposed_paths = {path.resolve() for path in proposed}

        for path in self.match_files():
            if path.resolve() in proposed_paths:
                continue
            for shortcut in self.yaml.parse_shortcuts(path):
                if shortcut.supported and shortcut.trigger:
                    by_trigger.setdefault(shortcut.trigger, []).append(
                        {"id": shortcut.id, "file": shortcut.file, "path": shortcut.path, "replace": shortcut.replace}
                    )

        for path, data in proposed.items():
            matches = data.get("matches") if isinstance(data, dict) else None
            if not isinstance(matches, list):
                continue
            for entry in matches:
                if not self.yaml.is_supported(entry):
                    continue
                trigger = self.yaml.trigger_for_entry(entry)
                by_trigger.setdefault(trigger, []).append(
                    {
                        "id": self.yaml.shortcut_id(path, entry),
                        "file": path.name,
                        "path": str(path),
                        "replace": entry.get("replace"),
                    }
                )

        duplicates = [
            {"trigger": trigger, "entries": entries, "files": sorted({item["file"] for item in entries})}
            for trigger, entries in by_trigger.items()
            if len(entries) > 1
        ]
        if duplicates:
            raise AppError("DUPLICATE_TRIGGER", "Duplicate triggers are not allowed.", duplicates, 409)

    def _resolve_mutated_shortcut(self, path: Path, shortcut: Shortcut, old_id: str | None, operation: str) -> Shortcut:
        if operation in {"delete", "raw-edit"}:
            return shortcut
        paths = self._paths_or_error()
        candidates = self.yaml.parse_shortcuts(path, paths.match_path)
        if old_id:
            for item in candidates:
                if item.trigger == shortcut.trigger and item.replace == shortcut.replace and item.form == shortcut.form:
                    return item
        return candidates[-1]

    def _resolve_moved_shortcut(self, path: Path, moved_entry: Any) -> Shortcut:
        paths = self._paths_or_error()
        moved_id = self.yaml.shortcut_id(path, moved_entry)
        for shortcut in self.yaml.parse_shortcuts(path, paths.match_path):
            if shortcut.id == moved_id:
                return shortcut
        raise AppError("SHORTCUT_NOT_FOUND", "Moved shortcut was not found.", status_code=500)

    def _resolve_imported_shortcuts(self, path: Path, entries: list[CommentedMap]) -> list[Shortcut]:
        paths = self._paths_or_error()
        imported_ids = {self.yaml.shortcut_id(path, entry) for entry in entries}
        return [shortcut for shortcut in self.yaml.parse_shortcuts(path, paths.match_path) if shortcut.id in imported_ids]

    def _validate_payload(self, trigger: str, replace: str, form: str | None = None) -> None:
        if not trigger.strip():
            raise AppError("INVALID_TRIGGER", "Trigger cannot be empty.", status_code=422)
        if form is not None:
            if not form.strip():
                raise AppError("INVALID_FORM", "Form template cannot be empty.", status_code=422)
            return
        if replace == "":
            raise AppError("INVALID_REPLACE", "Replacement cannot be empty.", status_code=422)

    def _validate_raw_match_entry(self, entry: Any) -> None:
        if not isinstance(entry, dict):
            raise AppError("INVALID_MATCH_ENTRY", "Raw YAML must be a single match mapping or one-item match list.", status_code=422)
        if "matches" in entry:
            raise AppError("INVALID_MATCH_ENTRY", "Raw YAML must be one match entry, not a full match file.", status_code=422)
        trigger = entry.get("trigger")
        if not isinstance(trigger, str) or not trigger.strip():
            raise AppError("INVALID_MATCH_ENTRY", "Raw YAML match entries must include a trigger.", status_code=422)

    def _raw_match_entry_from_yaml(self, text: str) -> Any:
        entry = self.yaml.loads(text)
        if isinstance(entry, list):
            if len(entry) != 1:
                raise AppError("INVALID_MATCH_ENTRY", "Raw YAML must contain exactly one match entry.", status_code=422)
            entry = entry[0]
        self._validate_raw_match_entry(entry)
        return entry

    def _paths_or_error(self) -> EspansoPaths:
        paths = self.discovery.discover()
        if not paths.config_path or not paths.match_path:
            raise AppError("ESPANSO_CONFIG_NOT_FOUND", "Espanso configuration directory could not be detected.", status_code=404)
        return paths

    def _backup_service(self) -> BackupService:
        paths = self._paths_or_error()
        return BackupService(paths.config_path / "shortcut-manager-backups")

    def _managed_file_for_folder(self, folder: str | None) -> Path:
        paths = self._paths_or_error()
        relative = self._normalize_folder(folder)
        target_dir = paths.match_path if relative == "" else paths.match_path / relative
        return self._safe_child(target_dir, MANAGED_FILE)

    def _folder_path(self, folder: str | None) -> Path:
        paths = self._paths_or_error()
        relative = self._normalize_folder(folder)
        target = paths.match_path if relative == "" else paths.match_path / relative
        root = paths.match_path.resolve()
        resolved = target.resolve()
        if not (resolved == root or root in resolved.parents):
            raise AppError("PATH_NOT_ALLOWED", "Invalid folder path.", status_code=403)
        return resolved

    def _folder_match_files(self, folder_path: Path) -> list[Path]:
        if not folder_path.exists() or not folder_path.is_dir():
            return []
        return sorted(
            path
            for path in folder_path.iterdir()
            if path.is_file() and path.suffix.lower() in {".yml", ".yaml"} and not self._is_backup_path(path)
        )

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

    def _folder_label(self, folder: str | None) -> str:
        relative = self._normalize_folder(folder)
        return "Root" if relative == "" else relative

    def _export_filename(self, folder: str) -> str:
        slug = "root" if folder == "Root" else folder.lower().replace("/", "-")
        slug = "".join(character if character.isalnum() or character in {"-", "_"} else "-" for character in slug)
        slug = "-".join(part for part in slug.split("-") if part)
        return f"espanso-{slug or 'shortcuts'}"

    def _folder_label_for_path(self, path: Path) -> str:
        paths = self._paths_or_error()
        return self.yaml.folder_for_path(path, paths.match_path)

    def _allowed_file(self, path: Path) -> Path:
        paths = self._paths_or_error()
        resolved = path.resolve()
        roots = [paths.match_path.resolve(), paths.config_dir.resolve()]
        if not any(resolved == root or root in resolved.parents for root in roots):
            raise AppError("PATH_NOT_ALLOWED", "Writes are only allowed inside Espanso directories.", status_code=403)
        return resolved

    def _safe_child(self, parent: Path, name: str) -> Path:
        candidate = (parent / name).resolve()
        parent_resolved = parent.resolve()
        if parent_resolved not in candidate.parents:
            raise AppError("PATH_NOT_ALLOWED", "Invalid target path.", status_code=403)
        return candidate

    def _is_backup_path(self, path: Path) -> bool:
        paths = self.discovery.discover()
        return bool(paths.config_path and (paths.config_path / "shortcut-manager-backups").resolve() in path.resolve().parents)
