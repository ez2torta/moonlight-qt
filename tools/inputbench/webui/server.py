from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from moonlight_client import MoonlightClient, MoonlightConnectionConfig
from recorder import AttemptRecorder, RecorderConfig
from sweep import PlayerTemplate, RangeSpec, SweepConfig, SweepRules, SweepRunner
from winner_detector import WinnerDetector, WinnerDetectorConfig

ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
CONFIG_PATH = ROOT / "config.json"


def _merge(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    out = dict(a)
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def _load_config() -> dict[str, Any]:
    base = json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))
    if CONFIG_PATH.exists():
        user = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        base = _merge(base, user)
    return base


CONFIG = _load_config()

MOONLIGHT = MoonlightClient(
    MoonlightConnectionConfig(
        host=str(CONFIG["moonlight"]["host"]),
        port=int(CONFIG["moonlight"]["port"]),
        token=str(CONFIG["moonlight"]["token"]),
        timeout_sec=float(CONFIG["moonlight"].get("timeout_sec", 5.0)),
    )
)
RECORDER = AttemptRecorder(
    RecorderConfig(
        enabled=bool(CONFIG.get("recorder", {}).get("enabled", False)),
        command=CONFIG.get("recorder", {}).get("command"),
    )
)
winner_cfg = CONFIG.get("winner_detector", {})
winner_roi = winner_cfg.get("roi", {})
WINNER_DETECTOR = WinnerDetector(
    WinnerDetectorConfig(
        mode=str(winner_cfg.get("mode", "manual")),
        template_dir=str((ROOT / str(winner_cfg.get("template_dir", "./templates"))).resolve()),
        roi_enabled=bool(winner_roi.get("enabled", False)),
        roi_p1=tuple(winner_roi.get("p1", [0, 0, 0, 0])),
        roi_p2=tuple(winner_roi.get("p2", [0, 0, 0, 0])),
    )
)
OUTPUTS_DIR = (ROOT / str(CONFIG.get("outputs_dir", "../sweeps"))).resolve()
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
RESET_SEQUENCE_PATH = (ROOT / str(CONFIG.get("reset_sequence", "../sequences/reset_training.json"))).resolve()


class BroadcastHub:
    def __init__(self):
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._clients.add(ws)

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(ws)

    async def broadcast(self, msg: dict[str, Any]) -> None:
        async with self._lock:
            clients = list(self._clients)
        for ws in clients:
            try:
                await ws.send_json(msg)
            except Exception:
                await self.disconnect(ws)


HUB = BroadcastHub()
APP_LOOP: asyncio.AbstractEventLoop | None = None


def _publish_from_thread(msg: dict[str, Any]) -> None:
    if APP_LOOP is None:
        return
    asyncio.run_coroutine_threadsafe(HUB.broadcast(msg), APP_LOOP)


def _load_reset_sequence() -> dict[str, Any] | None:
    if not RESET_SEQUENCE_PATH.exists():
        return None
    return json.loads(RESET_SEQUENCE_PATH.read_text(encoding="utf-8"))


SWEEP = SweepRunner(client=MOONLIGHT, recorder=RECORDER, detector=WINNER_DETECTOR, outputs_dir=OUTPUTS_DIR, reset_sequence_loader=_load_reset_sequence, publish=_publish_from_thread, save_sequences_default=bool(CONFIG.get("save_generated_sequences", True)))


@asynccontextmanager
async def lifespan(_: FastAPI):
    global APP_LOOP
    APP_LOOP = asyncio.get_running_loop()
    try:
        yield
    finally:
        APP_LOOP = None
        try:
            SWEEP.stop()
        except Exception:
            pass
        RECORDER.stop()
        MOONLIGHT.close()


