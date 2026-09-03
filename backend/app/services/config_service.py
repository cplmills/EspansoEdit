from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ruamel.yaml.comments import CommentedMap

from app.models.schemas import (
    EspansoConfigOption,
    EspansoConfigPayload,
    EspansoConfigUpdate,
    EspansoConfigValue,
)
from app.services.espanso_discovery import EspansoDiscoveryService, EspansoPaths
from app.services.reloader import EspansoReloadService
from app.services.yaml_service import YamlMatchService
from app.utils.errors import AppError


@dataclass(frozen=True)
class ConfigOptionDefinition:
    key: str
    label: str
    description: str
    type: str
    category: str
    default: Any = None
    choices: tuple[str, ...] = ()


CONFIG_OPTIONS: tuple[ConfigOptionDefinition, ...] = (
    ConfigOptionDefinition("backend", "Backend", "How Espanso injects expansions into the active app.", "select", "Injection", "auto", ("auto", "clipboard", "inject")),
    ConfigOptionDefinition("clipboard_threshold", "Clipboard threshold", "Character count after which Auto mode uses clipboard injection.", "number", "Injection", 100),
    ConfigOptionDefinition("paste_shortcut", "Paste shortcut", "Keyboard shortcut Espanso uses when pasting clipboard expansions.", "text", "Injection", "CTRL+V"),
    ConfigOptionDefinition("pre_paste_delay", "Pre-paste delay", "Milliseconds to wait before triggering the paste shortcut.", "number", "Injection", 300),
    ConfigOptionDefinition("paste_shortcut_event_delay", "Paste shortcut event delay", "Milliseconds between key events while simulating paste.", "number", "Injection", 10),
    ConfigOptionDefinition("restore_clipboard_delay", "Restore clipboard delay", "Milliseconds to wait before restoring the previous clipboard content.", "number", "Injection", 300),
    ConfigOptionDefinition("inject_delay", "Inject delay", "Milliseconds between injected text events.", "number", "Injection", 0),
    ConfigOptionDefinition("key_delay", "Key delay", "Milliseconds between injected key events.", "number", "Injection", 0),
    ConfigOptionDefinition("preserve_clipboard", "Preserve clipboard", "Restore previous clipboard content after an expansion.", "boolean", "Clipboard", True),
    ConfigOptionDefinition("toggle_key", "Toggle key", "Modifier key that enables or disables Espanso when double-pressed.", "select", "Controls", "OFF", ("OFF", "CTRL", "ALT", "SHIFT", "META", "LEFT_CTRL", "LEFT_ALT", "LEFT_SHIFT", "LEFT_META", "RIGHT_CTRL", "RIGHT_ALT", "RIGHT_SHIFT", "RIGHT_META")),
    ConfigOptionDefinition("search_shortcut", "Search shortcut", "Keyboard shortcut used to open Espanso's search window.", "text", "Controls", "ALT+Space"),
    ConfigOptionDefinition("search_trigger", "Search trigger", "Typed trigger used to open Espanso's search window.", "text", "Controls", "off"),
    ConfigOptionDefinition("show_icon", "Show menu bar icon", "Show the Espanso status icon in the macOS menu bar or system tray.", "boolean", "Interface", True),
    ConfigOptionDefinition("show_notifications", "Show notifications", "Allow Espanso to show desktop notifications.", "boolean", "Interface", True),
    ConfigOptionDefinition("max_form_width", "Max form width", "Maximum Espanso form width in pixels.", "number", "Forms", 700),
    ConfigOptionDefinition("max_form_height", "Max form height", "Maximum Espanso form height in pixels.", "number", "Forms", 500),
    ConfigOptionDefinition("post_form_delay", "Post-form delay", "Milliseconds to wait after a form closes before returning text.", "number", "Forms", 200),
    ConfigOptionDefinition("post_search_delay", "Post-search delay", "Milliseconds to wait after search closes before returning text.", "number", "Controls", 200),
    ConfigOptionDefinition("enable", "Enable Espanso", "Enable Espanso for this configuration.", "boolean", "General", True),
    ConfigOptionDefinition("auto_restart", "Auto restart", "Restart Espanso's worker after configuration files change.", "boolean", "General", True),
    ConfigOptionDefinition("apply_patch", "Apply built-in patches", "Allow Espanso's app-specific built-in compatibility patches.", "boolean", "General", True),
    ConfigOptionDefinition("undo_backspace", "Undo on backspace", "Pressing backspace after an expansion reverts it where supported.", "boolean", "General", True),
    ConfigOptionDefinition("backspace_limit", "Backspace limit", "How many backspaces Espanso tracks for correcting mistyped triggers.", "number", "General", 5),
    ConfigOptionDefinition("word_separators", "Word separators", "Characters Espanso treats as word boundaries.", "list", "General", [" ", ",", ".", "?", "!", "\\n", "\\t"]),
    ConfigOptionDefinition("max_regex_buffer_size", "Regex buffer size", "Maximum buffer length used for regex trigger matching.", "number", "Advanced", 30),
    ConfigOptionDefinition("evdev_modifier_delay", "EVDEV modifier delay", "Extra modifier injection delay on Wayland.", "number", "Advanced", 10),
    ConfigOptionDefinition("emulate_alt_codes", "Emulate ALT codes", "Restore Windows ALT-code behavior.", "boolean", "Advanced", False),
    ConfigOptionDefinition("disable_x11_fast_inject", "Disable X11 fast inject", "Use a slower X11 injection strategy for compatibility.", "boolean", "Advanced", False),
    ConfigOptionDefinition("x11_use_xclip_backend", "Use xclip clipboard backend", "Use xclip for clipboard operations on X11.", "boolean", "Advanced", False),
    ConfigOptionDefinition("x11_use_xdotool_backend", "Use xdotool inject backend", "Use xdotool for injection on X11.", "boolean", "Advanced", False),
)

