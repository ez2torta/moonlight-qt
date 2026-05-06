#!/usr/bin/env python3
"""Send sequences to the Moonlight-Qt input injection control server."""

from __future__ import annotations

import argparse
import json
import socket
import sys
from pathlib import Path


def send_line(sock: socket.socket, obj: dict) -> None:
    data = (json.dumps(obj, separators=(",", ":")) + "\n").encode("utf-8")
    sock.sendall(data)


def recv_line(sock: socket.socket, buf: bytearray) -> dict:
    while b"\n" not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            raise RuntimeError("server closed connection")
        buf.extend(chunk)
    nl = buf.index(b"\n")
    line = bytes(buf[:nl])
    del buf[: nl + 1]
    return json.loads(line.decode("utf-8"))


def cmd_play(args: argparse.Namespace) -> int:
    seq = json.loads(Path(args.sequence).read_text(encoding="utf-8"))
    fps = float(args.fps if args.fps else seq.get("fps", 120.0))

    msg = {
        "op": "PLAY",
        "fps": fps,
        "shift_frames": {"0": args.shift_pad0, "1": args.shift_pad1},
        "seq": seq,
    }
    return _exchange(args, [msg])


def cmd_stop(args: argparse.Namespace) -> int:
    return _exchange(args, [{"op": "STOP"}])


def cmd_hold(args: argparse.Namespace) -> int:
    msg = {"op": "HOLD", "pad": args.pad, "b": list(args.buttons or [])}
    if args.lt is not None:
        msg["lt"] = args.lt
    if args.rt is not None:
        msg["rt"] = args.rt
    if args.lx is not None:
        msg["lx"] = args.lx
    if args.ly is not None:
        msg["ly"] = args.ly
    return _exchange(args, [msg])


def cmd_status(args: argparse.Namespace) -> int:
    return _exchange(args, [{"op": "STATUS"}])


def cmd_ping(args: argparse.Namespace) -> int:
    return _exchange(args, [{"op": "PING"}])


def _exchange(args: argparse.Namespace, messages: list[dict]) -> int:
    with socket.create_connection((args.host, args.port), timeout=args.timeout) as s:
        s.settimeout(args.timeout)
        buf = bytearray()
        send_line(s, {"op": "HELLO", "token": args.token, "ver": 1})
        hello_resp = recv_line(s, buf)
        if hello_resp.get("op") != "OK":
            print(f"handshake failed: {hello_resp}", file=sys.stderr)
            return 2
        for msg in messages:
            send_line(s, msg)
            resp = recv_line(s, buf)
            print(json.dumps(resp))
            if resp.get("op") == "ERR":
                return 3
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, required=True)
    p.add_argument("--token", required=True)
    p.add_argument("--timeout", type=float, default=5.0)

    sub = p.add_subparsers(dest="cmd")
    sub.required = False  # default = play

    play = sub.add_parser("play", help="play a sequence file")
    play.add_argument("sequence")
    play.add_argument("--fps", type=float, default=None)
    play.add_argument("--shift-pad0", type=int, default=0)
    play.add_argument("--shift-pad1", type=int, default=0)
    play.set_defaults(func=cmd_play)

    stop = sub.add_parser("stop", help="cancel any active sequence")
    stop.set_defaults(func=cmd_stop)

    hold = sub.add_parser("hold", help="hold a static state on a pad")
    hold.add_argument("--pad", type=int, choices=[0, 1], required=True)
    hold.add_argument("--buttons", nargs="*")
    hold.add_argument("--lt", type=int)
    hold.add_argument("--rt", type=int)
    hold.add_argument("--lx", type=int)
    hold.add_argument("--ly", type=int)
    hold.set_defaults(func=cmd_hold)

    status = sub.add_parser("status", help="print injector status")
    status.set_defaults(func=cmd_status)

    ping = sub.add_parser("ping", help="round-trip check")
    ping.set_defaults(func=cmd_ping)

    return p


def main() -> int:
    parser = build_parser()
    # Convenience: if first positional is a path, behave like `play <path>`.
    argv = sys.argv[1:]
    if argv:
        for i, a in enumerate(argv):
            if a in {"play", "stop", "hold", "status", "ping"}:
                break
            if a.endswith(".json") or a.endswith(".mlseq"):
                argv.insert(i, "play")
                break
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
