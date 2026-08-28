from __future__ import annotations

import plistlib
from pathlib import Path

import pytest

from app.models.schemas import MacOSTextReplacementImport, ShortcutCreate, ShortcutMove, ShortcutRawCreate, ShortcutRawUpdate, ShortcutUpdate
from app.services.macos_text_replacement_importer import MacOSTextReplacementImportService
from app.services.shortcut_service import ShortcutService
from app.utils.errors import AppError
from conftest import FakeDiscovery, FakeReloader


def write_match(root: Path, name: str, content: str) -> Path:
    path = root / "match" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def write_macos_replacements(path: Path, items: list[dict], key: str = "NSUserDictionaryReplacementItems") -> None:
    with path.open("wb") as handle:
        plistlib.dump({key: items}, handle)


def test_loading_simple_match_file(service: ShortcutService, espanso_root: Path) -> None:
    write_match(espanso_root, "base.yml", 'matches:\n  - trigger: ":hello"\n    replace: "Hello world"\n')

    shortcuts = service.list_shortcuts()

    assert len(shortcuts) == 1
    assert shortcuts[0].trigger == ":hello"
    assert shortcuts[0].replace == "Hello world"
    assert shortcuts[0].editable is True
    assert shortcuts[0].folder == "Root"


def test_loading_shortcut_folder_from_subdirectory(service: ShortcutService, espanso_root: Path) -> None:
    write_match(espanso_root, "work/email.yml", 'matches:\n  - trigger: ":hello"\n    replace: "Hello world"\n')

    shortcut = service.list_shortcuts()[0]

    assert shortcut.folder == "work"


def test_loading_multiline_replacements(service: ShortcutService, espanso_root: Path) -> None:
    write_match(espanso_root, "base.yml", 'matches:\n  - trigger: ":nfse"\n    replace: |\n      Line one\n      Line two\n')

    shortcut = service.list_shortcuts()[0]

    assert shortcut.replace == "Line one\nLine two\n"


def test_adding_cr_multiline_replacement_writes_literal_block(service: ShortcutService, espanso_root: Path) -> None:
    replacement = "Option Explicit\r\rFunction CleanAddress(ByVal txt As String) As String\r    Dim s As String\rEnd Function"

    service.add_shortcut(ShortcutCreate(trigger=":vba", replace=replacement, folder="Scripting"))

    content = (espanso_root / "match" / "Scripting" / "espanso-shortcut-manager.yml").read_text(encoding="utf-8")
    shortcut = service.list_shortcuts()[0]
    assert shortcut.replace == replacement.replace("\r", "\n")
    assert "replace: |" in content
    assert "\r" not in content
    assert "Option Explicit" in content
    assert "Function CleanAddress" in content


def test_adding_shortcut_creates_managed_file_and_backup(service: ShortcutService, espanso_root: Path) -> None:
    shortcut, reload_result = service.add_shortcut(ShortcutCreate(trigger=":new", replace="New text"))

    assert shortcut.trigger == ":new"
    assert reload_result.success is True
    assert (espanso_root / "match" / "espanso-shortcut-manager.yml").exists()
    assert len(service.list_backups()) == 1


def test_adding_shortcut_with_common_options(service: ShortcutService, espanso_root: Path) -> None:
    shortcut, _ = service.add_shortcut(
        ShortcutCreate(
            trigger=":name",
            replace="Chris",
            label="Name",
            word=True,
            propagate_case=True,
            uppercase_style="capitalize",
        )
    )

    content = (espanso_root / "match" / "espanso-shortcut-manager.yml").read_text(encoding="utf-8")
    assert shortcut.label == "Name"
    assert shortcut.word is True
    assert "label: Name" in content
    assert "word: true" in content
    assert "propagate_case: true" in content
    assert "uppercase_style: capitalize" in content


def test_adding_shortcut_with_force_mode(service: ShortcutService, espanso_root: Path) -> None:
    shortcut, _ = service.add_shortcut(ShortcutCreate(trigger=":clip", replace="Clipboard text", force_mode="clipboard"))

    content = (espanso_root / "match" / "espanso-shortcut-manager.yml").read_text(encoding="utf-8")
    assert shortcut.force_mode == "clipboard"
    assert "force_mode: clipboard" in content


