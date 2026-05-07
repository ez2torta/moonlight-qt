# Moonlight Debug: conexion al host correcto (Windows)

Guia corta y directa para correr Moonlight debug y conectarlo al PC que quieres.

## 0. Ejecutable que debes usar

Usa este binario (debug desplegado):

    .\build\deploy-x64-debug\Moonlight.exe

Si no existe, compila primero:

    .\build-helper.ps1 full x64 debug

Si ya compilaste y solo cambiaste codigo:

    .\build-helper.ps1 compile x64 debug
    .\build-helper.ps1 deploy x64 debug

## 1. Asegura que estas apuntando al host correcto

No uses nombres ambiguos. Usa IP o UUID del host deseado.

Ejemplo con IP:

    $HOST = "192.168.1.50"

Verifica que Moonlight ve ese host y puede listar apps:

    .\build\deploy-x64-debug\Moonlight.exe list $HOST

Si este comando falla, todavia no hay conectividad real al host correcto.

## 2. Pairing al host correcto

Haz pairing explicito contra ese host:

    .\build\deploy-x64-debug\Moonlight.exe pair $HOST

O con PIN fijo:

    .\build\deploy-x64-debug\Moonlight.exe pair $HOST --pin 1234

Luego prueba otra vez:

    .\build\deploy-x64-debug\Moonlight.exe list $HOST

Si list funciona, el host correcto ya esta emparejado.

## 3. Ejecutar stream debug normal

Ejemplo:

    .\build\deploy-x64-debug\Moonlight.exe stream $HOST "Desktop"

Tip: usa exactamente el nombre del app como aparece en list.

## 4. Ejecutar stream debug con input injection

Genera token seguro:

    $TOKEN = -join ((48..57) + (97..102) | Get-Random -Count 32 | ForEach-Object { [char]$_ })

Arranca stream con inyeccion habilitada:

    .\build\deploy-x64-debug\Moonlight.exe stream `
      --input-inject-port 47999 `
      --input-inject-token $TOKEN `
      $HOST "Desktop"

Notas importantes:
- El puerto de inyeccion escucha solo en localhost (127.0.0.1).
- No necesitas 2 controles fisicos conectados.
- El inyector declara 2 pads virtuales (P1 y P2) internamente.

## 5. Validacion rapida de que la inyeccion esta viva

En otra terminal, mientras el stream esta activo:

    Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 47999 -State Listen

Si aparece en LISTEN, el control server esta activo.

## 6. Si no conecta al PC deseado

Checklist rapido:

1. Estas usando IP/UUID del host correcto (no un nombre repetido).
2. list funciona con ese host.
3. pair se hizo contra ese mismo host.
4. El host (Sunshine/GameStream) esta encendido y aceptando sesiones.
5. Firewall/antivirus en host no bloquea Sunshine/GameStream.
6. Cliente y host estan en la misma red/subred o ruta valida.

## 7. Comandos de diagnostico minimos

Ver ayuda general:

    .\build\deploy-x64-debug\Moonlight.exe --help

Ver ayuda por accion:

    .\build\deploy-x64-debug\Moonlight.exe pair --help
    .\build\deploy-x64-debug\Moonlight.exe list --help
    .\build\deploy-x64-debug\Moonlight.exe stream --help

## 8. Error comun que puedes ignorar

Al correr desde terminal puede salir:

    SetProcessDpiAwarenessContext() failed: Access is denied.

Eso no bloquea el uso normal de pair/list/stream en la mayoria de casos.