app = FastAPI(title="Moonlight InputBench WebUI", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def _auth_pin() -> str:
    return str(CONFIG.get("auth_pin", ""))


async def require_auth(x_auth: str | None = Header(default=None, alias="X-Auth"), auth: str | None = Query(default=None)) -> None:
    pin = _auth_pin()
    if not pin:
        return
    if x_auth == pin or auth == pin:
        return
    raise HTTPException(status_code=401, detail="unauthorized")


class HoldRequest(BaseModel):
    pad: int = Field(ge=0, le=1)
    b: list[str] = Field(default_factory=list)
    lx: int | None = None
    ly: int | None = None
    rx: int | None = None
    ry: int | None = None
    lt: int | None = Field(default=None, ge=0, le=255)
    rt: int | None = Field(default=None, ge=0, le=255)


class PlayRequest(BaseModel):
    fps: float | None = None
    shift_frames: dict[str, int] = Field(default_factory=lambda: {"0": 0, "1": 0})
    seq: dict[str, Any]


class ResetRequest(BaseModel):
    use_default: bool = True


class RangeBody(BaseModel):
    min: int
    max: int
    step: int = 1


class PlayerTemplateBody(BaseModel):
    directions: list[str]
    actions: list[str]
    walk_frames: RangeBody
    pre_button_frames: RangeBody
    button_timing: RangeBody
    buttons: list[str]
    press_frames: RangeBody


class SweepRulesBody(BaseModel):
    fps: float = 120.0
    repeats: int = 1
    settle_frames: int = 10
    pause_between_attempts_frames: int = 15
    save_generated_sequences: bool = True
    winner_mode: str = "manual"


class SweepStartRequest(BaseModel):
    p1: PlayerTemplateBody
    p2: PlayerTemplateBody
    rules: SweepRulesBody


class JudgeRequest(BaseModel):
    winner: str
    note: str = ""


@app.get("/")
async def root() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/live")
async def live_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "live.html")


@app.get("/sweep")
async def sweep_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "sweep.html")


@app.get("/api/config")
async def api_config(_: None = Depends(require_auth)) -> dict[str, Any]:
    return {"default_fps": CONFIG.get("default_fps", 120), "button_labels": CONFIG.get("button_labels", {}), "recorder_enabled": RECORDER.enabled, "winner_mode": CONFIG.get("winner_detector", {}).get("mode", "manual")}


@app.get("/api/ping")
async def api_ping(_: None = Depends(require_auth)) -> dict[str, Any]:
    return await asyncio.to_thread(MOONLIGHT.request, {"op": "PING"})


@app.get("/api/status")
async def api_status(_: None = Depends(require_auth)) -> dict[str, Any]:
    return await asyncio.to_thread(MOONLIGHT.request, {"op": "STATUS"})


@app.post("/api/stop")
async def api_stop(_: None = Depends(require_auth)) -> dict[str, Any]:
    return await asyncio.to_thread(MOONLIGHT.request, {"op": "STOP"})


@app.post("/api/hold")
async def api_hold(req: HoldRequest, _: None = Depends(require_auth)) -> dict[str, Any]:
    payload = {"op": "HOLD", "pad": req.pad, "b": req.b}
    for k in ("lx", "ly", "rx", "ry", "lt", "rt"):
        v = getattr(req, k)
        if v is not None:
            payload[k] = v
    return await asyncio.to_thread(MOONLIGHT.request, payload)


@app.post("/api/play")
async def api_play(req: PlayRequest, _: None = Depends(require_auth)) -> dict[str, Any]:
    fps = req.fps if req.fps is not None else float(req.seq.get("fps", CONFIG.get("default_fps", 120)))
    payload = {"op": "PLAY", "fps": fps, "shift_frames": req.shift_frames, "seq": req.seq}
    return await asyncio.to_thread(MOONLIGHT.request, payload)


@app.post("/api/reset-training")
async def api_reset_training(req: ResetRequest, _: None = Depends(require_auth)) -> dict[str, Any]:
    path = RESET_SEQUENCE_PATH
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"reset sequence not found: {path}")
    seq = json.loads(path.read_text(encoding="utf-8"))
    return await asyncio.to_thread(MOONLIGHT.request, {"op": "PLAY", "fps": float(seq.get("fps", CONFIG.get("default_fps", 120))), "shift_frames": {"0": 0, "1": 0}, "seq": seq})


