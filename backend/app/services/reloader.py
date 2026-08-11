from __future__ import annotations

import subprocess
from dataclasses import dataclass, asdict

from app.services.espanso_discovery import EspansoDiscoveryService


@dataclass
class ReloadResult:
    success: bool
    command: list[str]
    stdout: str
    stderr: str
    exit_code: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class EspansoReloadService:
    def __init__(self, discovery: EspansoDiscoveryService | None = None) -> None:
        self.discovery = discovery or EspansoDiscoveryService()
        self.last_successful_reload: dict[str, object] | None = None

    def reload(self) -> ReloadResult:
        paths = self.discovery.discover()
        if not paths.executable:
            return ReloadResult(False, [], "", "Espanso executable was not found.", 127)

        reload_command = [paths.executable, "reload"]
        if self._supports_command(paths.executable, "reload"):
            result = self._run(reload_command)
            if result.exit_code == 0:
                self.last_successful_reload = result.to_dict()
            return result

        result = ReloadResult(
            True,
            [],
            "Espanso is watching the config directory; no explicit reload command is available.",
            "",
            0,
        )
        self.last_successful_reload = result.to_dict()
        return result

    def _supports_command(self, executable: str, command_name: str) -> bool:
        result = self._run([executable, "--help"])
        return result.exit_code == 0 and command_name in result.stdout.split()

    def _run(self, command: list[str]) -> ReloadResult:
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            return ReloadResult(
                success=completed.returncode == 0,
                command=command,
                stdout=completed.stdout,
                stderr=completed.stderr,
                exit_code=completed.returncode,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return ReloadResult(False, command, "", str(exc), 1)