def test_adding_case_insensitive_shortcut(service: ShortcutService, espanso_root: Path) -> None:
    shortcut, _ = service.add_shortcut(
        ShortcutCreate(trigger=".nfsabn", replace="ABN details", case_insensitive=True)
    )

    content = (espanso_root / "match" / "espanso-shortcut-manager.yml").read_text(encoding="utf-8")
    listed = service.list_shortcuts()[0]
    assert shortcut.case_insensitive is True
    assert listed.trigger == ".nfsabn"
    assert listed.case_insensitive is True
    assert listed.editable is True
    assert "regex: (?i)\\.nfsabn" in content
    assert "trigger:" not in content


def test_adding_form_shortcut(service: ShortcutService, espanso_root: Path) -> None:
    shortcut, _ = service.add_shortcut(
        ShortcutCreate(trigger=":reply", form="Hi [[name]],\n\n[[message]]", label="Reply form")
    )

    content = (espanso_root / "match" / "espanso-shortcut-manager.yml").read_text(encoding="utf-8")
    assert shortcut.kind == "form"
    assert shortcut.form == "Hi [[name]],\n\n[[message]]"
    assert "form:" in content
    assert "[[name]]" in content
    assert "replace:" not in content


def test_adding_form_shortcut_with_fields(service: ShortcutService, espanso_root: Path) -> None:
    shortcut, _ = service.add_shortcut(
        ShortcutCreate(
            trigger=":choice",
            form="Plan: [[plan]]",
            form_fields_yaml="plan:\n  type: choice\n  values:\n    - Basic\n    - Pro\n",
        )
    )

    content = (espanso_root / "match" / "espanso-shortcut-manager.yml").read_text(encoding="utf-8")
    assert shortcut.form_fields["plan"]["type"] == "choice"
    assert "form_fields:" in content
    assert "type: choice" in content


def test_adding_raw_yaml_shortcut(service: ShortcutService, espanso_root: Path) -> None:
    shortcut, _ = service.add_shortcut_raw(
        ShortcutRawCreate(
            yaml='trigger: ":raw"\nreplace: "Raw replacement"\nword: true\n',
            folder="raw",
        )
    )

    path = espanso_root / "match" / "raw" / "espanso-shortcut-manager.yml"
    content = path.read_text(encoding="utf-8")
    assert shortcut.trigger == ":raw"
    assert shortcut.supported is True
    assert "word: true" in content
    assert "Raw replacement" in content


def test_adding_advanced_raw_yaml_shortcut(service: ShortcutService, espanso_root: Path) -> None:
    shortcut, _ = service.add_shortcut_raw(
        ShortcutRawCreate(
            yaml='trigger: ":today"\nreplace: "{{today}}"\nvars:\n  - name: today\n    type: date\n',
        )
    )

    content = (espanso_root / "match" / "espanso-shortcut-manager.yml").read_text(encoding="utf-8")
    assert shortcut.trigger == ":today"
    assert shortcut.supported is False
    assert "type: date" in content


def test_adding_raw_yaml_shortcut_from_single_item_list(service: ShortcutService, espanso_root: Path) -> None:
    shortcut, _ = service.add_shortcut_raw(
        ShortcutRawCreate(
            yaml='- trigger: ":file"\n  replace: "{{form1.file}}"\n  vars:\n    - name: files\n      type: shell\n      params:\n        cmd: "find ~/Documents -maxdepth 1"\n',
        )
    )

    content = (espanso_root / "match" / "espanso-shortcut-manager.yml").read_text(encoding="utf-8")
    assert shortcut.trigger == ":file"
    assert shortcut.supported is False
    assert "- trigger: \":file\"" in content
    assert 'cmd: "find ~/Documents -maxdepth 1"' in content


def test_rejecting_multiple_raw_yaml_shortcuts(service: ShortcutService) -> None:
    with pytest.raises(AppError) as exc:
        service.add_shortcut_raw(
            ShortcutRawCreate(
                yaml='- trigger: ":one"\n  replace: "One"\n- trigger: ":two"\n  replace: "Two"\n',
            )
        )

    assert exc.value.code == "INVALID_MATCH_ENTRY"


def test_rejecting_full_match_file_as_raw_shortcut(service: ShortcutService) -> None:
    with pytest.raises(AppError) as exc:
        service.add_shortcut_raw(ShortcutRawCreate(yaml='matches:\n  - trigger: ":bad"\n    replace: "Bad"\n'))

    assert exc.value.code == "INVALID_MATCH_ENTRY"


