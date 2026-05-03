# Moonlight-Qt: Flujo de Controles + Plan de Grabador/Reproductor de Inputs

## Objetivo de este documento

Este documento resume:

1. Como se capturan, transforman y envian los controles actualmente.
2. Que cambios conviene hacer para incorporar un grabador/reproductor de inputs dentro de Moonlight.

---

## 1) Flujo actual de controles (estado actual)

## 1.1 Bucle principal de eventos

El loop de la sesion recibe eventos SDL y los delega a SdlInputHandler:

- Teclado: SDL_KEYDOWN / SDL_KEYUP
- Mouse: SDL_MOUSEMOTION / SDL_MOUSEBUTTONDOWN / SDL_MOUSEBUTTONUP / SDL_MOUSEWHEEL
- Gamepad: SDL_CONTROLLERAXISMOTION / SDL_CONTROLLERBUTTONDOWN / SDL_CONTROLLERBUTTONUP
- Touch: SDL_FINGERDOWN / SDL_FINGERMOTION / SDL_FINGERUP
- Eventos extendidos de mando: sensores, touchpad, bateria, llegada/salida de dispositivo

Despacho principal:

- app/streaming/session.cpp
  - Session::startConnectionAsync()
  - Session::start()
  - switch de eventos SDL en el loop principal

## 1.2 Teclado

Entrada principal:

- app/streaming/input/keyboard.cpp
  - SdlInputHandler::handleKeyEvent()

Comportamiento relevante:

- Detecta y consume combos especiales locales (quit, fullscreen, overlay, etc.).
- Construye modifiers (Ctrl, Alt, Shift, Meta segun configuracion).
- Convierte scancode SDL a codigo de tecla esperado por host.
- Envia evento con LiSendKeyboardEvent2().
- Soporta inyeccion de texto UTF-8 con LiSendUtf8TextEvent().
- Mantiene estado de teclas presionadas para evitar teclas "pegadas" y poder levantar todo con raiseAllKeys().

## 1.3 Mouse

Entrada principal:

- app/streaming/input/mouse.cpp
  - handleMouseButtonEvent()
  - handleMouseMotionEvent()
  - handleMouseWheelEvent()

Comportamiento relevante:

- Modo relativo:
  - Envia deltas con LiSendMouseMoveEvent().
- Modo absoluto:
  - Reescala cursor a la region de video.
  - Aplica clamp a bordes del stream.
  - Envia posicion con LiSendMousePositionEvent().
- Scroll:
  - Usa high-resolution si SDL lo soporta (LiSendHighResScrollEvent / LiSendHighResHScrollEvent).
  - Si no, fallback a pasos discretos (LiSendScrollEvent / LiSendHScrollEvent).

## 1.4 Gamepad

Entrada principal:

- app/streaming/input/gamepad.cpp
  - sendGamepadState()
  - handleControllerAxisEvent()
  - handleControllerButtonEvent()
  - handleControllerSensorEvent()
  - handleControllerTouchpadEvent()
  - handleControllerDeviceEvent()

Comportamiento relevante:

- Mantiene estado por mando: botones, sticks, triggers, timers, capacidades.
- Modo single-controller:
  - Fusiona estado de varios mandos en un solo jugador.
- Modo multi-controller:
  - Conserva cada mando con indice propio y mascara activa.
- Envio principal de estado:
  - LiSendMultiControllerEvent().
- Llegada/salida de mando:
  - Declara tipo y capacidades con LiSendControllerArrivalEvent().
  - Notifica salida enviando estado vacio.
- Extras:
  - Bateria: LiSendControllerBatteryEvent().
  - Sensor acelerometro/giroscopio: LiSendControllerMotionEvent().
  - Touchpad de mando: LiSendControllerTouchEvent().

## 1.5 Touch de pantalla

Entrada principal:

- app/streaming/input/input.cpp
  - handleTouchFingerEvent()

Rutas:

- Modo touch absoluto:
  - app/streaming/input/abstouch.cpp
  - Si host soporta pen/touch nativo, usa LiSendTouchEvent() y LiSendPenEvent().
  - Si no, emula mouse (tap, long-press, drag).
