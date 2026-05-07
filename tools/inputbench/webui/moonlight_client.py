from __future__ import annotations

import json
import socket
import threading
from dataclasses import dataclass
from typing import Any


@dataclass
class MoonlightConnectionConfig:
    host: str
    port: int
    token: str
    timeout_sec: float = 5.0


class MoonlightClient:
    def __init__(self, config: MoonlightConnectionConfig):
        self._cfg = config
        self._sock: socket.socket | None = None
        self._buf = bytearray()
        self._lock = threading.Lock()

    def close(self) -> None:
        with self._lock:
            if self._sock is not None:
                try:
                    self._sock.close()
                except OSError:
                    pass
                self._sock = None
                self._buf.clear()

    def request(self, message: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            return self._request_locked(message)

    def _request_locked(self, message: dict[str, Any]) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                self._ensure_connected_locked()
                assert self._sock is not None
                self._send_line_locked(message)
                return self._recv_line_locked()
            except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
                last_error = exc
                self._reset_socket_locked()
                if attempt == 1:
                    break
        raise RuntimeError(f"moonlight request failed: {last_error}")

    def _ensure_connected_locked(self) -> None:
        if self._sock is not None:
            return
        sock = socket.create_connection((self._cfg.host, self._cfg.port), timeout=self._cfg.timeout_sec)
        sock.settimeout(self._cfg.timeout_sec)
        self._sock = sock
        self._buf.clear()
        self._send_line_locked({"op": "HELLO", "token": self._cfg.token, "ver": 1})
        hello = self._recv_line_locked()
        if hello.get("op") != "OK":
            self._reset_socket_locked()
            raise RuntimeError(f"handshake failed: {hello}")

    def _reset_socket_locked(self) -> None:
        if self._sock is None:
            return
        try:
            self._sock.close()
        except OSError:
            pass
        self._sock = None
        self._buf.clear()

    def _send_line_locked(self, obj: dict[str, Any]) -> None:
        if self._sock is None:
            raise RuntimeError("socket not connected")
        payload = (json.dumps(obj, separators=(",", ":")) + "\n").encode("utf-8")
        self._sock.sendall(payload)

    def _recv_line_locked(self) -> dict[str, Any]:
        if self._sock is None:
            raise RuntimeError("socket not connected")
        while b"\n" not in self._buf:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise RuntimeError("server closed connection")
            self._buf.extend(chunk)
        index = self._buf.index(b"\n")
        line = bytes(self._buf[:index])
        del self._buf[: index + 1]
        obj = json.loads(line.decode("utf-8"))
        if not isinstance(obj, dict):
            raise ValueError("non-object response")
        return obj