def test_adding_shortcut_to_folder(service: ShortcutService, espanso_root: Path) -> None:
    shortcut, _ = service.add_shortcut(ShortcutCreate(trigger=":work", replace="Work text", folder="work/email"))

    path = espanso_root / "match" / "work" / "email" / "espanso-shortcut-manager.yml"
    assert shortcut.folder == "work/email"
    assert path.exists()
    assert ":work" in path.read_text(encoding="utf-8")


def test_listing_empty_folders(service: ShortcutService, espanso_root: Path) -> None:
    (espanso_root / "match" / "work" / "email").mkdir(parents=True)
    (espanso_root / "match" / "packages").mkdir()

    folders = service.list_folders()

    assert "Root" in folders
    assert "work" in folders
    assert "work/email" in folders
    assert "packages" not in folders


def test_creating_folder(service: ShortcutService, espanso_root: Path) -> None:
    folder = service.create_folder("work/email")

    assert folder == "work/email"
    assert (espanso_root / "match" / "work" / "email").is_dir()
    assert "work/email" in service.list_folders()


def test_previewing_macos_text_replacements(espanso_root: Path, tmp_path: Path) -> None:
    preferences = tmp_path / ".GlobalPreferences.plist"
    write_macos_replacements(
        preferences,
        [
            {"replace": "omw", "with": "On my way!", "on": 1},
            {"replace": "addr", "with": "123 Example Street", "on": 0},
            {"replace": "broken"},
        ],
    )
    service = ShortcutService(
        FakeDiscovery(espanso_root),
        FakeReloader(),
        MacOSTextReplacementImportService(preferences),
    )

    preview = service.preview_macos_text_replacements()

    assert preview.available is True
    assert preview.source_key == "NSUserDictionaryReplacementItems"
    assert preview.items[0].trigger == "omw"
    assert preview.items[0].replacement == "On my way!"
    assert preview.items[1].enabled is False
    assert preview.unsupported_count == 1


def test_previewing_legacy_macos_text_replacements_key(espanso_root: Path, tmp_path: Path) -> None:
    preferences = tmp_path / ".GlobalPreferences.plist"
    write_macos_replacements(
        preferences,
        [{"replace": "brb", "with": "Be right back", "on": 1}],
        key="NSUserReplacementItems",
    )
    service = ShortcutService(
        FakeDiscovery(espanso_root),
        FakeReloader(),
        MacOSTextReplacementImportService(preferences),
    )

    preview = service.preview_macos_text_replacements()

    assert preview.available is True
    assert preview.source_key == "NSUserReplacementItems"
    assert preview.items[0].trigger == "brb"


def test_importing_macos_text_replacements_skips_duplicates_and_disabled(espanso_root: Path, tmp_path: Path) -> None:
    write_match(espanso_root, "base.yml", 'matches:\n  - trigger: "omw"\n    replace: "Already here"\n')
    preferences = tmp_path / ".GlobalPreferences.plist"
    write_macos_replacements(
        preferences,
        [
            {"replace": "omw", "with": "On my way!", "on": 1},
            {"replace": "sig", "with": "Chris Mills", "on": 1},
            {"replace": "off", "with": "Disabled", "on": 0},
            {"replace": "sig", "with": "Duplicate import", "on": 1},
        ],
    )
    service = ShortcutService(
        FakeDiscovery(espanso_root),
        FakeReloader(),
        MacOSTextReplacementImportService(preferences),
    )

    result = service.import_macos_text_replacements(MacOSTextReplacementImport(folder="imported/macos"))

    target = espanso_root / "match" / "imported" / "macos" / "espanso-shortcut-manager.yml"
    content = target.read_text(encoding="utf-8")
    assert result.imported_count == 1
    assert result.skipped_count == 3
    assert result.imported[0].trigger == "sig"
    assert result.imported[0].folder == "imported/macos"
    assert "replace: Chris Mills" in content
    assert "Duplicate import" not in content
    assert {item.reason for item in result.skipped} == {"duplicate_existing", "disabled", "duplicate_import"}


