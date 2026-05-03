# Build Process Explained: scripts/build-arch.bat

## Overview

The `build-arch.bat` script orchestrates a **complete, destructive build** from clean slate:
1. **Destroys all previous build artifacts**
2. **Reconfigures the project** using qmake
3. **Compiles from scratch** using jom.exe  
4. **Deploys runtime dependencies** (Qt DLLs, plugins, etc.)
5. **Creates installer package** (MSI via WiX)

---

## Detailed Build Stages

### Stage 1: Environment Setup (Lines 30–95)
**What:** Detects Qt installation, Visual Studio, and target architecture.

**Key Operations:**
- Reads `app/version.txt` for version number
- Maps architecture: `x86` → i386, `x64` → AMD64, `arm` → ARM, `arm64` → ARM64
- Calls `vswhere.exe` to find latest Visual Studio installation
- Runs `vcvarsall.bat` to configure MSVC compiler for target arch
- Finds Visual C++ redistributable DLLs (runtime dependencies like `msvcp140.dll`)

**Output if fails:**
- If Qt not found: "Unable to find qmake command"
- If VS not found: "Unable to find Visual Studio"
- If vcvarsall fails: C++ compiler not initialized

---

### Stage 2: Clean Build Directories (Lines 130–145)
**What:** **DESTRUCTIVELY WIPES** all previous builds.

```batch
rmdir /s /q %DEPLOY_FOLDER%      ← Removes bin/ with Moonlight.exe + DLLs
rmdir /s /q %BUILD_FOLDER%       ← Removes intermediate .obj files
rmdir /s /q %INSTALLER_FOLDER%   ← Removes .msi + portable zip
rmdir /s /q %SYMBOLS_FOLDER%     ← Removes .pdb debug files
mkdir %BUILD_ROOT%
mkdir %DEPLOY_FOLDER%
mkdir %BUILD_FOLDER%
mkdir %INSTALLER_FOLDER%
mkdir %SYMBOLS_FOLDER%
```

**Result:** Fresh empty directories created.

---

### Stage 3: Project Configuration (Lines 147–150)
**What:** Runs qmake to generate Makefiles.

```batch
pushd %BUILD_FOLDER%
%QMAKE_CMD% %SOURCE_ROOT%\moonlight-qt.pro
```

**Output:**
- Generated Makefiles: `build-x64-debug/Moonlight.exe.Makefile`, `AntiHooking.Pro.Makefile`, etc.
- qmake processes submodule .pro files (AntiHooking, app, h264bitstream, etc.)

---

### Stage 4: Compilation (Lines 152–156)
**What:** Compiles all source files using jom (parallel make).

```batch
pushd %BUILD_FOLDER%
%SOURCE_ROOT%\scripts\jom.exe %BUILD_CONFIG%
```

**Output:**
- Intermediate files: `*.obj` files in subdirectories
- Partial binaries: `AntiHooking\debug\AntiHooking.dll`, `app\debug\Moonlight.exe` (undeployed)

---

### Stage 5: Save Debug Symbols (Lines 158–179)
**What:** Collects `.pdb` files from build tree and archives them.

```batch
for /r "%BUILD_FOLDER%" %%f in (*.pdb) do (
    copy "%%f" %SYMBOLS_FOLDER%
)
copy %SOURCE_ROOT%\libs\windows\lib\%ARCH%\*.pdb %SYMBOLS_FOLDER%
7z a %SYMBOLS_FOLDER%\MoonlightDebuggingSymbols-%ARCH%-%VERSION%.zip %SYMBOLS_FOLDER%\*.pdb
```

**Output:**
- 22 `.pdb` files in `symbols-x64-debug/`
- `MoonlightDebuggingSymbols-x64-6.1.0.zip`

---

### Stage 6: Copy Runtime Dependencies (Lines 198–212)
**What:** Copies pre-built external DLLs and configuration files to deploy folder.

```batch
copy %SOURCE_ROOT%\libs\windows\lib\%ARCH%\*.dll %DEPLOY_FOLDER%
    ↓ FFmpeg: avcodec-62.dll, avutil-60.dll, swscale-9.dll
    ↓ OpenSSL: libssl-3-x64.dll, libcrypto-3-x64.dll
    ↓ Audio: opus.dll, SDL2_ttf.dll, libplacebo-360.dll, dav1d.dll

copy %BUILD_FOLDER%\AntiHooking\%BUILD_CONFIG%\AntiHooking.dll %DEPLOY_FOLDER%
copy %SOURCE_ROOT%\app\SDL_GameControllerDB\gamecontrollerdb.txt %DEPLOY_FOLDER%
```

---

### Stage 7: Deploy Qt Framework (Lines 223–232)
**What:** Runs `windeployqt.exe` to copy Qt DLLs, plugins, and QML files.

```batch
%WINDEPLOYQT_CMD% --dir %DEPLOY_FOLDER% --%BUILD_CONFIG% --qmldir %SOURCE_ROOT%\app\gui
    --no-opengl-sw --no-compiler-runtime --no-sql %WINDEPLOYQT_ARGS%
    %BUILD_FOLDER%\app\%BUILD_CONFIG%\Moonlight.exe
```

**Output:**
- Qt DLLs: `Qt6Core.dll`, `Qt6Gui.dll`, `Qt6Qml.dll`, `Qt6Quick.dll`, etc.
- Qt plugins: `imageformats/`, `iconengines/`, `platforms/` subdirectories
- QML modules: `qml/QtQuick/`, `qml/QtQml/` subdirectories

