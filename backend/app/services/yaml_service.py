from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from app.models.schemas import Shortcut
from app.utils.errors import AppError

CASE_INSENSITIVE_REGEX_PREFIX = "(?i)"
SUPPORTED_KEYS = {"trigger", "regex", "replace", "form", "form_fields", "label", "word", "propagate_case", "uppercase_style", "force_mode"}


def case_insensitive_regex_for_trigger(trigger: str) -> str:
    return f"{CASE_INSENSITIVE_REGEX_PREFIX}{re.escape(trigger)}"


def normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def trigger_from_case_insensitive_regex(regex: str) -> str | None:
    if not regex.startswith(CASE_INSENSITIVE_REGEX_PREFIX):
        return None
    trigger = re.sub(r"\\([^A-Za-z0-9])", r"\1", regex[len(CASE_INSENSITIVE_REGEX_PREFIX) :])
    if case_insensitive_regex_for_trigger(trigger) != regex:
        return None
    return trigger


class YamlMatchService:
    def __init__(self) -> None:
        self.yaml = self._new_yaml()

    def load_file(self, path: Path) -> Any:
        try:
            text = normalize_newlines(path.read_text(encoding="utf-8"))
            return self._new_yaml().load(text) if text.strip() else CommentedMap({"matches": CommentedSeq()})
        except Exception as exc:
            raise AppError("YAML_PARSE_FAILED", f"Failed to parse {path.name}.", str(exc), 422) from exc

    def dump_file(self, path: Path, data: Any) -> None:
        with path.open("w", encoding="utf-8") as handle:
            self._new_yaml().dump(data, handle)

    def dumps(self, data: Any) -> str:
        import io

        stream = io.StringIO()
        self._new_yaml().dump(data, stream)
        return stream.getvalue()

    def loads(self, text: str) -> Any:
        try:
            return self._new_yaml().load(normalize_newlines(text))
        except Exception as exc:
            raise AppError("YAML_VALIDATION_FAILED", "The proposed YAML is invalid.", str(exc), 422) from exc

    def _new_yaml(self) -> YAML:
        yaml = YAML()
        yaml.preserve_quotes = True
        yaml.indent(mapping=2, sequence=4, offset=2)
        return yaml

    def parse_shortcuts(self, path: Path, match_root: Path | None = None) -> list[Shortcut]:
        data = self.load_file(path)
        matches = data.get("matches") if isinstance(data, dict) else None
        if not isinstance(matches, list):
            return []

        shortcuts: list[Shortcut] = []
        for entry in matches:
            entry_id = self.shortcut_id(path, entry)
            supported = self.is_supported(entry)
            trigger = self.trigger_for_entry(entry)
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
                    trigger=trigger,
                    replace=replace if isinstance(replace, str) else None,
                    form=form if isinstance(form, str) else None,
                    form_fields=form_fields if isinstance(form_fields, dict) else None,
                    form_fields_yaml=self.dumps(form_fields) if isinstance(form_fields, dict) else None,
                    label=label if isinstance(label, str) else None,
                    word=word if isinstance(word, bool) else None,
                    propagate_case=propagate_case if isinstance(propagate_case, bool) else None,
                    case_insensitive=self.is_case_insensitive_entry(entry),
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
        trigger = self.trigger_for_entry(entry)
        return (
            isinstance(entry, dict)
            and isinstance(trigger, str)
            and (isinstance(entry.get("replace"), str) or isinstance(entry.get("form"), str))
            and set(entry.keys()).issubset(SUPPORTED_KEYS)
        )

    def trigger_for_entry(self, entry: Any) -> str | None:
        if not isinstance(entry, dict):
            return None
        trigger = entry.get("trigger")
        if isinstance(trigger, str):
            return trigger
        regex = entry.get("regex")
        if isinstance(regex, str):
            return trigger_from_case_insensitive_regex(regex)
        return None

    def is_case_insensitive_entry(self, entry: Any) -> bool:
        if not isinstance(entry, dict):
            return False
        regex = entry.get("regex")
        return isinstance(regex, str) and trigger_from_case_insensitive_regex(regex) is not None

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
                trigger = self.trigger_for_entry(entry)
                replace = entry.get("replace")
                form = entry.get("form")
                if not trigger or not trigger.strip():
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
        regex = entry.get("regex") if isinstance(entry, dict) else ""
        replace = entry.get("replace") if isinstance(entry, dict) else ""
        form = entry.get("form") if isinstance(entry, dict) else ""
        basis = f"{path.resolve()}::{trigger}::{regex}::{replace}::{form}"
        return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24]
