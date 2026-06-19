# InputBench WebUI (FastAPI)

Interfaz web para controlar el servidor de inyección de Moonlight desde celular/tablet y ejecutar barridos sintéticos.

## Requisitos

- Python 3.10+
- Moonlight ejecutándose con:
  - `--input-inject-port <PORT>`
  - `--input-inject-token <TOKEN>`

## Configuración

1. Copia `tools/inputbench/webui/config.example.json` a `tools/inputbench/webui/config.json`.
2. Ajusta:
   - `moonlight.host/port/token`
   - `auth_pin` (opcional)
   - `reset_sequence`
   - `recorder` (ffmpeg) si quieres MP4 por intento

## Instalar dependencias

```bash
python3 -m pip install -r tools/inputbench/webui/requirements.txt
```

## Ejecutar

```bash
cd tools/inputbench/webui
uvicorn server:app --host 0.0.0.0 --port 8088
```

Luego abre desde celular/tablet: `http://<IP-LAN-DEL-PC>:8088`.

## Vistas

- `/live`: control táctil dual P1/P2 (portrait móvil y landscape tablet)
- `/sweep`: configuración y ejecución de barridos sintéticos con resultados

## API

- `GET /api/ping`
- `GET /api/status`
- `POST /api/stop`
- `POST /api/hold`
- `POST /api/play`
- `POST /api/reset-training`
- `POST /api/sweep/start|stop|pause|resume|skip|judge`
- `GET /api/sweep/status|results`
- `GET /api/config`
- `WS /ws`

## Notas

- No se modifica `app/` ni `tools/inputbench/play.py`.
- Si no hay `config.json`, se usan defaults desde `config.example.json`.
- En modo manual (`winner_mode=manual`), cada intento queda pendiente de juicio en la UI.
