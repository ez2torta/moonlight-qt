# Input Bench — Phase 3

> Cierre de la línea de trabajo iniciada en `SOLUTION_PROMPT1.md`.
> Esta fase añade: (1) bloqueo del input físico, (2) **grabador de macros** que produce
> ficheros directamente reproducibles por el `InputInjector`, y (3) documentación
> completa del flujo de compilación / despliegue del cliente "servidor de mandos".

---

## 1. Resumen ejecutivo

Lo nuevo en Phase 3 frente a Phase 1+2:

| Componente | Archivo | Responsabilidad |
|---|---|---|
| `InputInjector::sBlockPhysical` | [app/streaming/input/inputinjector.h](app/streaming/input/inputinjector.h) | Flag atómico global. Cuando es `true`, `SdlInputHandler::sendGamepadState()` deja de llamar a `LiSendMultiControllerEvent` para mandos físicos. |
| `InputRecorder` | [app/streaming/input/inputrecorder.h](app/streaming/input/inputrecorder.h), [.cpp](app/streaming/input/inputrecorder.cpp) | Captura de los eventos físicos (post-merge, post-mouse-emulation) en un fichero JSON con el **mismo esquema** que ya consume `play.py`. Round-trip: grabar y reinyectar produce la misma secuencia. |
| Hook único | [app/streaming/input/gamepad.cpp:104](app/streaming/input/gamepad.cpp#L104) | Una sola línea `InputRecorder::tap(...)` justo después de `LiSendMultiControllerEvent`. |
| CLI flags nuevos | [app/cli/commandlineparser.cpp](app/cli/commandlineparser.cpp) | `--input-record FILE`, `--input-record-hz N` |
| Lifecycle | [app/streaming/session.cpp](app/streaming/session.cpp) | Se crea en `exec()` antes de iniciar el stream y se hace `finish()` (escribe el .json) en el cleanup, antes de borrar el `SdlInputHandler`. |

> El recorder graba **lo que el host realmente recibe**, no lo que SDL emite.
> Por eso la captura es coherente con `--multi-controller`, `mouseEmulation`
> y `clickpadButtonEmulationEnabled`.

---

## 2. Flujo de uso

### 2.1 Grabar una macro mientras juegas

```powershell
build\deploy-x64-debug\Moonlight.exe stream <HOST> "<APP>" `
  --input-record .\macros\round1_p1.json `
  --input-record-hz 60
```

Juegas la secuencia con tu pad físico. Al **cerrar el stream limpiamente**
(`Ctrl+Alt+Shift+Q`, cierre por GFE, etc.) el recorder llama a `finish()` y
escribe el JSON. Si matas el proceso (`Stop-Process`) **no se escribe nada**:
es por diseño (evita ficheros corruptos a medio escribir).

> El esquema producido es exactamente el mismo que entiende `play.py` en modo
> `events`. Se puede editar a mano y reproducir tal cual.

### 2.2 Reinyectar una macro grabada

```powershell
# Terminal 1: Moonlight escuchando órdenes
build\deploy-x64-debug\Moonlight.exe stream <HOST> "<APP>" `
  --input-inject-port 47999 `
  --input-inject-token <token-16+chars> `
  --block-physical-input
```

```powershell
# Terminal 2: cliente externo
python tools\inputbench\play.py `
  --port 47999 --token <token> `
  .\macros\round1_p1.json
```

Con `--block-physical-input`, tu mando real **deja de existir** desde la
perspectiva del host mientras dura el stream — útil para que la macro
no compita con tus dedos en pruebas de "mismo input dos veces seguidas".

### 2.3 Grabar y reinyectar a la vez (verificación round-trip)

```powershell
build\deploy-x64-debug\Moonlight.exe stream <HOST> "<APP>" `
  --input-inject-port 47999 --input-inject-token <token> `
  --input-record .\macros\replay_capture.json
```

Lanza la macro original con `play.py`. El recorder captura **lo que el host
recibió** (procedente del `InputInjector`) y lo guarda. Comparando los dos
JSON con `diff`, validas que el scheduler no introduce drift visible al host.

---

## 3. Esquema del fichero `.json`

Idéntico para grabaciones y para macros escritas a mano:

```json
{
  "frame_hz": 60.0,
  "shift_pad0": 0,
  "shift_pad1": 0,
  "events": [
    { "frame": 0,  "pads": { "0": { "buttons": [], "lt": 0, "rt": 0,
                                    "ls_x": 0, "ls_y": 0, "rs_x": 0, "rs_y": 0 } } },
    { "frame": 12, "pads": { "0": { "buttons": ["DOWN"], "lt": 0, "rt": 0,
                                    "ls_x": 0, "ls_y": -32000, "rs_x": 0, "rs_y": 0 } } },
    { "frame": 14, "pads": { "0": { "buttons": ["DOWN", "RIGHT"], ... } } },
    { "frame": 16, "pads": { "0": { "buttons": ["RIGHT"], ... } } },
    { "frame": 18, "pads": { "0": { "buttons": ["A"], ... } } }
  ]
}
```

- **`frame_hz`**: tasa que define la longitud de un "frame". Para CotW usa 60.
- **`shift_pad0` / `shift_pad1`**: offset por jugador, en frames. El recorder
  los escribe siempre a `0`; pueden editarse a mano para pruebas de delay.
- **`events[i].pads["N"]`**: estado **absoluto** del pad `N` en ese frame
  (no es delta). El injector calcula el diff contra el frame anterior.
- **Botones soportados**: `A B X Y UP DOWN LEFT RIGHT LB RB LS RS BACK START GUIDE MISC PADDLE1..4 TOUCHPAD`.

---

## 4. Modelo de hilos

```
┌─────────────────┐                ┌────────────────────┐
│  SDL main loop  │ event          │ SdlInputHandler    │
│  (thread A)     │───────────────▶│ ::sendGamepadState │
└─────────────────┘                └────────┬───────────┘
                                            │
                  ┌─ if sBlockPhysical ─────┴── return ──┐
                  │                                       │
                  ▼                                       │
       LiSendMultiControllerEvent ──┐                     │
                                    │                     │
                                    ▼                     │
                          InputRecorder::tap ─────────────┘
                                    │  (mutex breve)
                                    ▼
                             m_Events (vector)

┌─────────────────────┐ JSON line  ┌──────────────────────┐
│ play.py / cliente   │───────────▶│ InputControlServer   │ (Qt main)
└─────────────────────┘            └────────┬─────────────┘
                                            │ play()
                                            ▼
                                   ┌──────────────────────┐
                                   │ InputInjector worker │
                                   │ (std::thread, busy   │
                                   │  wait sub-ms)        │
                                   └────────┬─────────────┘
                                            ▼
                                   LiSendMultiControllerEvent
                                            │
                                            ▼
                                   InputRecorder::tap (si activo)
```

**Garantías**:
- `InputRecorder::tap` es **lock-light**: toma `m_Mtx` solo cuando el estado
  del pad cambió respecto al último tap del mismo pad. Para juegos a 60 Hz
  con axes en reposo, esto significa cero contención durante segundos.
- `sBlockPhysical` es `std::atomic<bool>` con load `relaxed`: cero overhead
  en el hot-path SDL.
- El recorder y el injector son **independientes**: puedes grabar sin tener
  el server activo, o tener el server activo sin grabar.

---

## 5. Flujo de compilación y despliegue

> Esta sección documenta cómo se construye y despliega el binario que actúa como
> "servidor que mueve los controles" — es decir, `Moonlight.exe` con todos los
> añadidos del input-bench cargados.

### 5.1 Vista general de la cadena de build (Windows / MSVC)

```
┌─────────────────────────────────────────────────────────────────┐
│                       moonlight-qt.pro                           │ qmake raíz
│  SUBDIRS = AntiHooking, qmdnsengine, h264bitstream,              │
│            moonlight-common-c, app                               │
└──────────────────────────────┬──────────────────────────────────┘
                               │ qmake
                               ▼
              ┌────────────────────────────────┐
              │        Makefile (raíz)          │
              │   Makefile.Debug / .Release     │
              └──────────────┬─────────────────┘
                             │ jom -j N
                             ▼
        ┌─────────────────────────────────────────┐
        │ AntiHooking.lib   qmdnsengine.lib       │
        │ h264bitstream.lib moonlight-common-c.lib│
        └──────────────────┬──────────────────────┘
                           │  (link estático)
                           ▼
                 ┌──────────────────┐
                 │ app/Makefile     │   <-- generado por qmake desde app/app.pro
                 │ + moc + cl + link│
                 └────────┬─────────┘
                          │
                          ▼
                build\build-x64-debug\app\debug\Moonlight.exe
                                      │
                                      │ build-helper.ps1 deploy
                                      ▼
                            build\deploy-x64-debug\
                            Moonlight.exe + DLLs Qt + plugins
```

### 5.2 Toolchain requerida

| Herramienta | Versión usada | Ruta típica |
|---|---|---|
| Qt | 6.11.0 MSVC 2022 64-bit | `C:\Qt\6.11.0\msvc2022_64` |
| MSVC Build Tools | VS 2022 (cl 14.44) | `C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools` |
| jom | (incluido en `scripts\jom.exe`) | `scripts\jom.exe` |
| Windows SDK | 10.0.26100 | gestionado por VS BuildTools |
| Python | 3.10+ (solo para `play.py`) | cualquier `python.exe` en PATH |

### 5.3 Build manual completo (desde cero)

```powershell
cd C:\Users\Tortita\Documents\GitHub\moonlight-qt

# 1. Cargar el entorno MSVC en la sesión actual.
$vc = "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat"
cmd /c "`"$vc`" x64 && set" |
  Where-Object { $_ -match '=' } |
  ForEach-Object { $kv = $_ -split '=', 2; [Environment]::SetEnvironmentVariable($kv[0], $kv[1]) }

# 2. Generar el árbol Makefile.
mkdir build\build-x64-debug -Force | Out-Null
cd build\build-x64-debug
C:\Qt\6.11.0\msvc2022_64\bin\qmake.exe `
  ..\..\moonlight-qt.pro -spec win32-msvc "CONFIG+=debug"

# 3. Compilar (paralelo).
C:\Users\Tortita\Documents\GitHub\moonlight-qt\scripts\jom.exe debug
```

### 5.4 Build incremental (lo más habitual durante el desarrollo)

```powershell
# Re-ejecutar SOLO el subproyecto app/ tras tocar fuentes existentes:
$vc = "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat"
cmd /c "`"$vc`" x64 && cd /d build\build-x64-debug && C:\Users\Tortita\Documents\GitHub\moonlight-qt\scripts\jom.exe debug"
```

> **Cuándo regenerar Makefile a mano**: si añades / borras ficheros en `app.pro`.
> En ese caso, además del `jom debug` anterior, ejecuta primero:
>
> ```powershell
> cd build\build-x64-debug\app
> C:\Qt\6.11.0\msvc2022_64\bin\qmake.exe -o Makefile ..\..\..\app\app.pro
> ```
>
> El recorder se incorporó así: `app.pro` recibió `inputrecorder.cpp` y
> `inputrecorder.h`, luego se regeneró `app/Makefile` y se relanzó `jom debug`.
> El subproyecto raíz **no necesita re-qmake** porque `SUBDIRS` no cambió.

### 5.5 Despliegue (deploy) del binario

El `Moonlight.exe` recién enlazado vive en `build\build-x64-debug\app\debug\`,
pero arrancarlo desde ahí falla por DLLs Qt no encontradas. Hay dos formas:

**Opción A — full deploy (genera la carpeta completa con `windeployqt`):**

Es lo que hace `build-helper.ps1 deploy`. Internamente:
1. Copia `Moonlight.exe`, `Moonlight.pdb`, `Moonlight.ilk`.
2. Ejecuta `windeployqt --debug --qmldir app\gui Moonlight.exe`, que copia:
   - `Qt6Core.dll`, `Qt6Gui.dll`, `Qt6Quick.dll`, `Qt6Network.dll`, ...
   - Plugins (`platforms\qwindowsd.dll`, `imageformats\*`, `tls\*`, ...).
   - Caches QML compilados.
3. Copia DLLs de terceros desde `libs\windows\bin\x64`: SDL2, ffmpeg,
   placebo, openssl, discord-rpc, etc.

**Opción B — refresh rápido (cuando solo cambiaste `Moonlight.exe`):**

Las DLLs ya están en la carpeta deploy de un build previo, basta sobrescribir:

```powershell
Copy-Item build\build-x64-debug\app\debug\Moonlight.* `
          build\deploy-x64-debug\ -Force
```

Esto es lo que se ha venido haciendo durante phase 1 → 3 entre cambios de
código C++ que **no** alteran el grafo de dependencias Qt/SDL.

> Si alguna vez añades una llamada a un módulo Qt nuevo (p. ej. `QtMultimedia`),
> tienes que volver al deploy completo (Opción A) para que `windeployqt` arrastre
> la DLL correspondiente.

### 5.6 Build de Release (firmable y empaquetable)

```powershell
cmd /c "`"$vc`" x64 && set" | ...   # mismo bloque de entorno que en 5.3
mkdir build\build-x64-release -Force | Out-Null
cd build\build-x64-release
C:\Qt\6.11.0\msvc2022_64\bin\qmake.exe `
  ..\..\moonlight-qt.pro -spec win32-msvc "CONFIG+=release"
C:\Users\Tortita\Documents\GitHub\moonlight-qt\scripts\jom.exe release
```

Para producir el instalador MSI con WiX (`wix\Moonlight.sln`) o el ZIP
portable, ver `BUILD_WINDOWS_LOCAL.md` y `scripts\generate-bundle.bat`.

### 5.7 Diagnóstico de fallos comunes

| Síntoma | Causa probable | Arreglo |
|---|---|---|
| `'cl' is not recognized` | Falta entorno MSVC en la shell | Ejecutar `vcvarsall.bat x64` antes de `jom` |
| `LNK2019 unresolved external InputRecorder::tap` | `app.pro` quedó desfasado | Añadir `inputrecorder.cpp/.h` y re-qmake del subproyecto `app/` |
| `Cannot open include file: 'inputrecorder.h'` | Olvidaste `app.pro` o `gamepad.cpp` `#include` | Verificar ambos |
| `Q_OBJECT class with no MOC` | qmake no regeneró Makefile tras añadir un header con Q_OBJECT | Borrar `app/Makefile` y re-qmake |
| Moonlight arranca pero el recorder no escribe nada | Cierre forzado del proceso | El recorder solo flushea en cleanup limpio; salir con `Ctrl+Alt+Shift+Q` o desde el host |

---

## 6. Mapa de ficheros que toca Phase 3

```
app/
├── app.pro                                    # +inputrecorder.{cpp,h}
├── cli/
│   └── commandlineparser.cpp                  # +--input-record(-hz)
├── settings/
│   └── streamingpreferences.h                 # +inputRecordPath/Hz
└── streaming/
    ├── session.h                              # +InputRecorder fwd-decl + miembro
    ├── session.cpp                            # +ciclo de vida del recorder + sBlockPhysical
    └── input/
        ├── gamepad.cpp                        # +tap del recorder + guard sBlockPhysical
        ├── inputinjector.h                    # +static atomic sBlockPhysical
        ├── inputinjector.cpp                  # +definición de sBlockPhysical
        ├── inputrecorder.h                    # NUEVO
        └── inputrecorder.cpp                  # NUEVO
```

`tools/inputbench/play.py` y los samples no cambian: el recorder produce
ficheros **directamente compatibles** con el reproductor existente.

---

## 7. Limitaciones conocidas y trabajo futuro

- **Solo guarda en cierre limpio**. Falta una orden `RECORD_STOP` por TCP que
  permita pedir un flush a mitad de stream. Trivial de añadir al
  `InputControlServer` cuando haga falta.
- **No graba motion / accel / touchpad táctil**, solo `LiSendMultiControllerEvent`.
  Esto basta para fighting games; para juegos que usen giroscopio habría que
  tapar también `LiSendControllerMotionEvent`.
- **La compresión de eventos es por-cambio**, no por-frame. Si dos pads
  cambian en el mismo frame, generan dos entradas con el mismo `frame`. El
  reproductor las aplica en orden y el resultado es correcto, pero ficheros
  muy largos pueden compactarse fusionando entradas con `frame` igual.
- **`shift_pad0/1` se escriben siempre a 0**. Si quieres una macro con delay
  fijo entre P1 y P2, edítalos a mano antes de reinyectar.

---

## 8. Comprobación rápida (smoke test)

```powershell
# 1. Lanza un stream grabando
build\deploy-x64-debug\Moonlight.exe stream <HOST> "<APP>" --input-record .\smoke.json

# 2. Pulsa A, B, atrás, atrás, A en el mando físico. Cierra el stream.

# 3. Inspecciona
Get-Content .\smoke.json | Select-Object -First 40

# 4. Reinyecta esa misma macro
build\deploy-x64-debug\Moonlight.exe stream <HOST> "<APP>" `
  --input-inject-port 47999 --input-inject-token <token-16+>
python tools\inputbench\play.py --port 47999 --token <token> .\smoke.json
```

Si el host ve la misma combinación → round-trip OK.