CONFIG_OPTION_BY_KEY = {option.key: option for option in CONFIG_OPTIONS}


class EspansoConfigService:
    def __init__(
        self,
        discovery: EspansoDiscoveryService | None = None,
        reloader: EspansoReloadService | None = None,
        yaml: YamlMatchService | None = None,
    ) -> None:
        self.discovery = discovery or EspansoDiscoveryService()
        self.reloader = reloader or EspansoReloadService(self.discovery)
        self.yaml = yaml or YamlMatchService()

    def get_config(self) -> EspansoConfigPayload:
        paths = self._paths_or_error()
        default_path = self._default_config_path(paths)
        data = self._load_default_config(default_path)
        return self._payload(paths, default_path, data)

    def update_config(self, payload: EspansoConfigUpdate) -> EspansoConfigPayload:
        paths = self._paths_or_error()
        default_path = self._default_config_path(paths)
        default_path.parent.mkdir(parents=True, exist_ok=True)
        data = self._load_default_config(default_path)

        for key in CONFIG_OPTION_BY_KEY:
            data.pop(key, None)

        for item in payload.values:
            option = CONFIG_OPTION_BY_KEY.get(item.key)
            if option is None:
                raise AppError("CONFIG_OPTION_UNKNOWN", f"{item.key} is not a supported Espanso setting.", status_code=422)
            if not item.enabled:
                continue
            data[item.key] = self._coerce_value(option, item.value)

        self.yaml.dump_file(default_path, data)
        reload_result = self.reloader.reload()
        return self._payload(paths, default_path, data, reload_result.to_dict())

    def config_yaml_files(self) -> list[Path]:
        paths = self._paths_or_error()
        if not paths.config_dir or not paths.config_dir.exists():
            return []
        return sorted(paths.config_dir.glob("*.yml")) + sorted(paths.config_dir.glob("*.yaml"))

    def _paths_or_error(self) -> EspansoPaths:
        paths = self.discovery.discover()
        if not paths.config_path:
            raise AppError("ESPANSO_CONFIG_MISSING", "Espanso config path could not be detected.", status_code=404)
        return paths

    def _default_config_path(self, paths: EspansoPaths) -> Path:
        if not paths.config_dir:
            raise AppError("ESPANSO_CONFIG_MISSING", "Espanso config directory could not be detected.", status_code=404)
        return paths.config_dir / "default.yml"

    def _load_default_config(self, path: Path) -> CommentedMap:
        if not path.exists():
            return CommentedMap()
        data = self.yaml.load_file(path)
        if data is None:
            return CommentedMap()
        if not isinstance(data, dict):
            raise AppError("CONFIG_INVALID", "Espanso default.yml must contain a YAML mapping.", status_code=422)
        return data if isinstance(data, CommentedMap) else CommentedMap(data)

    def _payload(
        self,
        paths: EspansoPaths,
        default_path: Path,
        data: CommentedMap,
        reload_result: dict[str, Any] | None = None,
    ) -> EspansoConfigPayload:
        values = {
            option.key: EspansoConfigValue(
                key=option.key,
                enabled=option.key in data,
                value=data.get(option.key, option.default),
            )
            for option in CONFIG_OPTIONS
        }
        unknown_values = {str(key): value for key, value in data.items() if str(key) not in CONFIG_OPTION_BY_KEY}
        files = []
        for path in self.config_yaml_files():
            files.append({"path": str(path), "file": path.name, "content": path.read_text(encoding="utf-8")})
        return EspansoConfigPayload(
            status={
                "installed": paths.installed,
                "version": paths.version,
                "running": paths.running,
                "config_path": str(paths.config_path) if paths.config_path else None,
                "match_path": str(paths.match_path) if paths.match_path else None,
                "config_dir": str(paths.config_dir) if paths.config_dir else None,
                "executable": paths.executable,
                "yaml_valid": True,
                "duplicate_triggers": [],
                "last_reload": reload_result,
            },
            default_path=str(default_path),
            options=[
                EspansoConfigOption(
                    key=option.key,
                    label=option.label,
                    description=option.description,
                    type=option.type,
                    category=option.category,
                    default=option.default,
                    choices=list(option.choices),
                )
                for option in CONFIG_OPTIONS
            ],
            values=values,
            unknown_values=unknown_values,
            files=files,
            reload=reload_result,
        )

    def _coerce_value(self, option: ConfigOptionDefinition, value: Any) -> Any:
        if option.type == "boolean":
            if not isinstance(value, bool):
                raise AppError("CONFIG_VALUE_INVALID", f"{option.label} must be true or false.", status_code=422)
            return value
        if option.type == "number":
            if isinstance(value, bool):
                raise AppError("CONFIG_VALUE_INVALID", f"{option.label} must be a number.", status_code=422)
            try:
                number = int(value)
            except (TypeError, ValueError) as exc:
                raise AppError("CONFIG_VALUE_INVALID", f"{option.label} must be a number.", status_code=422) from exc
            if number < 0:
                raise AppError("CONFIG_VALUE_INVALID", f"{option.label} cannot be negative.", status_code=422)
            return number
        if option.type == "select":
            text = str(value or "").strip()
            if text not in option.choices:
                raise AppError("CONFIG_VALUE_INVALID", f"{option.label} must be one of: {', '.join(option.choices)}.", status_code=422)
            return text
        if option.type == "list":
            if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
                raise AppError("CONFIG_VALUE_INVALID", f"{option.label} must be a list of text values.", status_code=422)
            return value
        text = str(value or "").strip()
        if not text:
            raise AppError("CONFIG_VALUE_INVALID", f"{option.label} cannot be blank when enabled.", status_code=422)
        return text
