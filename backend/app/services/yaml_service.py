from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from app.models.schemas import Shortcut
from app.utils.errors import AppError

SUPPORTED_KEYS = {"trigger", "replace", "form", "form_fields", "label", "word", "propagate_case", "uppercase_style", "force_mode"}


class YamlMatchService:
    def __init__(self) -> None:
        self.yaml = YAML()
        self.yaml.preserve_quotes = True
        self.yaml.indent(mapping=2, sequence=4, offset=2)

    def load_file(self, path: Path) -> Any:
        try:
            text = path.read_text(encoding="utf-8")
            return self.yaml.load(text) if text.strip() else CommentedMap({"matches": CommentedSeq()})
        except Exception as exc:
            raise AppError("YAML_PARSE_FAILED", f"Failed to parse {path.name}.", str(exc), 422) from exc

    def dump_file(self, path: Path, data: Any) -> None:
        with path.open("w", encoding="utf-8") as handle:
            self.yaml.dump(data, handle)

    def dumps(self, data: Any) -> str:
        import io

        stream = io.StringIO()
        self.yaml.dump(data, stream)
        return stream.getvalue()

    def loads(self, text: str) -> Any:
        try:
            return self.yaml.load(text)
        except Exception as exc:
            raise AppError("YAML_VALIDATION_FAILED", "The proposed YAML is invalid.", str(exc), 422) from exc

    def parse_shortcuts(self, path: Path, match_root: Path | None = None) -> list[Shortcut]:
        data = self.load_file(path)
        matches = data.get("matches") if isinstance(data, dict) else None
        if not isinstance(matches, list):
            return []

        shortcuts: list[Shortcut] = []
        for entry in matches:
            entry_id = self.shortcut_id(path, entry)
            supported = self.is_supported(entry)
            trigger = entry.get("trigger") if isinstance(entry, dict) else None
            replace = entry.get("replace") if isinstance(entry, dict) else None
            form = entry.get("form") if isinstance(entry, dict) else None
            form_fields = entry.get("form_fields") if isinstance(entry, dict) else None
            label = entry.get("label") if isinstance(entry, dict) else None
            word = entry.get("word") if isinstance(entry, dict) else None
            propagate_case = entry.get("propagate_case") if isinstance(entry, dict) else None
            uppercase_style = entry.get("uppercase_style") if isinstance(entry, dict) else None
            force_mode = entry.get("force_mode") if isinstance(entry, dict) else None
            shortcuts.append(
                Shortcut(
                    id=entry_id,
                    trigger=trigger if isinstance(trigger, str) else None,
                    replace=replace if isinstance(replace, str) else None,
                    form=form if isinstance(form, str) else None,
                    form_fields=form_fields if isinstance(form_fields, dict) else None,
                    form_fields_yaml=self.dumps(form_fields) if isinstance(form_fields, dict) else None,
                    label=label if isinstance(label, str) else None,
                    word=word if isinstance(word, bool) else None,
                    propagate_case=propagate_case if isinstance(propagate_case, bool) else None,
                    uppercase_style=uppercase_style if isinstance(uppercase_style, str) else None,
                    force_mode=force_mode if isinstance(force_mode, str) else None,
                    folder=self.folder_for_path(path, match_root),
                    file=path.name,
                    path=str(path),
                    editable=supported,
                    supported=supported,
                    kind="form" if supported and isinstance(form, str) else "basic" if supported else "advanced",
                    preview=replace if isinstance(replace, str) else form if isinstance(form, str) else None,
                    raw_yaml=self.dumps(entry) if isinstance(entry, dict) else None,
                )
            )
        return shortcuts

    def folder_for_path(self, path: Path, match_root: Path | None) -> str:
        if match_root is None:
            return "Root"
        try:
            parent = path.parent.resolve().relative_to(match_root.resolve())
        except ValueError:
            return "Root"
        return "Root" if str(parent) == "." else parent.as_posix()

    def is_supported(self, entry: Any) -> bool:
        return (
            isinstance(entry, dict)
            and isinstance(entry.get("trigger"), str)
            and (isinstance(entry.get("replace"), str) or isinstance(entry.get("form"), str))
            and set(entry.keys()).issubset(SUPPORTED_KEYS)
        )

    def validate_match_file(self, data: Any, require_matches: bool = True) -> list[dict[str, Any]]:
        errors: list[dict[str, Any]] = []
        if not isinstance(data, dict):
            return [{"code": "ROOT_NOT_MAPPING", "message": "YAML root must be a mapping."}]
        matches = data.get("matches")
        if matches is None:
            if require_matches:
                errors.append({"code": "MATCHES_MISSING", "message": "Root matches key is required."})
            return errors
        if not isinstance(matches, list):
            return [{"code": "MATCHES_NOT_LIST", "message": "matches must be a list."}]
        for index, entry in enumerate(matches):
            if not isinstance(entry, dict):
                errors.append({"code": "MATCH_NOT_MAPPING", "message": "Match entry must be a mapping.", "index": index})
                continue
            if self.is_supported(entry):
                trigger = entry.get("trigger")
                replace = entry.get("replace")
                form = entry.get("form")
                if not trigger.strip():
                    errors.append({"code": "EMPTY_TRIGGER", "message": "Trigger cannot be empty.", "index": index})
                if replace == "" and form is None:
                    errors.append({"code": "EMPTY_REPLACE", "message": "Replacement cannot be empty.", "index": index})
                if form == "" and replace is None:
                    errors.append({"code": "EMPTY_FORM", "message": "Form template cannot be empty.", "index": index})
                if "form_fields" in entry and not isinstance(entry.get("form_fields"), dict):
                    errors.append({"code": "INVALID_FORM_FIELDS", "message": "form_fields must be a mapping.", "index": index})
                for key in ("label", "uppercase_style"):
                    if key in entry and not isinstance(entry.get(key), str):
                        errors.append({"code": "INVALID_STRING_OPTION", "message": f"{key} must be a string.", "index": index})
                if "force_mode" in entry and entry.get("force_mode") not in {"clipboard", "keys"}:
                    errors.append({"code": "INVALID_FORCE_MODE", "message": "force_mode must be clipboard or keys.", "index": index})
                for key in ("word", "propagate_case"):
                    if key in entry and not isinstance(entry.get(key), bool):
                        errors.append({"code": "INVALID_BOOLEAN_OPTION", "message": f"{key} must be true or false.", "index": index})
        return errors

    def shortcut_id(self, path: Path, entry: Any) -> str:
        trigger = entry.get("trigger") if isinstance(entry, dict) else ""
        replace = entry.get("replace") if isinstance(entry, dict) else ""
        form = entry.get("form") if isinstance(entry, dict) else ""
        basis = f"{path.resolve()}::{trigger}::{replace}::{form}"
        return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24]
