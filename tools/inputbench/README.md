# inputbench

External tooling to drive Moonlight-Qt's input injection control server.

## Quick start

Launch Moonlight with injection enabled:

```powershell
$env:MLI_TOKEN = -join ((48..57) + (97..102) | Get-Random -Count 32 | % { [char]$_ })
.\Moonlight.exe stream `
    --input-inject-port 47999 `
    --input-inject-token $env:MLI_TOKEN `
    <host> "<app>"
```

Send a sequence:

```powershell
python tools\inputbench\play.py `
    --port 47999 `
    --token $env:MLI_TOKEN `
    tools\inputbench\sequences\qcf_p1_punish.json
```

With a frame shift (advance pad 0 by 2 frames):

```powershell
python tools\inputbench\play.py `
    --port 47999 --token $env:MLI_TOKEN `
    --shift-pad0 -2 `
    tools\inputbench\sequences\qcf_p1_punish.json
```

## Protocol

Loopback TCP, line-delimited JSON, UTF-8.

1. Client connects, sends `{"op":"HELLO","token":"...","ver":1}`.
2. Server replies `{"op":"OK","controllers":[0,1]}` on success.
3. Then any of:
   - `{"op":"PLAY","fps":120,"shift_frames":{"0":-2,"1":0},"seq":{...}}`
   - `{"op":"STOP"}`
   - `{"op":"HOLD","pad":0,"b":["DOWN","A"]}`
   - `{"op":"STATUS"}`
   - `{"op":"PING"}`

Sequences come in two modes: `dense` (one slot per frame) or `events`
(deltas only). See `sequences/*.json` for examples.

Button names: `A B X Y UP DOWN LEFT RIGHT LB RB LS RS BACK START GUIDE
MISC PADDLE1..4 TOUCHPAD`.

Stick axes: `lx ly rx ry` (-32768..32767). Triggers: `lt rt` (0..255).