@app.post("/api/sweep/start")
async def api_sweep_start(req: SweepStartRequest, _: None = Depends(require_auth)) -> dict[str, Any]:
    cfg = SweepConfig(
        p1=PlayerTemplate(directions=req.p1.directions, actions=req.p1.actions, walk_frames=RangeSpec(**req.p1.walk_frames.model_dump()), pre_button_frames=RangeSpec(**req.p1.pre_button_frames.model_dump()), button_timing=RangeSpec(**req.p1.button_timing.model_dump()), buttons=req.p1.buttons, press_frames=RangeSpec(**req.p1.press_frames.model_dump())),
        p2=PlayerTemplate(directions=req.p2.directions, actions=req.p2.actions, walk_frames=RangeSpec(**req.p2.walk_frames.model_dump()), pre_button_frames=RangeSpec(**req.p2.pre_button_frames.model_dump()), button_timing=RangeSpec(**req.p2.button_timing.model_dump()), buttons=req.p2.buttons, press_frames=RangeSpec(**req.p2.press_frames.model_dump())),
        rules=SweepRules(**req.rules.model_dump()),
    )
    return await asyncio.to_thread(SWEEP.start, cfg)


@app.post("/api/sweep/stop")
async def api_sweep_stop(_: None = Depends(require_auth)) -> dict[str, Any]:
    return await asyncio.to_thread(SWEEP.stop)


@app.post("/api/sweep/pause")
async def api_sweep_pause(_: None = Depends(require_auth)) -> dict[str, Any]:
    return await asyncio.to_thread(SWEEP.pause)


@app.post("/api/sweep/resume")
async def api_sweep_resume(_: None = Depends(require_auth)) -> dict[str, Any]:
    return await asyncio.to_thread(SWEEP.resume)


@app.post("/api/sweep/skip")
async def api_sweep_skip(_: None = Depends(require_auth)) -> dict[str, Any]:
    return await asyncio.to_thread(SWEEP.skip_current)


@app.get("/api/sweep/status")
async def api_sweep_status(_: None = Depends(require_auth)) -> dict[str, Any]:
    return await asyncio.to_thread(SWEEP.status)


@app.get("/api/sweep/results")
async def api_sweep_results(_: None = Depends(require_auth)) -> dict[str, Any]:
    rows = await asyncio.to_thread(SWEEP.results)
    return {"rows": rows}


@app.get("/api/sweep/results.csv")
async def api_sweep_results_csv(_: None = Depends(require_auth)) -> PlainTextResponse:
    rows = await asyncio.to_thread(SWEEP.results)
    lines = ["index,winner,p1,p2,input_json_path,video_path,note"]
    for row in rows:
        line = ",".join(
            [
                str(row.get("index", "")),
                str(row.get("winner", "")),
                json.dumps(row.get("params", {}).get("p1", {}), separators=(",", ":")),
                json.dumps(row.get("params", {}).get("p2", {}), separators=(",", ":")),
                json.dumps(str(row.get("input_json_path", "") or "")),
                json.dumps(str(row.get("video_path", "") or "")),
                json.dumps(str(row.get("note", "") or "")),
            ]
        )
        lines.append(line)
    return PlainTextResponse("\n".join(lines), media_type="text/csv")


@app.post("/api/sweep/judge")
async def api_sweep_judge(req: JudgeRequest, _: None = Depends(require_auth)) -> dict[str, Any]:
    winner = req.winner.lower()
    if winner not in {"p1", "p2", "draw", "unknown", "repeat"}:
        raise HTTPException(status_code=400, detail="winner must be p1|p2|draw|unknown|repeat")
    if winner == "repeat":
        await asyncio.to_thread(SWEEP.skip_current)
        return {"ok": True}
    return await asyncio.to_thread(SWEEP.judge_pending, winner, req.note)


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket, auth: str | None = Query(default=None)) -> None:
    pin = _auth_pin()
    if pin and auth != pin:
        await ws.close(code=4401)
        return
    await HUB.connect(ws)
    await HUB.broadcast({"type": "ws_connected", "sweep": SWEEP.status()})
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        await HUB.disconnect(ws)
