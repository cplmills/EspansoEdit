from __future__ import annotations

import plistlib
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.models.schemas import MacOSTextReplacementItem, MacOSTextReplacementPreview
from app.utils.errors import AppError

DEFAULT_PREFERENCES_PATH = Path.home() / "Library" / "Preferences" / ".GlobalPreferences.plist"
REPLACEMENT_KEYS = ("NSUserDictionaryReplacementItems", "NSUserReplacementItems")


@dataclass(frozen=True)
class TextReplacementSource:
    path: Path
    keys: tuple[str, ...] = REPLACEMENT_KEYS


class MacOSTextReplacementImportService:
    def __init__(self, preference_path: Path | None = None) -> None:
        self.preference_path = preference_path
        self.sources = (TextReplacementSource(preference_path, REPLACEMENT_KEYS),) if preference_path else self._default_sources()

    def preview(self) -> MacOSTextReplacementPreview:
        macos_version = self._macos_version()
        first_source = self.sources[0].path if self.sources else DEFAULT_PREFERENCES_PATH
        found_preferences = False

        for source in self.sources:
            if not source.path.exists():
                continue
            found_preferences = True
            data = self._read_preferences(source.path)
            for key in source.keys:
                raw_items = data.get(key)
                if raw_items is None:
                    continue
                if not isinstance(raw_items, list):
                    raise AppError(
                        "MACOS_REPLACEMENTS_INVALID",
                        "macOS text replacements were not in the expected format.",
                        {"path": str(source.path), "key": key},
                        422,
                    )
                return self._preview_items(source.path, key, raw_items, macos_version)

        return MacOSTextReplacementPreview(
            available=found_preferences,
            macos_version=macos_version,
            source_path=str(first_source),
            items=[],
            unsupported_count=0,
        )

    def _preview_items(
        self,
        source_path: Path,
        source_key: str,
        raw_items: list[Any],
        macos_version: str | None,
    ) -> MacOSTextReplacementPreview:
        items: list[MacOSTextReplacementItem] = []
        unsupported_count = 0
        for raw_item in raw_items:
            item = self._parse_item(raw_item)
            if item:
                items.append(item)
            else:
                unsupported_count += 1

        return MacOSTextReplacementPreview(
            available=True,
            macos_version=macos_version,
            source_path=str(source_path),
            source_key=source_key,
            items=items,
            unsupported_count=unsupported_count,
        )

    def _read_preferences(self, path: Path) -> dict[str, Any]:
        try:
            with path.open("rb") as handle:
                data = plistlib.load(handle)
        except Exception as exc:
            raise AppError(
                "MACOS_REPLACEMENTS_READ_FAILED",
                "Failed to read macOS text replacements.",
                {"path": str(path), "error": str(exc)},
                422,
            ) from exc
        if not isinstance(data, dict):
            raise AppError(
                "MACOS_REPLACEMENTS_INVALID",
                "macOS preferences were not in the expected format.",
                status_code=422,
            )
        return data

    def _parse_item(self, raw_item: Any) -> MacOSTextReplacementItem | None:
        if not isinstance(raw_item, dict):
            return None
        trigger = raw_item.get("replace")
        replacement = raw_item.get("with")
        enabled = raw_item.get("on", True)
        if not isinstance(trigger, str) or not isinstance(replacement, str):
            return None
        return MacOSTextReplacementItem(
            trigger=trigger,
            replacement=replacement,
            enabled=enabled not in {False, 0, "0", "false", "False"},
        )

    def _default_sources(self) -> tuple[TextReplacementSource, ...]:
        home = Path.home()
        return (
            TextReplacementSource(DEFAULT_PREFERENCES_PATH, REPLACEMENT_KEYS),
            TextReplacementSource(
                home / "Library" / "Group Containers" / "group.com.apple.UserDictionary" / "Library" / "Preferences" / "group.com.apple.UserDictionary.plist",
                REPLACEMENT_KEYS,
            ),
            TextReplacementSource(
                home / "Library" / "Group Containers" / "group.com.apple.UserDictionary" / "Library" / "Preferences" / ".GlobalPreferences.plist",
                REPLACEMENT_KEYS,
            ),
        )

    def _macos_version(self) -> str | None:
        try:
            result = subprocess.run(
                ["sw_vers", "-productVersion"],
                capture_output=True,
                check=False,
                text=True,
                timeout=2,
            )
        except Exception:
            return None
        version = result.stdout.strip()
        return version or None
