from __future__ import annotations

import itertools
import json
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal

from moonlight_client import MoonlightClient
from recorder import AttemptRecorder
from winner_detector import WinnerDetector, Winner

ActionName = Literal["none", "walk_forward", "walk_back", "jump_forward", "jump_neutral", "jump_back", "dash_forward", "dash_back"]


@dataclass
class RangeSpec:
    min: int
    max: int
    step: int = 1

    def values(self) -> list[int]:
        hi = max(self.min, self.max)
        lo = min(self.min, self.max)
        step = max(1, abs(self.step))
        return list(range(lo, hi + 1, step))


@dataclass
class PlayerTemplate:
    directions: list[str]
    actions: list[ActionName]
    walk_frames: RangeSpec
    pre_button_frames: RangeSpec
    button_timing: RangeSpec
    buttons: list[str]
    press_frames: RangeSpec


@dataclass
class SweepRules:
    fps: float = 120.0
    repeats: int = 1
    settle_frames: int = 10
    pause_between_attempts_frames: int = 15
    save_generated_sequences: bool = True
    winner_mode: str = "manual"


@dataclass
class SweepConfig:
    p1: PlayerTemplate
    p2: PlayerTemplate
    rules: SweepRules


@dataclass
class SweepAttempt:
    index: int
    params: dict[str, Any]
    input_json_path: str | None = None
    video_path: str | None = None
    winner: Winner = "unknown"
    note: str = ""


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SweepRunner:
    def __init__(self, client: MoonlightClient, recorder: AttemptRecorder, detector: WinnerDetector, outputs_dir: Path, reset_sequence_loader: Callable[[], dict[str, Any] | None], publish: Callable[[dict[str, Any]], None], save_sequences_default: bool = True):
        self._client = client
        self._recorder = recorder
        self._detector = detector
        self._outputs_dir = outputs_dir
        self._reset_sequence_loader = reset_sequence_loader
        self._publish = publish
        self._save_sequences_default = save_sequences_default

        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._state: dict[str, Any] = {"running": False, "paused": False, "run_id": None, "total": 0, "current": 0, "current_params": None, "pending_judgement": None, "finished": False, "started_at": None, "ended_at": None, "error": None}
        self._results: list[SweepAttempt] = []
        self._stop_flag = False
        self._skip_flag = False
        self._pause_cond = threading.Condition(self._lock)
        self._judge_cond = threading.Condition(self._lock)

    def status(self) -> dict[str, Any]:
        with self._lock:
            st = dict(self._state)
            st["results_count"] = len(self._results)
            return st

    def results(self) -> list[dict[str, Any]]:
        with self._lock:
            return [asdict(row) for row in self._results]

    def start(self, config: SweepConfig) -> dict[str, Any]:
        with self._lock:
            if self._state["running"]:
                raise RuntimeError("sweep already running")
            self._stop_flag = False
            self._skip_flag = False
            self._results = []
            run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            self._state.update({"running": True, "paused": False, "run_id": run_id, "total": self._count_cases(config), "current": 0, "current_params": None, "pending_judgement": None, "finished": False, "started_at": _iso_now(), "ended_at": None, "error": None})
            self._thread = threading.Thread(target=self._run, args=(run_id, config), daemon=True)
            self._thread.start()
            self._publish({"type": "sweep_started", "status": self.status()})
            return self.status()

    def stop(self) -> dict[str, Any]:
        with self._lock:
            self._stop_flag = True
            self._pause_cond.notify_all()
            self._judge_cond.notify_all()
        return self.status()

    def pause(self) -> dict[str, Any]:
        with self._lock:
            self._state["paused"] = True
            self._publish({"type": "sweep_paused", "status": self.status()})
            return self.status()

    def resume(self) -> dict[str, Any]:
        with self._lock:
            self._state["paused"] = False
            self._pause_cond.notify_all()
            self._publish({"type": "sweep_resumed", "status": self.status()})
            return self.status()

    def skip_current(self) -> dict[str, Any]:
        with self._lock:
            self._skip_flag = True
            self._judge_cond.notify_all()
            self._publish({"type": "sweep_skip_requested", "status": self.status()})
            return self.status()

    def judge_pending(self, winner: Winner, note: str = "") -> dict[str, Any]:
        with self._lock:
            pending = self._state.get("pending_judgement")
            if pending is None:
                raise RuntimeError("no pending attempt to judge")
            pending["winner"] = winner
            pending["note"] = note
            self._judge_cond.notify_all()
            return self.status()

    def _count_cases(self, config: SweepConfig) -> int:
        p1, p2 = config.p1, config.p2
        p1_counts = [
            len(p1.directions),
            len(p1.actions),
            len(p1.walk_frames.values()),
            len(p1.pre_button_frames.values()),
            len(p1.buttons),
            len(p1.press_frames.values()),
        ]
        p2_counts = [
            len(p2.directions),
            len(p2.actions),
            len(p2.walk_frames.values()),
            len(p2.pre_button_frames.values()),
            len(p2.button_timing.values()),
            len(p2.buttons),
            len(p2.press_frames.values()),
        ]
        counts = [*p1_counts, *p2_counts, max(1, config.rules.repeats)]
        total = 1
        for c in counts:
            total *= max(1, c)
        return total

    def _run(self, run_id: str, config: SweepConfig) -> None:
        try:
            run_dir = self._outputs_dir / run_id
            run_dir.mkdir(parents=True, exist_ok=True)
            attempts = self._iter_attempts(config)
            for idx, params in enumerate(attempts, start=1):
                if self._should_stop():
                    break
                self._wait_if_paused_or_stop()
                if self._should_stop():
                    break

                with self._lock:
                    self._state["current"] = idx
                    self._state["current_params"] = params
                self._publish({"type": "sweep_progress", "status": self.status()})

                reset = self._reset_sequence_loader()
                if reset is not None:
                    self._client.request({"op": "PLAY", "fps": config.rules.fps, "shift_frames": {"0": 0, "1": 0}, "seq": reset})
                    self._sleep_frames(config.rules.settle_frames, config.rules.fps)

                seq = self._build_sequence(params, config.rules.fps)
                attempt = SweepAttempt(index=idx, params=params)

                if config.rules.save_generated_sequences and self._save_sequences_default:
                    seq_path = run_dir / f"{idx:05d}.json"
                    seq_path.write_text(json.dumps(seq, indent=2), encoding="utf-8")
                    attempt.input_json_path = str(seq_path)

                video_path: Path | None = None
                if self._recorder.enabled:
                    video_path = run_dir / f"{idx:05d}.mp4"
                    self._recorder.start(video_path)
                    attempt.video_path = str(video_path)

                self._client.request({"op": "PLAY", "fps": config.rules.fps, "shift_frames": {"0": 0, "1": 0}, "seq": seq})
                self._sleep_frames(self._sequence_duration_frames(seq) + config.rules.pause_between_attempts_frames, config.rules.fps)
                self._client.request({"op": "STOP"})

                if self._recorder.enabled:
                    self._recorder.stop()

                if config.rules.winner_mode == "auto" and video_path is not None:
                    attempt.winner = self._detector.detect(video_path)
                else:
                    verdict = self._wait_manual_judgement(attempt)
                    if verdict is None:
                        attempt.winner = "unknown"
                    else:
                        attempt.winner = verdict["winner"]
                        attempt.note = verdict.get("note", "")

                if self._skip_flag:
                    self._skip_flag = False
                    attempt.note = (attempt.note + " | skipped").strip(" |")

                with self._lock:
                    self._results.append(attempt)
                self._publish({"type": "sweep_attempt_done", "attempt": asdict(attempt), "status": self.status()})
        except Exception as exc:
            with self._lock:
                self._state["error"] = str(exc)
            self._publish({"type": "sweep_error", "error": str(exc), "status": self.status()})
        finally:
            self._recorder.stop()
            with self._lock:
                self._state.update({"running": False, "paused": False, "finished": True, "ended_at": _iso_now(), "pending_judgement": None})
            self._publish({"type": "sweep_finished", "status": self.status(), "results_count": len(self._results)})

    def _wait_manual_judgement(self, attempt: SweepAttempt) -> dict[str, Any] | None:
        with self._lock:
            self._state["pending_judgement"] = {"index": attempt.index, "params": attempt.params, "winner": None, "note": ""}
            self._publish({"type": "sweep_judgement_required", "status": self.status()})
            while True:
                if self._stop_flag or self._skip_flag:
                    self._state["pending_judgement"] = None
                    return None
                pending = self._state["pending_judgement"]
                if pending is not None and pending.get("winner"):
                    verdict = dict(pending)
                    self._state["pending_judgement"] = None
                    return verdict
                self._judge_cond.wait(timeout=0.25)

    def _iter_attempts(self, config: SweepConfig):
        p1, p2, rules = config.p1, config.p2, config.rules
        for repeat in range(max(1, rules.repeats)):
            product = itertools.product(
                p1.directions,
                p1.actions,
                p1.walk_frames.values(),
                p1.pre_button_frames.values(),
                p1.buttons,
                p1.press_frames.values(),
                p2.directions,
                p2.actions,
                p2.walk_frames.values(),
                p2.pre_button_frames.values(),
                p2.button_timing.values(),
                p2.buttons,
                p2.press_frames.values(),
            )
            for values in product:
                (p1_dir, p1_action, p1_walk, p1_pre, p1_button, p1_press, p2_dir, p2_action, p2_walk, p2_pre, p2_button_timing, p2_button, p2_press) = values
                yield {
                    "repeat": repeat,
                    "p1": {"direction": p1_dir, "action": p1_action, "walk_frames": p1_walk, "pre_button_frames": p1_pre, "button": p1_button, "press_frames": p1_press},
                    "p2": {"direction": p2_dir, "action": p2_action, "walk_frames": p2_walk, "pre_button_frames": p2_pre, "button_timing": p2_button_timing, "button": p2_button, "press_frames": p2_press},
                }

    def _build_sequence(self, params: dict[str, Any], fps: float) -> dict[str, Any]:
        events: list[dict[str, Any]] = []
        p1, p2 = params["p1"], params["p2"]
        self._append_player_events(events, 0, p1["direction"], p1["action"], p1["walk_frames"], p1["pre_button_frames"], p1["button"], p1["press_frames"], p2_button_time=None)
        self._append_player_events(events, 1, p2["direction"], p2["action"], p2["walk_frames"], p2["pre_button_frames"], p2["button"], p2["press_frames"], p2_button_time=p2["button_timing"])
        events.sort(key=lambda e: (int(e["t"]), int(e["pad"])))
        return {"mode": "events", "fps": fps, "events": events}

    def _append_player_events(self, events: list[dict[str, Any]], pad: int, direction: str, action: str, walk_frames: int, pre_button_frames: int, button: str, press_frames: int, p2_button_time: int | None) -> None:
        t = 0
        initial_buttons = self._direction_to_buttons(direction, pad)
        if initial_buttons:
            events.append({"t": t, "pad": pad, "down": initial_buttons})
        t += max(0, walk_frames)
        if initial_buttons:
            events.append({"t": t, "pad": pad, "up": initial_buttons})

        action_buttons, action_hold = self._action_to_buttons(action, pad)
        if action_buttons:
            events.append({"t": t, "pad": pad, "down": action_buttons})
            events.append({"t": t + action_hold, "pad": pad, "up": action_buttons})
        t += action_hold
        t += max(0, pre_button_frames)

        button_t = max(0, p2_button_time) if p2_button_time is not None else t
        events.append({"t": button_t, "pad": pad, "down": [button]})
        events.append({"t": button_t + max(1, press_frames), "pad": pad, "up": [button]})

    @staticmethod
    def _direction_to_buttons(direction: str, pad: int) -> list[str]:
        d = direction.upper().strip()
        if d == "FORWARD":
            return ["RIGHT"] if pad == 0 else ["LEFT"]
        if d == "BACK":
            return ["LEFT"] if pad == 0 else ["RIGHT"]
        mapping = {
            "UP": ["UP"], "DOWN": ["DOWN"], "LEFT": ["LEFT"], "RIGHT": ["RIGHT"],
            "UP_LEFT": ["UP", "LEFT"], "UP_RIGHT": ["UP", "RIGHT"], "DOWN_LEFT": ["DOWN", "LEFT"], "DOWN_RIGHT": ["DOWN", "RIGHT"],
        }
        return mapping.get(d, [])

    @staticmethod
    def _action_to_buttons(action: str, pad: int) -> tuple[list[str], int]:
        a = action.lower().strip()
        fwd, back = ("RIGHT", "LEFT") if pad == 0 else ("LEFT", "RIGHT")
        action_map: dict[str, tuple[list[str], int]] = {
            "none": ([], 0),
            "walk_forward": ([fwd], 5),
            "walk_back": ([back], 5),
            "jump_forward": (["UP", fwd], 4),
            "jump_neutral": (["UP"], 4),
            "jump_back": (["UP", back], 4),
            "dash_forward": ([fwd], 2),
            "dash_back": ([back], 2),
        }
        return action_map.get(a, ([], 0))

    @staticmethod
    def _sequence_duration_frames(seq: dict[str, Any]) -> int:
        mx = 0
        for ev in seq.get("events", []):
            mx = max(mx, int(ev.get("t", 0)))
        return mx + 2

    @staticmethod
    def _sleep_frames(frames: int, fps: float) -> None:
        if frames > 0:
            time.sleep(float(frames) / max(1.0, fps))

    def _should_stop(self) -> bool:
        with self._lock:
            return self._stop_flag

    def _wait_if_paused_or_stop(self) -> None:
        with self._lock:
            while self._state["paused"] and not self._stop_flag:
                self._pause_cond.wait(timeout=0.25)
