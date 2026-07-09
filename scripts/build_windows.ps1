# =============================================================================
# ID:       CAT-DETECTOR-BUILD-WIN-001
# Purpose:  Local Windows build script — installs dependencies, builds the
#           standalone cat-detector.exe and cat-detector-status-tray.exe with PyInstaller, and (if Inno Setup 6
#           is present) packages it into a GUI installer .exe.
# Platform: Windows 10/11, PowerShell 5.1+
# Usage:    From the project root:  .\scripts\build_windows.ps1
# Output:   dist\cat-detector.exe
#           dist\cat-detector-status-tray.exe
#           dist\cat-detector-installer-2.0.0-windows-x64.exe  (if ISCC found)
# =============================================================================

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "=== Cat Detector  Windows Build Script  v2.0.0 ===" -ForegroundColor Cyan
Write-Host ""

# ---------------------------------------------------------------------------
# 1. Verify Python is available
# ---------------------------------------------------------------------------
try {
    $pyver = python --version 2>&1
    Write-Host "Python: $pyver" -ForegroundColor Green
} catch {
    Write-Error "Python not found. Install Python 3.11+ from https://python.org"
    exit 1
}

# ---------------------------------------------------------------------------
# 2. Install / upgrade pip build dependencies
# ---------------------------------------------------------------------------
Write-Host "`n[1/3] Installing build dependencies..." -ForegroundColor Yellow
pip install --upgrade pyinstaller pynput winotify pystray pillow

# ---------------------------------------------------------------------------
# 3. Build the standalone exes with PyInstaller
# ---------------------------------------------------------------------------
Write-Host "`n[2/3] Building Windows executables with PyInstaller..." -ForegroundColor Yellow

if ((-not (Test-Path "cat_detector.spec")) -or (-not (Test-Path "cat_status_tray.spec"))) {
    Write-Error "Required PyInstaller spec files not found. Run this script from the project root."
    exit 1
}

pyinstaller --noconfirm --clean cat_detector.spec
pyinstaller --noconfirm --clean cat_status_tray.spec

if (-not (Test-Path "dist\cat-detector.exe")) {
    Write-Error "PyInstaller build failed — dist\cat-detector.exe not produced."
    exit 1
}
if (-not (Test-Path "dist\cat-detector-status-tray.exe")) {
    Write-Error "PyInstaller build failed — dist\cat-detector-status-tray.exe not produced."
    exit 1
}

$exeSize = (Get-Item "dist\cat-detector.exe").Length / 1MB
Write-Host "  Built: dist\cat-detector.exe  ($([math]::Round($exeSize, 1)) MB)" -ForegroundColor Green
$traySize = (Get-Item "dist\cat-detector-status-tray.exe").Length / 1MB
Write-Host "  Built: dist\cat-detector-status-tray.exe  ($([math]::Round($traySize, 1)) MB)" -ForegroundColor Green

# ---------------------------------------------------------------------------
# 4. Build the installer with Inno Setup (optional)
# ---------------------------------------------------------------------------
Write-Host "`n[3/3] Building Windows installer with Inno Setup..." -ForegroundColor Yellow

$iscc = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"

if (Test-Path $iscc) {
    & $iscc "installer\cat-detector.iss"
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Inno Setup build failed (exit code $LASTEXITCODE)."
        exit $LASTEXITCODE
    }
    $installer = Get-ChildItem "dist\cat-detector-installer-*-windows-x64.exe" |
                 Select-Object -First 1
    if ($installer) {
        $installerSize = $installer.Length / 1MB
        Write-Host "  Built: $($installer.Name)  ($([math]::Round($installerSize, 1)) MB)" -ForegroundColor Green
    }
} else {
    Write-Host "  Inno Setup 6 not found at: $iscc" -ForegroundColor DarkYellow
    Write-Host "  Download from https://www.innosetup.com/ to build the installer." -ForegroundColor DarkYellow
    Write-Host "  Standalone exes are still available at dist\cat-detector.exe and dist\cat-detector-status-tray.exe" -ForegroundColor Yellow
}

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "=== Build complete ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "Produced artifacts:" -ForegroundColor White
Get-ChildItem "dist\*.exe" | ForEach-Object {
    $sz = $_.Length / 1MB
    Write-Host ("  {0,-55} {1,6:F1} MB" -f $_.Name, $sz) -ForegroundColor Green
}
Write-Host ""
Write-Host "Usage examples:" -ForegroundColor White
Write-Host "  dist\cat-detector.exe                         # default (lock OFF, medium sensitivity)"
Write-Host "  dist\cat-detector.exe --sensitivity high      # dainty steppers"
Write-Host "  dist\cat-detector.exe --toddler               # toddler mode"
Write-Host "  dist\cat-detector.exe --lock --sound          # lock + notification + meow"
Write-Host "  dist\cat-detector-status-tray.exe             # tray status monitor"
Write-Host ""
