# Solución a `prompt1.md` — Banco de pruebas de inputs frame-precisos para *City of the Wolves* sobre Moonlight-Qt

## 0. TL;DR

Construir, dentro de Moonlight-Qt, un **inyector de inputs sintéticos** que conviva con el `SdlInputHandler` y emita eventos directamente al stack `LiSendMultiControllerEvent` / `LiSendKeyboardEvent2` con timing alineado al video del host. La "lógica de qué inputs mandar" vive fuera del binario, en un proceso externo (Python recomendado), y se comunica con Moonlight por un **socket TCP loopback línea-a-línea** (más simple y robusto que stdin, más liviano que un servidor HTTP). Cada mensaje nuevo **reemplaza** la cola anterior (semántica *preempt*). Los "controles virtuales desde celular" son un *use case* aparte y no se mezclan con el experimento.

---

## 1. Lectura del prompt y supuestos

Citas literales del prompt y mi interpretación:

| Cita | Interpretación / supuesto |
|---|---|
| "experimentar en *City of the Wolves*" | Es un fighting game de SNK. La ventana de timing relevante es **1 frame ≈ 16.67 ms a 60 fps** o **8.33 ms a 120 fps**. Asumo que el host corre el juego y Moonlight lo recibe. |
| "mandar inputs tanto para P1 como para P2" | **Asumo dos gamepads virtuales emitidos por el mismo cliente Moonlight** vía `LiSendMultiControllerEvent` con `controllerNumber=0` y `controllerNumber=1`. Esto ya está soportado por `MAX_GAMEPADS=16` y el modo multi-controller (ver [app/streaming/input/input.h](app/streaming/input/input.h#L73-L74) y [app/streaming/input/gamepad.cpp](app/streaming/input/gamepad.cpp#L378)). |
| "recibir cadenas de inputs proactivamente con poco retraso" | Latencia objetivo de **un sub-frame** entre que la cadena llega al cliente y se inyecta al pipeline (<1 ms). El delay extra dominante seguirá siendo el de red Moonlight host↔cliente, que no se puede bajar desde aquí. |
| "al menos 5 segundos a 120 fps" | **≥ 600 frames** por jugador. Asumo guion en formato denso (un slot por frame) o disperso (eventos con timestamp). Soporto ambos. |
| "cambiar perillas de frames, hacer cosas un par de frames antes/después" | Necesito **offsets de timing por jugador y por evento** y la posibilidad de re-disparar la misma secuencia con shift `Δ ∈ {-3, -2, -1, 0, +1, +2, +3}` frames sin reescribirla. |
| "lógica fuera de Moonlight... webserver pequeño o stdin" | Compararé tres transports y recomendaré uno. |
| "cuando reciba una cadena nueva, la nueva se superpone a la vieja, la vieja no se sigue ejecutando" | Semántica **preempt total**: al recibir `PLAY`, cancelo la secuencia activa, libero todos los botones (estado neutro garantizado), y arranco la nueva. |
| "controles virtuales desde celular para P1 y P2" | Caso de uso distinto (humano-en-el-loop), no automatizado. Lo trato en sección aparte para no contaminar el banco de pruebas. |

Supuestos adicionales:

- **Solo gamepad, no teclado/mouse.** Fighting games se juegan con pad. Si más adelante hace falta teclado, la misma vía sirve con `LiSendKeyboardEvent2`.
- **Plataforma host:** indiferente. El cliente sintético solo emite eventos LiSend\*; el host ve dos gamepads "reales" gracias a Sunshine/GFE.
- **No hay submódulo `moonlight-common-c` poblado** en este workspace (ya documentado en [PLAN_INPUT_RECORDER.md](PLAN_INPUT_RECORDER.md#L226-L232)). No bloquea: integramos en Moonlight-Qt antes de las llamadas LiSend\*.
- **Sin gamepad físico requerido.** El inyector no depende de SDL; produce los mismos `MultiControllerEvent` que produciría un pad real.

---

## 2. Hallazgos en el código actual

### 2.1 Punto de inyección ideal

`SdlInputHandler::sendGamepadState()` en [app/streaming/input/gamepad.cpp](app/streaming/input/gamepad.cpp#L104) ya hace:

```cpp
LiSendMultiControllerEvent(state->index, m_GamepadMask,
                           state->buttons,
                           state->lt, state->rt,
                           state->lsX, state->lsY,
                           state->rsX, state->rsY);
```

Conclusión: **basta con poder fabricar un `GamepadState` virtual y llamar a `LiSendMultiControllerEvent` directamente**. No necesito tocar el flujo SDL.

### 2.2 Multi-controller ya disponible

- `MAX_GAMEPADS = 16` ([input.h L73](app/streaming/input/input.h#L73)).
- El `m_GamepadMask` es un bitmask: P1 = bit 0, P2 = bit 1 → mask `0x03` para los dos activos.
- Los índices 0 y 1 quedan reservados para los virtuales aunque haya pads físicos conectados (les forzamos índices 14 y 15 si conviene, o desactivamos input físico durante el experimento).

### 2.3 Plan preexistente reutilizable

[PLAN_INPUT_RECORDER.md](PLAN_INPUT_RECORDER.md) ya propone un `InputTransport` que centraliza todas las llamadas LiSend\*. **Reaprovecho ese componente** y le agrego un modo `INJECT` además de `RECORD` y `PLAYBACK`.

---

## 3. Arquitectura propuesta

```
┌───────────────────────────┐         TCP 127.0.0.1:47999          ┌─────────────────────────┐
│  Script externo (Python)  │  ◀──── línea JSON / binario ───▶    │  Moonlight-Qt           │
│  - lee guiones .mlseq     │                                       │  ┌───────────────────┐  │
│  - aplica frame-shift     │                                       │  │ InputInjector     │  │
│  - encola y envía PLAY    │                                       │  │  - cola preempt   │  │
│  - REST/CLI a gusto       │                                       │  │  - scheduler 1ms  │  │
└───────────────────────────┘                                       │  └─────────┬─────────┘  │
                                                                    │            ▼            │
                                                                    │  InputTransport         │
                                                                    │            ▼            │
                                                                    │  LiSendMultiController* │
                                                                    └─────────────────────────┘
```

### 3.1 Componentes nuevos en Moonlight-Qt

| Archivo | Responsabilidad |
|---|---|
| `app/streaming/input/inputtransport.{h,cpp}` | Wrapper único sobre LiSend\*. Modo `LIVE` / `INJECT` / `MIXED`. (Ya planificado.) |
| `app/streaming/input/inputinjector.{h,cpp}` | Cola de eventos con timestamp absoluto, scheduler en hilo dedicado, semántica preempt. |
| `app/streaming/input/inputcontrolserver.{h,cpp}` | Servidor TCP loopback que parsea protocolo y llama al injector. |
| `app/cli/commandlineparser.cpp` | Flags `--input-inject-port=47999`, `--input-inject-token=<hex>`, `--block-physical-input`. |

### 3.2 Componentes externos (repo separado o `tools/inputbench/`)

| Archivo | Responsabilidad |
|---|---|
| `tools/inputbench/play.py` | CLI que lee `.mlseq` y manda `PLAY` al puerto. |
| `tools/inputbench/sequences/*.mlseq` | Guiones de tests (combos, OS, frame-perfect setups). |
| `tools/inputbench/shift.py` | Aplica `Δframes` a un guion y produce variante. |

---

## 4. Comparación de transports

| Opción | Pro | Contra | Veredicto |
|---|---|---|---|
| **stdin línea-a-línea** | Cero infra. | El binario de Moonlight es GUI Qt; stdin no es confiable en Windows con GUI. Difícil "preempt" si el productor está bloqueado. | Descartado. |
| **HTTP REST** | Familiar, multilenguaje. | Overhead por request, no full-duplex, peor para *push* del cliente al script (telemetría). | Solo si después se quiere UI web. |
| **WebSocket** | Bidireccional, framed. | Necesita lib extra en C++. | Buena, pero overkill para v1. |
| **TCP loopback line-delimited (recomendado)** | Trivial con `QTcpServer`, full-duplex, sub-ms, framing simple por `\n`. | Hay que inventar un mini-protocolo (5 verbos). | **Elegido.** |
| **UDP loopback** | Mínima latencia. | Sin garantías de orden ni entrega — peligroso para `PLAY/STOP`. | Descartado. |
| **Pipe nombrado de Windows** | Rápido, autenticable. | No portable. | Descartado. |

**Decisión:** TCP en `127.0.0.1`, puerto configurable (default 47999), token de 32 bytes hex obligatorio en el handshake (defensa OWASP A07: el puerto local podría ser leído por otro proceso del mismo usuario).

---

## 5. Protocolo del puerto de control

Texto, una línea = un mensaje, terminada en `\n`. JSON compacto.

### 5.1 Handshake

```
→ {"op":"HELLO","token":"<hex64>","ver":1}
← {"op":"OK","fps":120,"controllers":[0,1]}
```

Si el token no coincide, el server cierra. Si Moonlight no está en sesión activa, responde `{"op":"ERR","msg":"NO_SESSION"}`.

### 5.2 Comandos

| `op` | Payload | Semántica |
|---|---|---|
| `PLAY` | `{"seq":[...], "shift_frames":{"0":-1,"1":0}, "fps":120}` | **Cancela** lo que esté reproduciéndose, libera ambos pads a neutro durante 1 frame, encola y arranca. |
| `STOP` | `{}` | Cancela todo y deja pads neutros. |
| `PAUSE` / `RESUME` | `{}` | Útil para depurar. |
| `HOLD` | `{"pad":0,"buttons":["A","DOWN"]}` | Mantiene un estado fijo (sandbox manual). Se cancela con `STOP` o nuevo `PLAY`. |
| `STATUS` | `{}` | Devuelve frame actual, longitud restante, drift μs. |

### 5.3 Formato de `seq`

Dos modos, ambos aceptados:

**Modo denso (un slot por frame):**

```json
{"mode":"dense","fps":120,"frames":[
  {"0":{"b":["DOWN"],          "lx":0,"ly":-32000},
   "1":{"b":[],                "lx":0,"ly":0}},
  {"0":{"b":["DOWN","RIGHT"],  "lx":22000,"ly":-22000},
   "1":{"b":["A"]}},
  ...
]}
```

**Modo evento (cambios solo):**

```json
{"mode":"events","fps":120,"events":[
  {"t":0,  "pad":0,"down":["DOWN"]},
  {"t":2,  "pad":0,"down":["RIGHT"]},
  {"t":3,  "pad":0,"up":["DOWN"]},
  {"t":4,  "pad":0,"down":["A"], "up":["RIGHT"]},
  {"t":120,"pad":1,"down":["A"]}
]}
```

Donde `t` está en **frames** del `fps` declarado. Internamente se traduce a `int64 deadline_us = t_start_us + t * (1e6/fps) + shift_frames[pad]*(1e6/fps)`.

### 5.4 Mapeo de nombres de botones

Strings → flags de `MultiControllerEvent`. Tabla en `inputinjector.cpp`:

```
A→A_FLAG, B→B_FLAG, X→X_FLAG, Y→Y_FLAG,
UP→UP_FLAG, DOWN→DOWN_FLAG, LEFT→LEFT_FLAG, RIGHT→RIGHT_FLAG,
LB→LB_FLAG, RB→RB_FLAG, LS→LS_CLK_FLAG, RS→RS_CLK_FLAG,
BACK→BACK_FLAG, START→PLAY_FLAG, GUIDE→SPECIAL_FLAG
```

Triggers como int 0..255 con keys `lt`,`rt`. Sticks como int -32768..32767 con `lx,ly,rx,ry`.

---

## 6. Scheduler frame-preciso

### 6.1 Por qué un hilo dedicado

El loop principal de Qt mezcla rendering, eventos SDL y red. Un `QTimer` de 1 ms tiene jitter ≥ 5–15 ms en Windows. Inaceptable a 120 fps.

### 6.2 Implementación

```cpp
// inputinjector.cpp (esqueleto)
void InputInjector::run() {
    using clk = std::chrono::steady_clock;
    timeBeginPeriod(1);              // Windows: bajar quantum
    while (!m_stop.load()) {
        auto now = clk::now();
        Event ev;
        if (!m_queue.peek(ev)) {
            m_cv.wait_for(lock, std::chrono::milliseconds(2));
            continue;
        }
        auto delay = ev.deadline - now;
        if (delay > std::chrono::microseconds(1500)) {
            m_cv.wait_for(lock, delay - std::chrono::microseconds(500));
            continue;                // re-check deadline tras dormir
        }
        // busy-wait final < 1.5 ms para precisión sub-frame
        while (clk::now() < ev.deadline) { /* spin */ }
        m_queue.pop();
        applyEvent(ev);              // → InputTransport → LiSendMulti...
    }
    timeEndPeriod(1);
}
```

Drift esperado: **< 200 μs** en escritorio Windows con `timeBeginPeriod(1)`. Más que suficiente para precisión de 1 frame a 120 fps (8333 μs).

### 6.3 Preempt

```cpp
void InputInjector::play(Sequence seq) {
    {
        std::lock_guard g(m_mtx);
        m_queue.clear();
        // inserta evento NEUTRAL inmediato (todos botones a 0, sticks 0)
        m_queue.push(neutralEvent(/*pad=*/0, now));
        m_queue.push(neutralEvent(/*pad=*/1, now));
        // luego la nueva secuencia, alineada al próximo frame
        scheduleSequence(seq, now + oneFrame());
    }
    m_cv.notify_all();
}
```

**Garantía:** entre la secuencia vieja y la nueva siempre hay 1 frame de neutro, evitando combos basura por superposición.

---

## 7. Frame-shift sin reescribir guion

Cada `PLAY` acepta `shift_frames` por pad. El injector calcula:

```
deadline_pad_i = base_t + (event.t + shift_frames[i]) * frame_us
```

`shift_frames` puede ser negativo (adelantar): se descuenta del `base_t`, pero **nunca por debajo de `now+1ms`**; si el shift negativo cae en el pasado, se dispara inmediato y se loguea `WARN: shift truncated`.

Esto cubre el "hacer cosas un par de frames antes o después" del prompt sin tocar la secuencia base. Para barrido sistemático (`Δ ∈ {-3..+3}`), el script externo lanza 7 PLAYs con `STOP` + reset de juego entre cada uno.

---

## 8. ¿Y los "controles virtuales desde el celular"?

Es un caso **distinto** al banco de pruebas:

- **Banco de pruebas** (objetivo principal del prompt): determinismo, sub-frame, 0% input humano.
- **Pad virtual desde celular**: usabilidad, latencia humana ya domina (>50 ms).

Recomendación: **no mezclarlos en v1.** Para el segundo caso ya existen apps tipo Steam Link / DS4Windows / vJoy / *Mobile Gamepad* que crean un pad HID en el host. Moonlight no necesita cambios: si el host ve dos pads HID, los reenvía al juego. La única integración valiosa dentro de Moonlight sería montar una **PWA** servida en `127.0.0.1:8080` con dos paneles (P1/P2) que mande mensajes por el mismo `inputcontrolserver`. Eso reutiliza toda la infra del injector. Lo dejo como **fase 3**.

---

## 9. Plan de implementación por fases

### Fase 0 — Preparación (no escribe código del injector)
- [ ] Confirmar que el host expone Sunshine con soporte multi-controller.
- [ ] Snapshot de [PLAN_INPUT_RECORDER.md](PLAN_INPUT_RECORDER.md): el `InputTransport` se hace **antes** que el injector porque el injector lo usa.

### Fase 1 — Injector mínimo (CLI-only, P1 solo)
1. Crear `InputTransport` (centralizar LiSend\*).
2. Crear `InputInjector` con scheduler y cola preempt.
3. Crear `InputControlServer` TCP loopback con auth por token.
4. Flag CLI `--input-inject-port=N --input-inject-token=...`.
5. Probar `HOLD pad=0 buttons=[A]` y verificar en el host.

### Fase 2 — Dos pads + secuencias densas/eventos
6. Habilitar pad 1.
7. Implementar parser de `seq` denso y por eventos.
8. Implementar `shift_frames` por pad.
9. Script `tools/inputbench/play.py` con `argparse`.

### Fase 3 — Calidad
10. `STATUS` con drift y conteo de eventos.
11. Bloqueo de input físico (`--block-physical-input` desactiva `SdlInputHandler` para gamepads, no para combos de salida).
12. Logging CSV de cada evento aplicado (timestamp real vs deadline).
13. (Opcional) PWA en celular reutilizando el control server.

---

## 10. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Jitter de scheduler en Windows > 1 frame | `timeBeginPeriod(1)` + busy-wait final < 1.5 ms. Medir y reportar drift en `STATUS`. |
| Drop de paquetes UDP de Moonlight host↔cliente | Fuera de nuestro control. Documentar que el banco mide *pipeline cliente*, no host. Para validar host, comparar grabación de video del juego vs deadlines. |
| Pads físicos interfieren | Flag `--block-physical-input` que pone `m_GamepadMask &= ~0x03` o ignora SDL_CONTROLLER\* events para índices 0/1. |
| Secuencias muy largas (>10 min) llenan RAM | Modo *streaming*: el script externo manda `APPEND` cada N frames en vez de un `PLAY` gigante. |
| Token filtrado → otro proceso local inyecta inputs | Token efímero generado al arrancar Moonlight, mostrado solo en stdout/log con permisos del usuario. Rotación al reiniciar. |
| Reconexión Moonlight (host se cae) | Server emite `{"op":"EVT","kind":"SESSION_LOST"}`. El script decide si reintentar. |

---

## 11. Ejemplo end-to-end

### Guion `tools/inputbench/sequences/qcf_p1_punish.mlseq`

```json
{"mode":"events","fps":120,"events":[
  {"t":0,  "pad":0,"down":["DOWN"]},
  {"t":3,  "pad":0,"down":["RIGHT"]},
  {"t":4,  "pad":0,"up":["DOWN"]},
  {"t":6,  "pad":0,"down":["A"], "up":["RIGHT"]},
  {"t":10, "pad":0,"up":["A"]}
]}
```

### Disparo desde el script

```bash
python tools/inputbench/play.py \
    --port 47999 --token $MOONLIGHT_INJECT_TOKEN \
    --shift-pad0 -2 \
    sequences/qcf_p1_punish.mlseq
```

### Lo que ocurre dentro de Moonlight

1. `InputControlServer` recibe `PLAY`.
2. `InputInjector::play()` limpia cola, encola NEUTRAL para pad 0, luego 5 eventos con deadlines `now + (t-2)*8333μs`.
3. Hilo scheduler despierta, dispara `LiSendMultiControllerEvent` para pad 0 cuando toca.
4. Pad 1 nunca se toca (sigue neutro).
5. El host ve un movimiento qcf+A sin jitter humano.

---

## 12. Lo que NO se hace (fuera de alcance v1)

- Reconocimiento de imagen del juego para *closed-loop* (reaccionar a hitconfirm).
- Sincronización con audio del host.
- Re-grabar inputs reales (eso vive en `InputRecorder`, fase distinta del plan original).
- UI dentro de Moonlight para editar guiones (usar editor externo + script).

---

## 13. Resumen ejecutivo de decisiones

1. **Transport:** TCP loopback line-delimited JSON con token. Stdin/HTTP descartados.
2. **Punto de inyección:** justo antes de `LiSendMultiControllerEvent`, vía `InputTransport`.
3. **Dos jugadores:** dos índices del multi-controller existente, sin tocar SDL.
4. **Frame-shift:** parámetro por `PLAY`, no edición de guion.
5. **Preempt:** la nueva secuencia limpia la cola y mete 1 frame neutro.
6. **Scheduler:** hilo propio + `timeBeginPeriod(1)` + busy-wait final.
7. **Celular como gamepad:** caso aparte, fase 3, reutilizando el mismo control server.

