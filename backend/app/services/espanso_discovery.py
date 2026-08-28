from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from shutil import which


@dataclass(frozen=True)
class EspansoPaths:
    installed: bool
    version: str | None
    running: bool
    config_path: Path | None
    match_path: Path | None
    config_dir: Path | None
    executable: str | None


class EspansoDiscoveryService:
    def discover(self) -> EspansoPaths:
        executable = self._executable()
        version = self._version(executable) if executable else None
        config_path = self._config_path(executable)
        if config_path is None:
            config_path = self._fallback_config_path()

        match_path = config_path / "match" if config_path else None
        config_dir = config_path / "config" if config_path else None
        running = self._running(executable)

        return EspansoPaths(
            installed=executable is not None,
            version=version,
            running=running,
            config_path=config_path,
            match_path=match_path,
            config_dir=config_dir,
            executable=executable,
        )

    def _executable(self) -> str | None:
        configured = os.environ.get("ESPANSO_EXECUTABLE")
        candidates = [
            configured,
            which("espanso"),
            "/usr/local/bin/espanso",
            "/opt/homebrew/bin/espanso",
            "/Applications/Espanso.app/Contents/MacOS/espanso",
        ]
        for candidate in candidates:
            if not candidate:
                continue
            path = Path(candidate).expanduser()
            if path.is_file() and os.access(path, os.X_OK):
                return str(path)
        return None

    def _version(self, executable: str) -> str | None:
        result = self._run([executable, "--version"])
        if result and result.returncode == 0:
            return (result.stdout or result.stderr).strip() or None
        return None

    def _config_path(self, executable: str | None) -> Path | None:
        if not executable:
            return None
        for args in ([executable, "path", "config"], [executable, "path"]):
            result = self._run(args)
            if result and result.returncode == 0:
                candidate = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
                if candidate:
                    return Path(candidate).expanduser()
        return None

    def _fallback_config_path(self) -> Path | None:
        candidates = [
            Path.home() / "Library" / "Application Support" / "espanso",
            Path.home() / ".config" / "espanso",
        ]
        return next((path for path in candidates if path.exists()), candidates[0])

    def _running(self, executable: str | None) -> bool:
        if executable:
            result = self._run([executable, "status"])
            text = f"{result.stdout if result else ''}\n{result.stderr if result else ''}".lower()
            if "running" in text:
                return True
            if result and result.returncode == 0 and "not running" not in text:
                return True
        pgrep = self._run(["pgrep", "-x", "espanso"])
        return bool(pgrep and pgrep.returncode == 0)

    def _run(self, args: list[str]) -> subprocess.CompletedProcess[str] | None:
        try:
            return subprocess.run(args, capture_output=True, text=True, timeout=5, check=False)
        except (OSError, subprocess.SubprocessError):
            return None
