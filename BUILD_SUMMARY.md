# Build Results Summary & Answers

## Your 3 Questions Answered

### Q1: What's in build/?

```
build/
├── build-x64-debug/        (38 items)   ← Intermediate compilation objects (.obj, Makefiles)
│   ├── AntiHooking/        Compiled DLL and objects
│   ├── app/                Moonlight.exe (UNDEPLOYED - needs windeployqt)
│   ├── h264bitstream/      Compiled lib
│   ├── moonlight-common-c/ Compiled objects
│   └── qmdnsengine/        Compiled lib
│
├── deploy-x64-debug/       (49 files)   ← ✓ READY TO RUN
│   ├── Moonlight.exe                   (1.0 MB executable)
│   ├── Qt6*.dll            (8 DLLs: Core, Gui, Qml, Quick, Network, Svg, Sql, Widgets)
│   ├── av*.dll             (3 DLLs: avcodec-62, avutil-60, swscale-9 from FFmpeg)
│   ├── libssl-3-x64.dll    (OpenSSL crypto)
│   ├── libcrypto-3-x64.dll (OpenSSL utilities)
│   ├── SDL2.dll            (Input/audio)
│   ├── SDL2_ttf.dll        (Font rendering)
│   ├── opus.dll            (Audio codec)
│   ├── libplacebo-360.dll  (GPU rendering)
│   ├── dav1d.dll           (AV1 decoder)
│   ├── AntiHooking.dll     (Security)
│   ├── gamecontrollerdb.txt (SDL GamePad mappings)
│   ├── plugins/            (Qt platform, image format, icon engines)
│   ├── qml/                (Qt Quick 2D UI framework)
│   ├── translations/       (i18n support for Qt)
│   └── [other Qt support files]
│
├── installer-x64-debug/    (1+ items) ← Portable distribution
│   └── MoonlightPortable-x64-6.1.0.zip (deploy-x64-debug/ as archive)
│
└── symbols-x64-debug/      (22 PDB files)
    ├── *.pdb               (Debug symbols for each component)
    └── MoonlightDebuggingSymbols-x64-6.1.0.zip
```

**Key Facts:**
- **Safe to delete:** `build-x64-debug/` (intermediate, regenerated on next build)
- **Never delete:** `deploy-x64-debug/` (contains executable + runtime dependencies)
- **To run immediately:** `build\deploy-x64-debug\Moonlight.exe`

---

### Q2: Can agent automate parts of the build?

**YES** ✓ Created **build-helper.ps1** with 5 modes:

| Mode | Time | Use Case |
|------|------|----------|
| `full` | 2–3 min | Complete rebuild (stage 1-11) |
| `compile` | 10 sec | Fast iteration: edit .cpp → test |
| `deploy` | 5 sec | Refresh DLLs (rarely needed) |
| `run` | varies | Build + launch Moonlight |
| `help` | – | Show usage |

**Usage Examples:**
```powershell
# First time: full build
.\build-helper.ps1 full

# Development loop (10 seconds each):
# Edit app/gui/main.qml
.\build-helper.ps1 compile

# If link errors, do clean build
.\build-helper.ps1 full

# Ready to test
.\build-helper.ps1 run
```

**What it does:**
- Detects if build folder already exists (skips destructive cleanup if not needed)
- Runs jom directly for faster recompilation
- Automatically calls windeployqt only when needed
- Manages Qt DLL copying without re-running full build-arch.bat

---

### Q3: Does re-running build-arch.bat update or overwrite?

**COMPLETE OVERWRITE** 🔄

```batch
echo Cleaning output directories
rmdir /s /q %DEPLOY_FOLDER%       ← ✗ Deletes deployable binaries
rmdir /s /q %BUILD_FOLDER%        ← ✗ Deletes all .obj files
rmdir /s /q %INSTALLER_FOLDER%    ← ✗ Deletes portable .zip
rmdir /s /q %SYMBOLS_FOLDER%      ← ✗ Deletes .pdb symbols
```

Then recreates everything from scratch.

**Timeline of a re-run:**
```
[Existing build-x64-debug/]
        ↓ (run build-arch.bat again)
        ↓ rmdir /s /q → DESTROYED
[Empty folder]
        ↓ mkdir
        ↓ qmake (regenerates Makefile)
        ↓ jom.exe debug (recompiles all)
        ↓ windeployqt (copies all DLLs again)
        ↓ New build-x64-debug/ ← Fresh artifacts
```

---

## Why Destructive?

**Pros:**
- ✓ **Guaranteed correctness** — no stale linker state
- ✓ **Version consistency** — all artifacts match version.txt timestamp
- ✓ **CI/CD friendly** — reproducible builds for releases
- ✓ **No surprise linker errors** — old .obj files never cause havoc

**Cons:**
- ✗ **Slow for iteration** — even if 1 file changed, everything recompiles
- ✗ **Development friction** — 2–3 min wait between edits

**Solution:** Use `build-helper.ps1 compile` instead (10 sec per iteration).

---

## Recommended Development Workflow

### Setup (One-time)
```powershell
# Qt already installed? ✓ (you did this)
# VS 2022 Build Tools installed? ✓ (you did this)

# First build:
.\build-helper.ps1 full
# Output: build\deploy-x64-debug\Moonlight.exe ✓ READY
```

### Daily Loop (Fast)
```powershell
# Edit one file
code app/gui/main.qml
# Compile only (not full build)
.\build-helper.ps1 compile      # 10 sec ← FAST
# Test
.\build-helper.ps1 run          # Launches immediately

# If you get linker errors:
.\build-helper.ps1 full         # 2–3 min ← Clean rebuild
```

### Before Committing
```powershell
# Verify full clean build works
.\build-helper.ps1 full
```

### Release Build
```powershell
# Use original script (creates .msi + .zip)
.\scripts\build-arch.bat release
```

---

## Fallback If build-helper.ps1 Fails

**If PowerShell script issues, manual commands are:**

```powershell
# Setup once
cd build\build-x64-debug

# Fast recompile loop:
..\..\..\scripts\jom.exe debug    # 10 sec compile

# If linking still fails:
cd ..
rm build-x64-debug -r -force      # Nuke it
cd ..
.\scripts\build-arch.bat debug    # Full rebuild
```

---

## Next Steps

1. **Test compiled Moonlight:**
   ```powershell
   .\build\deploy-x64-debug\Moonlight.exe
   ```
   Should launch the streaming client.

2. **Ready for feature development?**
   - Review [PLAN_INPUT_RECORDER.md](PLAN_INPUT_RECORDER.md) for architecture
   - Edit `app/streaming/input/` files
   - Use `.\build-helper.ps1 compile` for fast iteration

3. **Questions about build system?**
   - See [BUILD_PROCESS_EXPLAINED.md](BUILD_PROCESS_EXPLAINED.md) for stage-by-stage breakdown
   - Each build folder documented

