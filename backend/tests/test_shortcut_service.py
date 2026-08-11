from __future__ import annotations

from pathlib import Path

import pytest

from app.models.schemas import ShortcutCreate, ShortcutMove, ShortcutRawUpdate, ShortcutUpdate
from app.services.shortcut_service import ShortcutService
from app.utils.errors import AppError
from conftest import FakeDiscovery, FakeReloader


def write_match(root: Path, name: str, content: str) -> Path:
    path = root / "match" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


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
