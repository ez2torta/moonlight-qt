from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


@dataclass
class RecorderConfig:
    enabled: bool = False
    command: list[str] | str | None = None


class AttemptRecorder:
    def __init__(self, config: RecorderConfig):
        self._config = config
        self._proc: subprocess.Popen[bytes] | None = None
        self._last_output: Path | None = None

    @property
    def enabled(self) -> bool:
        return bool(self._config.enabled and self._config.command)

    @property
    def last_output(self) -> Path | None:
        return self._last_output

    def start(self, output_path: Path) -> Path | None:
        if not self.enabled:
            return None
        self.stop()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = self._render_command(output_path)
        self._proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self._last_output = output_path
        return output_path

    def stop(self) -> None:
        if self._proc is None:
            return
        proc = self._proc
        self._proc = None
        try:
            if proc.stdin is not None:
                proc.stdin.write(b"q\n")
                proc.stdin.flush()
        except OSError:
            pass
        try:
            proc.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            proc.kill()

    def _render_command(self, output_path: Path) -> Sequence[str]:
        output = str(output_path)
        if isinstance(self._config.command, str):
            return [token.format(output=output) for token in shlex.split(self._config.command)]
        return [str(token).format(output=output) for token in (self._config.command or [])]