- Modo touch relativo tipo trackpad:
  - app/streaming/input/reltouch.cpp
  - Emula movimiento relativo y clicks con timers/gestos.

## 1.6 Configuracion de captura y estado global

- app/streaming/input/input.cpp
  - setCaptureActive()
  - isSystemKeyCaptureActive()
  - raiseAllKeys()

Esto afecta si un input se procesa o se descarta, y si se captura teclado/mouse del sistema.

---

## 2) Meta: grabador/reproductor integrado

## 2.1 Que significa "grabador/reproductor" aqui

Grabador:

- Guardar en archivo una secuencia temporal de inputs ya "normalizados" por Moonlight.
- Incluir timestamps relativos para reproducir timing real.

Reproductor:

- Leer archivo de sesion de input.
- Reinyectar eventos al pipeline de envio respetando tiempos.
- Opcion de velocidad (0.5x, 1x, 2x), pausa, stop, loop opcional.

## 2.2 Nivel de captura recomendado

Se recomienda capturar en la capa inmediatamente anterior a LiSend..., no a nivel SDL crudo.

Ventajas:

- Se graba exactamente lo que se enviaria al host.
- Evita diferencias por plataforma/dispositivo SDL.
- Reduce complejidad de parser de eventos SDL.

Consecuencia:

- Hay que encapsular todas las llamadas LiSend... en un punto comun para poder interceptar.

---

## 3) Arquitectura propuesta

## 3.1 Nuevo componente central: InputTransport

Crear modulo nuevo, por ejemplo:

- app/streaming/input/inputtransport.h
- app/streaming/input/inputtransport.cpp

Responsabilidad:

- API unica para enviar todo input (teclado, mouse, gamepad, touch).
- En modo normal: delega a LiSend... real.
- En modo grabacion: delega a LiSend... y tambien registra evento.
- En modo reproduccion: puede bloquear input local real y enviar solo eventos del playback.

## 3.2 Nuevo componente: InputRecorder

Crear:

- app/streaming/input/inputrecorder.h
- app/streaming/input/inputrecorder.cpp

Responsabilidad:

- startRecording(path)
- stopRecording()
- writeEvent(type, payload, t_relative_us)

## 3.3 Nuevo componente: InputPlayback

Crear:

- app/streaming/input/inputplayback.h
- app/streaming/input/inputplayback.cpp

Responsabilidad:

- load(path)
- start(speed)
- pause()
- resume()
- stop()
- Loop de scheduler basado en reloj monotonic.
- Emision de eventos hacia InputTransport.

## 3.4 Formato de archivo recomendado

Primera version simple y robusta:

- Contenedor binario con header fijo + frames TLV.

Header sugerido:

- magic: MLIN
- version: 1
- created_unix_ms
- stream_profile (resolucion, fps opcional)

Frame sugerido:

- delta_us (uint32)
- event_type (uint16)
- payload_len (uint16)
- payload bytes

Motivo de binario:

- Menor tamaño y parseo mas rapido.
- Menor overhead que JSON para streams largos.

(Se puede agregar herramienta de export JSON para debugging en una etapa posterior.)

---

## 4) Plan de cambios concretos por archivo

## 4.1 Introducir InputTransport y usarlo en vez de LiSend directo

Cambios principales:

- app/streaming/input/keyboard.cpp
- app/streaming/input/mouse.cpp
- app/streaming/input/gamepad.cpp
- app/streaming/input/abstouch.cpp
- app/streaming/input/reltouch.cpp
- app/streaming/input/input.cpp (solo si hay envios directos adicionales)

Accion:

- Reemplazar llamadas LiSend... por wrappers de InputTransport.

Ejemplo conceptual:

- Antes: LiSendMouseMoveEvent(dx, dy)
- Despues: inputTransport.sendMouseMove(dx, dy)

## 4.2 Inyectar InputTransport en SdlInputHandler

Archivos:

- app/streaming/input/input.h
- app/streaming/input/input.cpp
- app/streaming/session.cpp

Accion:

- Agregar miembro InputTransport al handler.
- Inicializarlo desde Session con configuracion (normal/record/playback).

