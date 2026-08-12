from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from app.models.schemas import PackageInstall, PackageItem
from app.services.espanso_discovery import EspansoDiscoveryService, EspansoPaths
from app.services.reloader import EspansoReloadService
from app.services.yaml_service import YamlMatchService
from app.utils.errors import AppError


class EspansoPackageService:
    def __init__(
        self,
        discovery: EspansoDiscoveryService | None = None,
        reloader: EspansoReloadService | None = None,
    ) -> None:
        self.discovery = discovery or EspansoDiscoveryService()
        self.reloader = reloader or EspansoReloadService(self.discovery)
        self.yaml = YamlMatchService()

    def list_packages(self) -> list[PackageItem]:
        package_root = self._package_root()
        if not package_root.exists():
            return []
        return [self._package_item(path) for path in sorted(package_root.iterdir()) if path.is_dir() and not path.name.startswith(".")]

    def install_package(self, payload: PackageInstall) -> dict[str, Any]:
        command = self._install_command(payload)
        result = self._run(command, timeout=120)
        if result["exit_code"] != 0:
            raise AppError("PACKAGE_INSTALL_FAILED", "Espanso package install failed.", result, 500)
        reload_result = self.reloader.reload()
        return {
            **result,
            "reload": reload_result.to_dict(),
            "package": self._find_package(payload),
        }

    def uninstall_package(self, name: str) -> dict[str, Any]:
        package_name = self._validate_name(name)
        before = self._package_path(package_name)
        command = self._base_command("uninstall") + [package_name]
        result = self._run(command, timeout=60)
        if result["exit_code"] != 0:
            if before.exists():
                shutil.rmtree(before)
            else:
                raise AppError("PACKAGE_UNINSTALL_FAILED", "Espanso package uninstall failed.", result, 500)
        reload_result = self.reloader.reload()
        return {**result, "reload": reload_result.to_dict(), "package": None}

    def update_package(self, name: str) -> dict[str, Any]:
        package_name = self._validate_name(name)
        command = self._base_command("update") + [package_name]
        result = self._run(command, timeout=120)
        if result["exit_code"] != 0:
            raise AppError("PACKAGE_UPDATE_FAILED", "Espanso package update failed.", result, 500)
        reload_result = self.reloader.reload()
        return {**result, "reload": reload_result.to_dict(), "package": self._package_item(self._package_path(package_name)) if package_name != "all" and self._package_path(package_name).exists() else None}

    def _install_command(self, payload: PackageInstall) -> list[str]:
        name = self._optional_name(payload.name)
        git = (payload.git or "").strip()
        if not name and not git:
            raise AppError("INVALID_PACKAGE", "Enter a package name or Git repository URL.", status_code=422)
        command = self._base_command("install")
        if payload.external:
            command.append("--external")
        if payload.force:
            command.append("--force")
        if payload.refresh_index:
            command.append("--refresh-index")
        if payload.use_native_git:
            command.append("--use-native-git")
        if payload.version:
            command.extend(["--version", payload.version.strip()])
        if git:
            command.extend(["--git", git])
        if payload.branch:
            command.extend(["--git-branch", payload.branch.strip()])
        if name:
            command.append(name)
        return command

    def _base_command(self, subcommand: str) -> list[str]:
        paths = self._paths_or_error()
        if not paths.executable:
            raise AppError("ESPANSO_NOT_INSTALLED", "Espanso executable was not found.", status_code=404)
        return [paths.executable, "package", subcommand]

    def _paths_or_error(self) -> EspansoPaths:
        paths = self.discovery.discover()
        if not paths.config_path or not paths.match_path:
            raise AppError("ESPANSO_CONFIG_NOT_FOUND", "Espanso configuration directory could not be detected.", status_code=404)
        return paths

    def _package_root(self) -> Path:
        paths = self._paths_or_error()
        return paths.match_path / "packages"

    def _package_path(self, name: str) -> Path:
        root = self._package_root().resolve()
        target = (root / name).resolve()
        if root not in target.parents:
            raise AppError("PATH_NOT_ALLOWED", "Invalid package path.", status_code=403)
        return target

    def _package_item(self, path: Path) -> PackageItem:
        yaml_files = sorted(file for file in path.rglob("*") if file.is_file() and file.suffix.lower() in {".yml", ".yaml"})
        shortcut_count = 0
        yaml_valid = True
        metadata = self._metadata(path, yaml_files)
        for yaml_file in yaml_files:
            try:
                shortcuts = self.yaml.parse_shortcuts(yaml_file, self._package_root())
                shortcut_count += len(shortcuts)
            except AppError:
                yaml_valid = False
        return PackageItem(
            name=path.name,
            path=str(path),
            file_count=len(yaml_files),
            shortcut_count=shortcut_count,
            yaml_valid=yaml_valid,
            version=metadata.get("version"),
            description=metadata.get("description"),
            source=metadata.get("source"),
        )

    def _metadata(self, path: Path, yaml_files: list[Path]) -> dict[str, str | None]:
        candidates = [
            path / "_manifest.yml",
            path / "_manifest.yaml",
            path / "package.yml",
            path / "package.yaml",
            *yaml_files,
        ]
        for candidate in candidates:
            if not candidate.exists():
                continue
            try:
                data = self.yaml.load_file(candidate)
            except AppError:
                continue
            if not isinstance(data, dict):
                continue
            package = data.get("package") if isinstance(data.get("package"), dict) else data
            if not isinstance(package, dict):
                continue
            return {
                "version": self._string_value(package.get("version")),
                "description": self._string_value(package.get("description")),
                "source": self._string_value(package.get("source") or package.get("homepage") or package.get("repo")),
            }
        return {}

    def _find_package(self, payload: PackageInstall) -> PackageItem | None:
        name = self._optional_name(payload.name)
        if name and self._package_path(name).exists():
            return self._package_item(self._package_path(name))
        packages = self.list_packages()
        return packages[-1] if packages else None

    def _validate_name(self, value: str) -> str:
        name = value.strip()
        if not name:
            raise AppError("INVALID_PACKAGE", "Package name is required.", status_code=422)
        if "/" in name or "\\" in name or name in {".", ".."} or name.startswith("."):
            raise AppError("INVALID_PACKAGE", "Package name cannot contain path separators.", status_code=422)
        return name

    def _optional_name(self, value: str | None) -> str:
        if not value or not value.strip():
            return ""
        return self._validate_name(value)

    def _string_value(self, value: Any) -> str | None:
        return value if isinstance(value, str) and value.strip() else None

    def _run(self, command: list[str], timeout: int) -> dict[str, Any]:
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
            return {
                "command": command,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
                "exit_code": completed.returncode,
            }
        except (OSError, subprocess.SubprocessError) as exc:
            return {
                "command": command,
                "stdout": "",
                "stderr": str(exc),
                "exit_code": 1,
            }