**Qt 6.8+ specific excludes:**
- ~~Fusion, Imagine, Universal control styles~~ (not needed for Moonlight UI)
- ~~qmltooling plugin~~ (QML debugging removed)
- ~~FFmpeg codec~~ (Moonlight uses FFmpeg libs directly)

---

### Stage 8: Clean Unused Qt Files (Lines 234–244)
**What:** Removes unused Qt control styles to reduce package size.

```batch
rmdir %DEPLOY_FOLDER%\qml\QtQuick\Controls\Fusion
rmdir %DEPLOY_FOLDER%\qml\QtQuick\Controls\Universal
rmdir %DEPLOY_FOLDER%\qml\QtQuick\Controls\Windows
rmdir %DEPLOY_FOLDER%\qml\QtQuick\Controls\FluentWinUI3
del %DEPLOY_FOLDER%\icuuc.dll  ← Qt deployed wrong version for ARM64
```

---

### Stage 9: Code Signing (Lines 246–254, Optional)
**What:** If `SIGN=1`, digitally signs all DLLs and EXE.

```batch
signtool %SIGNTOOL_PARAMS% Moonlight.exe *.dll  ← Uses DigiCert timestamp server
```

**Only for release/ signed builds** — skipped in debug.

---

### Stage 10: Build MSI Installer (Lines 267–269)
**What:** Runs WiX (Moonlight.wixproj) to create Windows installer.

```batch
msbuild -Restore %SOURCE_ROOT%\wix\Moonlight\Moonlight.wixproj
    /p:Configuration=%BUILD_CONFIG% /p:Platform=%ARCH%
```

**Output:** `wix\Moonlight\bin\Release\Moonlight.msi`

---

### Stage 11: Package Portable Executable (Lines 271–290)
**What:** Creates a self-contained .zip for portable use.

```batch
copy "%VC_REDIST_DLL_PATH%\*.dll" %DEPLOY_FOLDER%  ← Visual C++ runtime (msvcp140.dll, etc.)

if defined CI_VERSION (
    echo. > %DEPLOY_FOLDER%\portable.dat.inactive
) else (
    echo. > %DEPLOY_FOLDER%\portable.dat  ← Signals "I'm portable, use local settings"
)

7z a %INSTALLER_FOLDER%\MoonlightPortable-%ARCH%-%VERSION%.zip %DEPLOY_FOLDER%\*
```

**Output:** `MoonlightPortable-x64-6.1.0.zip` (contains entire deploy/ folder)

---

## Build Output Summary

After successful build, you have:

| Folder | Contents | Purpose |
|--------|----------|---------|
| `build-x64-debug/` | `.obj`, Makefiles, undeployed `.dll`/`.exe` | **Intermediate artifacts — safe to delete** |
| `deploy-x64-debug/` | **Moonlight.exe + all DLLs/plugins/QML** | **Ready to run or distribute** |
| `installer-x64-debug/` | `MoonlightPortable-x64-6.1.0.zip` | **Self-contained portable bundle** |
| `symbols-x64-debug/` | 22 `.pdb` files + `.zip` archive | **Debugging symbols for profilers/debuggers** |

**To run Moonlight immediately after build:**
```powershell
cd build\deploy-x64-debug
.\Moonlight.exe
```

---

## Why Total Cleanup? (Destructive by Design)

### Problem: Stale Build Artifacts
- Old `.obj` files might not relink if headers change
- Qmake regenerates Makefile; stale intermediate files can cause linker errors
- Qt files might upgrade but old plugins left behind

### Solution: Clean slate each time
- **Consistent state**: Every build identical from same source
- **No surprise linker errors**: No stale `.obj` files
- **Easy debugging**: Build artifacts map 1:1 to version.txt at build time
- **CI/CD friendly**: Release builds require reproducible binaries

### Trade-off: **Slow for iterative development**
- Full rebuild takes ~2–3 minutes even with no source changes
- Problem: Modifying one `.cpp` file requires relinking **everything**

---

## Incremental Build Strategy

To speed up development, you could:

### Option A: Use jom directly (skip qmake if Makefiles unchanged)
```powershell
cd build\build-x64-debug
..\..\..\scripts\jom.exe debug
```
**Result:** Recompiles only changed `.cpp` → generates new `.obj` files → relinks  
**Speed:** ~10 seconds if 1 file changed  
**Risk:** If you add/remove files, must re-run qmake

### Option B: Clean + qmake, but skip everything else
```powershell
# Partial rebuild (no windeployqt)
.\build-arch.bat debug
# Edit your code
# Then just:
cd build\build-x64-debug
..\..\..\scripts\jom.exe debug
cd ..\..\..
.\scripts\build-arch.bat debug  # Full build once verified
```

### Option C: Modify build-arch.bat
Create `build-arch-incremental.bat` that:
- Skips `rmdir` if Makefile exists
- Reruns qmake only if `.pro` files modified
- Skips windeployqt unless deploy folder empty

---

## File Size Summary

| Item | Size |
|------|------|
| `build-x64-debug/` (all .obj) | ~200 MB |
| `deploy-x64-debug/` (runtime + exes) | ~120 MB |
| `symbols-x64-debug/` (debug symbols) | ~45 MB |
| **Total per build** | **~365 MB** |

---

## Next Steps

1. **First build after environment setup?** → Run full `build-arch.bat debug`
2. **Edit source, test changes?** → Manually run `jom.exe debug` from build folder
3. **Ready to release?** → Run `build-arch.bat release` (same process, optimized binaries, signed)
4. **Troubleshooting linker errors?** → Delete `build-x64-debug/`, re-run full build

