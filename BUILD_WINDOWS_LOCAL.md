# Compilar Moonlight-Qt en esta PC (Windows)

Fecha de validacion: 2026-05-01

## Resumen rapido

Estado actual en esta computadora:

- Git: instalado y funcionando.
- Submodulos: inicializados correctamente.
- 7-Zip: instalado en C:\Program Files\7-Zip\7z.exe.
- Qt: no instalado (qmake y windeployqt no existen en PATH).
- Visual Studio Build Tools / MSBuild / CL: no detectados.

Conclusión:

- El repositorio ya esta listo.
- Faltan las herramientas de compilacion (Qt + MSVC 2022).

---

## 1) Lo que ya quedo hecho en este repo

Se ejecuto correctamente:

- git submodule update --init --recursive

Prueba de build realizada:

- scripts\build-arch.bat debug

Primer error real obtenido:

- Unable to find QMake. Did you add Qt bins to your PATH?

---

## 2) Instalar prerequisitos en Windows

## 2.1 Visual Studio 2022 (requerido)

Instala Visual Studio 2022 Community o Build Tools 2022 con estos componentes:

- Desktop development with C++
- MSVC v143 - VS 2022 C++ x64/x86 build tools
- Windows 10/11 SDK (cualquiera reciente)
- C++ CMake tools for Windows (opcional, pero recomendado)

Si quieres por terminal (opcional):

- winget install --id Microsoft.VisualStudio.2022.Community -e

Luego abre Visual Studio Installer y verifica los componentes de C++ anteriores.

## 2.2 Qt 6.7 o superior con MSVC (requerido)

Instala Qt mediante Qt Online Installer.

Selecciona al menos:

- Qt 6.7+ para MSVC 2022 64-bit (por ejemplo: msvc2022_64)
- Qt Tools (incluye Qt Creator; opcional pero util)

Importante:

- No uses MinGW para este proyecto.
- Debe ser kit MSVC.

## 2.3 Graphics Tools (solo para debug runtime)

Solo necesario para ejecutar builds debug:

- Configuracion de Windows -> Optional Features -> Graphics Tools

O por terminal:

- dism /online /add-capability /capabilityname:Tools.Graphics.DirectX~~~~0.0.1.0

Reinicia si te lo pide.

---

## 3) Abrir terminal correcta para build

Debes compilar desde una terminal con Qt en PATH.

Opciones recomendadas:

1. Qt Command Prompt (la mejor opcion para este repo).
2. Developer PowerShell for VS 2022 + agregar ruta de Qt\bin al PATH manualmente.

Verificaciones minimas en la terminal antes de compilar:

- qmake -v
- where qmake
- where msbuild

Si qmake no aparece, agrega la carpeta de Qt bin, por ejemplo:

- C:\Qt\6.8.0\msvc2022_64\bin

---

## 4) Compilar para desarrollo (recomendado primero)

Desde la raiz del repo:

1. git submodule update --init --recursive
2. scripts\build-arch.bat debug

Salida esperada:

- Build successful ...
- Artefactos en carpeta build\

Notas:

- El script detecta arquitectura segun qmake (x64 o arm64).
- Usa jom y prepara dependencias Qt con windeployqt.

---

## 5) Compilar release

Desde la raiz del repo:

1. scripts\build-arch.bat release

Esto genera deploy e instalador MSI por arquitectura detectada.

---

## 6) Generar instalador final (multi-arquitectura)

Este paso requiere haber compilado antes ambas arquitecturas:

1. build-arch.bat release en entorno Qt x64
2. build-arch.bat release en entorno Qt arm64
3. scripts\generate-bundle.bat release

Si falta alguna arquitectura, generate-bundle fallara con mensaje explicito.

---

## 7) Checklist de diagnostico rapido (si algo falla)

1. qmake no encontrado:
   - Qt no instalado o PATH sin Qt\bin.
2. msbuild/cl no encontrados:
   - Falta Visual Studio C++ workload.
3. Error de submodulos:
   - Ejecutar git submodule update --init --recursive.
4. Error de windeployqt:
   - Kit Qt incompatible o mezcla de MinGW/MSVC.
5. Error en firmado/certificados:
   - Usa release normal (no signed-release) para desarrollo local.

---

## 8) Estado de esta PC tras validacion

Comandos validados con resultado:

- git --version: OK
- git submodule update --init --recursive: OK
- scripts\build-arch.bat debug: FAIL por falta de qmake
- Visual Studio installation path: no detectado
- C:\Qt: no existe

Siguiente accion concreta recomendada:

1. Instalar Visual Studio 2022 con C++.
2. Instalar Qt 6.7+ msvc2022_64.
3. Abrir Qt Command Prompt.
4. Reintentar scripts\build-arch.bat debug.
