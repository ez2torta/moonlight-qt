# Build Helper: Faster compilation during development
# Usage: .\build-helper.ps1 [mode] [arch] [config]

param(
    [ValidateSet('full', 'compile', 'deploy', 'run', 'help')]
    [string]$Mode = 'full',
    
    [ValidateSet('x64', 'x86', 'arm64', 'arm')]
    [string]$Arch = 'x64',
    
    [ValidateSet('debug', 'release')]
    [string]$Config = 'debug'
)

$ROOT = Split-Path -Parent $MyInvocation.MyCommand.Path
$BUILD_FOLDER = "$ROOT\build\build-$Arch-$Config"
$DEPLOY_FOLDER = "$ROOT\build\deploy-$Arch-$Config"
$EXE_PATH = "$DEPLOY_FOLDER\Moonlight.exe"
$SCRIPTS_FOLDER = "$ROOT\scripts"

function Show-Help {
    @"
Moonlight-Qt Build Helper
==========================

USAGE:
  .\build-helper.ps1 [mode] [arch] [config]

MODES:
  full      Complete build from scratch (like build-arch.bat)
  compile   Fast: compile only changed .cpp files (skip deploy)
  deploy    Re-run windeployqt and copy DLLs (use after Qt upgrade)
  run       Build + execute Moonlight.exe
  help      Show this message

DEFAULTS:
  arch   = x64
  config = debug

EXAMPLES:
  .\build-helper.ps1 compile          # Fast iterate: edit .cpp → compile
  .\build-helper.ps1 full x64 debug   # Full build (resets everything)
  .\build-helper.ps1 run              # Build + launch
  .\build-helper.ps1 compile arm64    # Compile for ARM64

WORKFLOW FOR DEVELOPMENT:
  1. First time: .\build-helper.ps1 full
  2. Edit app/main.cpp
  3. Test: .\build-helper.ps1 compile
  4. If link errors: .\build-helper.ps1 full
  5. Ready to ship: .\scripts\build-arch.bat release

"@
}

function Run-Command {
    param([string]$Cmd, [string]$Description)
    Write-Host "▶ $Description" -ForegroundColor Cyan
    Invoke-Expression $Cmd
    if ($LASTEXITCODE -ne 0) {
        Write-Host "✗ Failed: $Description (exit code $LASTEXITCODE)" -ForegroundColor Red
        exit 1
    }
    Write-Host "✓ Done" -ForegroundColor Green
    Write-Host ""
}

function Build-Full {
    Write-Host "🔄 FULL BUILD: $Arch $Config" -ForegroundColor Yellow
    Push-Location $ROOT
    Run-Command ".\scripts\build-arch.bat $Arch $Config" "Running build-arch.bat"
    Pop-Location
}

function Build-CompileOnly {
    if (-not (Test-Path $BUILD_FOLDER)) {
        Write-Host "⚠ Build folder not found. Run 'full' first." -ForegroundColor Yellow
        Build-Full
        return
    }
    
    Write-Host "⚡ COMPILE ONLY: $Arch $Config (incremental)" -ForegroundColor Yellow
    
    # Check if Makefiles exist
    $Makefile = "$BUILD_FOLDER\Moonlight.exe.Makefile"
    if (-not (Test-Path $Makefile)) {
        Write-Host "⚠ Makefile not found. Running qmake..." -ForegroundColor Yellow
        Push-Location $BUILD_FOLDER
        & "$ROOT\scripts\jom.exe" qmake
        if ($LASTEXITCODE -ne 0) {
            Write-Host "✗ qmake failed" -ForegroundColor Red
            Pop-Location
            exit 1
        }
        Pop-Location
    }
    
    # Compile with jom
    Push-Location $BUILD_FOLDER
    Run-Command "$ROOT\scripts\jom.exe $Config" "Compiling with jom.exe"
    Pop-Location
    
    Write-Host "ℹ Next: Run 'deploy' to refresh DLLs, or 'run' to test immediately" -ForegroundColor Magenta
}

function Build-Deploy {
    if (-not (Test-Path "$BUILD_FOLDER\app\$Config\Moonlight.exe")) {
        Write-Host "✗ Compiled Moonlight.exe not found!" -ForegroundColor Red
        exit 1
    }
    
    Write-Host "📦 DEPLOY: Updating DLLs and Qt files" -ForegroundColor Yellow
    
    # Remove old deploy folder
    if (Test-Path $DEPLOY_FOLDER) {
        Write-Host "  Removing old deploy folder..."
        Remove-Item -Recurse -Force $DEPLOY_FOLDER
    }
    mkdir $DEPLOY_FOLDER | Out-Null
    
    # Copy dependencies
    Push-Location $ROOT
    Run-Command "Copy-Item '$ROOT\libs\windows\lib\$Arch\*.dll' '$DEPLOY_FOLDER\'" "Copying external libs"
    Run-Command "Copy-Item '$BUILD_FOLDER\AntiHooking\$Config\AntiHooking.dll' '$DEPLOY_FOLDER\'" "Copying AntiHooking"
    Run-Command "Copy-Item '$ROOT\app\SDL_GameControllerDB\gamecontrollerdb.txt' '$DEPLOY_FOLDER\'" "Copying game controller DB"
    Pop-Location
    
    # Run windeployqt
    Push-Location $ROOT
    $WINDEPLOYQT = "windeployqt.exe"
    Write-Host "  Running windeployqt..." -ForegroundColor Gray
    & $WINDEPLOYQT --dir $DEPLOY_FOLDER --$Config --qmldir app\gui --no-opengl-sw --no-compiler-runtime --no-sql --no-system-d3d-compiler --no-system-dxc-compiler --skip-plugin-types qmltooling,generic --no-ffmpeg --no-quickcontrols2fusion --no-quickcontrols2imagine --no-quickcontrols2universal --no-quickcontrols2fusionstyleimpl --no-quickcontrols2imaginestyleimpl --no-quickcontrols2universalstyleimpl --no-quickcontrols2windowsstyleimpl --no-quickcontrols2fluentwinui3styleimpl "$BUILD_FOLDER\app\$Config\Moonlight.exe"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "✗ windeployqt failed" -ForegroundColor Red
        Pop-Location
        exit 1
    }
    Pop-Location
    
    # Copy final exe
    Copy-Item "$BUILD_FOLDER\app\$Config\Moonlight.exe" "$DEPLOY_FOLDER\" -Force
    
    Write-Host "✓ Deploy complete. Ready in: $DEPLOY_FOLDER" -ForegroundColor Green
}

function Build-And-Run {
    Write-Host "🚀 BUILD + RUN" -ForegroundColor Yellow
    
    # Quick compile check
    if (-not (Test-Path "$BUILD_FOLDER\app\$Config\Moonlight.exe")) {
        Build-Full
    } else {
        Build-CompileOnly
    }
    
    # Check if deploy folder recent
    if (-not (Test-Path $EXE_PATH)) {
        Build-Deploy
    }
    
    # Launch
    Write-Host "▶ Launching: $EXE_PATH" -ForegroundColor Cyan
    & $EXE_PATH
}

# Main dispatcher
switch ($Mode) {
    'help'    { Show-Help }
    'full'    { Build-Full }
    'compile' { Build-CompileOnly }
    'deploy'  { Build-Deploy }
    'run'     { Build-And-Run }
    default   { Show-Help }
}

Write-Host "Done!" -ForegroundColor Green
