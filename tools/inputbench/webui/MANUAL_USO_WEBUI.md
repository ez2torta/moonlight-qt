# Manual de uso WebUI (InputBench)

Manual practico para usar el WebUI de InputBench con tu build debug de Moonlight en Windows.

## 1. Objetivo

El WebUI te permite:
- Control tactil manual de P1/P2 en vivo.
- Ejecutar barridos sinteticos (sweep) con parametros combinatorios.
- Registrar resultados por intento.
- Enviar un reset previo entre intentos (si defines reset_sequence).

## 2. Prerrequisitos

1. Moonlight debug debe estar corriendo en stream con inyeccion habilitada.
2. WebUI debe apuntar al mismo host/port/token de inyeccion.
3. El puerto de inyeccion (ejemplo 47999) es local (127.0.0.1).

## 3. Arranque recomendado (paso a paso)

### 3.1 Iniciar Moonlight con inyeccion

En terminal 1:

    $HOST = "IP_O_HOST_OBJETIVO"
    $APP  = "Desktop"
    $TOKEN = -join ((48..57) + (97..102) | Get-Random -Count 32 | ForEach-Object { [char]$_ })

    .\build\deploy-x64-debug\Moonlight.exe stream `
      --input-inject-port 47999 `
      --input-inject-token $TOKEN `
      $HOST $APP

### 3.2 Ajustar config del WebUI

Archivo:
- tools/inputbench/webui/config.json

Valores clave:
- moonlight.host: 127.0.0.1
- moonlight.port: 47999
- moonlight.token: debe ser exactamente el mismo TOKEN usado al arrancar Moonlight
- listen_host: 0.0.0.0 (si quieres abrir WebUI desde celular en la LAN)
- listen_port: 8088

### 3.3 Iniciar WebUI

En terminal 2:

    cd tools\inputbench\webui
    uvicorn server:app --host 0.0.0.0 --port 8088

### 3.4 Abrir interfaz

- PC local: http://127.0.0.1:8088
- Celular/tablet en LAN: http://IP_DE_TU_PC:8088

## 4. Uso por pantallas

## 4.1 Inicio (/)

- Guarda PIN opcional (auth_pin) localmente en navegador.
- Si auth_pin esta vacio en config, no hay autenticacion.

## 4.2 Live (/live)

- Control tactil de P1 y P2 (hold por boton).
- release-all: suelta todos los botones sin STOP global.
- panic-stop: envia STOP y limpia estados.
- Ping y estado de conexion se actualizan en polling.

## 4.3 Sweep (/sweep)

- Configuras templates de P1/P2:
  - directions
  - actions
  - buttons
  - rangos de frames
- Botones principales:
  - Test training reset: reproduce reset_sequence
  - Start: inicia barrido
  - Pause/Resume/Skip/Stop: control de corrida
  - Judge P1/P2/Draw/Unknown/Repeat: veredicto manual cuando winner_mode=manual
- Resultados:
  - Tabla con ganador, parametros y rutas de archivos generados.

## 5. Que era reset_training.json

Es una secuencia JSON de inputs que el WebUI usa para:

1. Boton Test training reset (endpoint /api/reset-training).
2. Paso previo antes de cada intento en Sweep (si existe el archivo).

Si no existe, el endpoint /api/reset-training responde 404 y no hay reset previo.

## 6. Estado de tu repo

Se detecto que faltaba este archivo:
- tools/inputbench/sequences/reset_training.json

Ya fue agregado con una secuencia neutral basica para liberar direcciones/botones en P1 y P2.

## 7. Validaciones rapidas

### 7.1 Ver que Moonlight escucha inyeccion

    Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 47999 -State Listen

### 7.2 Ver conectividad WebUI -> Moonlight

Desde navegador o curl a:
- GET /api/ping
- GET /api/status

Si falla, casi siempre es token distinto o puerto distinto.

## 8. Problemas comunes

1. 401 unauthorized:
- auth_pin configurado pero no cargado en el navegador.

2. moonlight request failed / handshake failed:
- token de config.json no coincide con el token del stream activo.

3. reset-training da 404:
- ruta reset_sequence incorrecta o archivo inexistente.

4. Celular no abre WebUI:
- usar listen_host 0.0.0.0
- permitir puerto 8088 en firewall de Windows

## 9. Recomendacion para tu flujo diario

1. Arranca Moonlight stream con token nuevo.
2. Copia token a config.json.
3. Levanta WebUI.
4. Prueba /api/ping.
5. Prueba Live.
6. Corre Sweep.