## 4.3 Integrar estado de grabacion/reproduccion en Session

Archivos:

- app/streaming/session.h
- app/streaming/session.cpp

Accion:

- Agregar estado de recorder y playback de sesion.
- Garantizar que callbacks de red y event loop principal no rompan sincronizacion.
- Definir politica cuando playback esta activo:
  - Opcion A: bloquear input local.
  - Opcion B: mezclar (no recomendado para primera version).

## 4.4 Exponer controles por CLI

Archivos:

- app/cli/commandlineparser.cpp
- app/settings/streamingpreferences.* (si se guarda en prefs)

Flags sugeridas:

- --input-record=<ruta>
- --input-play=<ruta>
- --input-play-speed=<float>
- --input-play-loop
- --input-block-live-during-playback

## 4.5 Exponer controles en GUI (fase 2)

Archivos tentativos:

- app/gui/SettingsView.qml (o equivalente)
- app/gui model C++ asociado

Opciones GUI:

- Boton Start/Stop recording
- Boton Load + Play/Pause/Stop
- Indicador REC/PLAY superpuesto

---

## 5) Orden de implementacion recomendado

Fase 1 (MVP tecnico, sin UI):

1. Crear InputTransport.
2. Cambiar todas las rutas LiSend... del input handler para usar InputTransport.
3. Crear InputRecorder con formato binario v1.
4. Agregar flags CLI para grabar.
5. Validar que el stream funciona igual sin grabar.

Fase 2 (playback basico):

1. Crear InputPlayback con scheduler temporal.
2. Reproducir eventos solo durante sesion activa.
3. Agregar bloqueo de input local opcional.
4. Agregar speed factor.

Fase 3 (ergonomia y robustez):

1. Integracion GUI.
2. Indicadores visuales y logs.
3. Soporte de loop.
4. Herramienta de inspeccion/debug de archivos grabados.

---

## 6) Riesgos tecnicos y mitigaciones

Riesgo 1: timing inestable en playback

- Mitigacion: usar reloj monotonic y scheduler por delta_us.
- Mitigacion: limitar catch-up maximo por tick para no burstear eventos.

Riesgo 2: desincronizacion por cambios de resolucion/escala en modo absoluto

- Mitigacion: almacenar metadata de stream (width/height) y advertir mismatch.
- Mitigacion: opcion de remap en playback futuro.

Riesgo 3: race conditions con callbacks y event loop

- Mitigacion: recorder/playback operan en main thread o usan cola thread-safe unica.

Riesgo 4: crecimiento excesivo de archivo

- Mitigacion: compresion opcional futura.
- Mitigacion: rotacion por tamano o duracion maxima.

---

## 7) Estrategia de testing

## 7.1 Tests funcionales manuales minimos

1. Stream normal sin recorder: comportamiento identico al actual.
2. Grabar 30 s con teclado + mouse + gamepad.
3. Reproducir y verificar comportamiento equivalente en host.
4. Reproducir a 0.5x y 2x.
5. Probar con multi-controller ON/OFF.
6. Probar touch absoluto/relativo.

## 7.2 Instrumentacion recomendada

- Contador de eventos grabados por tipo.
- Contador de eventos reproducidos y drops.
- Log de drift temporal medio y maximo en playback.

---

## 8) Definicion de Done (MVP)

Se considera MVP terminado cuando:

1. Se puede iniciar stream con flag de grabacion y produce archivo valido.
2. Se puede iniciar stream con flag de reproduccion y se reinyectan inputs.
3. No hay regresion observable del manejo de input cuando recorder/playback esta desactivado.
4. Se documenta formato v1 y limitaciones.

---

## 9) Nota sobre dependencias de bajo nivel

En este workspace, la carpeta del submodulo moonlight-common-c que usualmente contiene implementaciones internas aparece vacia.

Esto no bloquea el plan del grabador/reproductor propuesto porque la integracion se hace en Moonlight-Qt, justo antes de las llamadas LiSend....

Si mas adelante se necesita instrumentar serializacion interna de paquetes, habra que inicializar/traer ese submodulo completo.