def test_importing_selected_macos_text_replacements_only(espanso_root: Path, tmp_path: Path) -> None:
    preferences = tmp_path / ".GlobalPreferences.plist"
    write_macos_replacements(
        preferences,
        [
            {"replace": "sig", "with": "Chris Mills", "on": 1},
            {"replace": "addr", "with": "123 Example Street", "on": 1},
            {"replace": "off", "with": "Disabled", "on": 0},
        ],
    )
    service = ShortcutService(
        FakeDiscovery(espanso_root),
        FakeReloader(),
        MacOSTextReplacementImportService(preferences),
    )

    result = service.import_macos_text_replacements(
        MacOSTextReplacementImport(
            folder="selected",
            replacements=[service.preview_macos_text_replacements().items[1]],
        )
    )

    target = espanso_root / "match" / "selected" / "espanso-shortcut-manager.yml"
    content = target.read_text(encoding="utf-8")
    assert result.imported_count == 1
    assert result.imported[0].trigger == "addr"
    assert "123 Example Street" in content
    assert "Chris Mills" not in content
    assert [item.reason for item in result.skipped] == ["ignored", "ignored"]


def test_rejecting_reserved_folder(service: ShortcutService) -> None:
    with pytest.raises(AppError) as exc:
        service.add_shortcut(ShortcutCreate(trigger=":pkg", replace="No", folder="packages"))

    assert exc.value.code == "INVALID_FOLDER"


def test_editing_shortcut(service: ShortcutService, espanso_root: Path) -> None:
    write_match(espanso_root, "base.yml", 'matches:\n  - trigger: ":old"\n    replace: "Old"\n')
    shortcut = service.list_shortcuts()[0]

    updated, _ = service.update_shortcut(shortcut.id, ShortcutUpdate(trigger=":new", replace="New"))

    assert updated.trigger == ":new"
    assert "Old" not in (espanso_root / "match" / "base.yml").read_text(encoding="utf-8")


def test_editing_shortcut_options(service: ShortcutService, espanso_root: Path) -> None:
    write_match(espanso_root, "base.yml", 'matches:\n  - trigger: ":old"\n    replace: "Old"\n    word: true\n')
    shortcut = service.list_shortcuts()[0]

    updated, _ = service.update_shortcut(
        shortcut.id,
        ShortcutUpdate(trigger=":new", replace="New", label="New label", word=False, propagate_case=True),
    )

    content = (espanso_root / "match" / "base.yml").read_text(encoding="utf-8")
    assert updated.label == "New label"
    assert updated.word is None
    assert "label: New label" in content
    assert "word:" not in content
    assert "propagate_case: true" in content


def test_editing_case_insensitive_shortcut_back_to_trigger(service: ShortcutService, espanso_root: Path) -> None:
    created, _ = service.add_shortcut(
        ShortcutCreate(trigger=".nfsabn", replace="ABN details", case_insensitive=True)
    )

    updated, _ = service.update_shortcut(
        created.id,
        ShortcutUpdate(trigger=".nfsabn", replace="ABN details", case_insensitive=False),
    )

    content = (espanso_root / "match" / "espanso-shortcut-manager.yml").read_text(encoding="utf-8")
    assert updated.case_insensitive is False
    assert "trigger: .nfsabn" in content
    assert "regex:" not in content


def test_raw_editing_advanced_shortcut(service: ShortcutService, espanso_root: Path) -> None:
    path = write_match(
        espanso_root,
        "base.yml",
        'matches:\n  - trigger: ":date"\n    replace: "{{today}}"\n    vars:\n      - name: today\n        type: date\n',
    )
    shortcut = service.list_shortcuts()[0]
    assert shortcut.supported is False

    updated, _ = service.update_shortcut_raw(
        shortcut.id,
        ShortcutRawUpdate(
            yaml='trigger: ":date"\nreplace: "{{today}}"\nlabel: Today\nvars:\n  - name: today\n    type: date\n'
        ),
    )

    content = path.read_text(encoding="utf-8")
    assert updated.supported is False
    assert updated.label == "Today"
    assert "label: Today" in content
    assert "type: date" in content


def test_moving_shortcut_to_folder(service: ShortcutService, espanso_root: Path) -> None:
    write_match(espanso_root, "base.yml", 'matches:\n  - trigger: ":move"\n    replace: "Move me"\n')
    shortcut = service.list_shortcuts()[0]

    moved, _ = service.move_shortcut(shortcut.id, ShortcutMove(folder="work"))

    source = (espanso_root / "match" / "base.yml").read_text(encoding="utf-8")
    target = espanso_root / "match" / "work" / "espanso-shortcut-manager.yml"
    assert moved.folder == "work"
    assert ":move" not in source
    assert ":move" in target.read_text(encoding="utf-8")


def test_moving_advanced_shortcut_to_folder(service: ShortcutService, espanso_root: Path) -> None:
    write_match(
        espanso_root,
        "base.yml",
        'matches:\n  - trigger: ":date"\n    replace: "{{today}}"\n    vars:\n      - name: today\n        type: date\n',
    )
    shortcut = service.list_shortcuts()[0]

    moved, _ = service.move_shortcut(shortcut.id, ShortcutMove(folder="advanced"))

    target = espanso_root / "match" / "advanced" / "espanso-shortcut-manager.yml"
    assert moved.folder == "advanced"
    assert moved.supported is False
    assert "type: date" in target.read_text(encoding="utf-8")


def test_deleting_shortcut(service: ShortcutService, espanso_root: Path) -> None:
    write_match(espanso_root, "base.yml", 'matches:\n  - trigger: ":old"\n    replace: "Old"\n')
    shortcut = service.list_shortcuts()[0]

    deleted, _ = service.delete_shortcut(shortcut.id)

    assert deleted.id == shortcut.id
    assert service.list_shortcuts() == []


def test_preserving_unrelated_yaml_properties(service: ShortcutService, espanso_root: Path) -> None:
    path = write_match(
        espanso_root,
        "base.yml",
        'global_vars:\n  - name: user\n    type: echo\n    params:\n      echo: Chris\nmatches:\n  - trigger: ":old"\n    replace: "Old"\n',
    )
    shortcut = service.list_shortcuts()[0]

    service.update_shortcut(shortcut.id, ShortcutUpdate(trigger=":old", replace="Changed"))

    content = path.read_text(encoding="utf-8")
    assert "global_vars:" in content
    assert "echo: Chris" in content


def test_preserving_unsupported_entries(service: ShortcutService, espanso_root: Path) -> None:
    path = write_match(
        espanso_root,
        "base.yml",
        'matches:\n  - trigger: ":date"\n    replace: "{{today}}"\n    vars:\n      - name: today\n        type: date\n  - trigger: ":old"\n    replace: "Old"\n',
    )
    unsupported = service.list_shortcuts()[0]
    supported = service.list_shortcuts()[1]

    assert unsupported.supported is False
    service.update_shortcut(supported.id, ShortcutUpdate(trigger=":old", replace="Changed"))

    content = path.read_text(encoding="utf-8")
    assert "vars:" in content
    assert "type: date" in content


def test_detecting_duplicate_triggers(service: ShortcutService, espanso_root: Path) -> None:
    write_match(espanso_root, "a.yml", 'matches:\n  - trigger: ":dup"\n    replace: "A"\n')
    write_match(espanso_root, "b.yml", 'matches:\n  - trigger: ":dup"\n    replace: "B"\n')

    result = service.validate()

    assert result.duplicate_triggers[0]["trigger"] == ":dup"


def test_rejecting_new_duplicate_trigger(service: ShortcutService, espanso_root: Path) -> None:
    write_match(espanso_root, "a.yml", 'matches:\n  - trigger: ":dup"\n    replace: "A"\n')

    with pytest.raises(AppError) as exc:
        service.add_shortcut(ShortcutCreate(trigger=":dup", replace="B"))

    assert exc.value.code == "DUPLICATE_TRIGGER"


def test_invalid_yaml_rejection(service: ShortcutService, espanso_root: Path) -> None:
    write_match(espanso_root, "broken.yml", "matches:\n  - trigger: [")

    result = service.validate()

    assert result.yaml_valid is False
    assert result.errors[0]["code"] == "YAML_PARSE_FAILED"


def test_rollback_after_simulated_reload_failure(espanso_root: Path) -> None:
    service = ShortcutService(FakeDiscovery(espanso_root), FakeReloader(should_fail=True))
    path = write_match(espanso_root, "base.yml", 'matches:\n  - trigger: ":old"\n    replace: "Old"\n')
    shortcut = service.list_shortcuts()[0]

    with pytest.raises(AppError) as exc:
        service.update_shortcut(shortcut.id, ShortcutUpdate(trigger=":old", replace="Changed"))

    assert exc.value.code == "ESPANSO_RELOAD_FAILED"
    assert 'replace: "Old"' in path.read_text(encoding="utf-8")


def test_preventing_writes_outside_allowed_directories(service: ShortcutService, tmp_path: Path) -> None:
    outside = tmp_path / "outside.yml"
    outside.write_text("matches:\n", encoding="utf-8")

    with pytest.raises(AppError) as exc:
        service._allowed_file(outside)

    assert exc.value.code == "PATH_NOT_ALLOWED"
