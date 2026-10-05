param (
    [ValidateSet("desktop", "debug", "android", "clean")]
    [string]$Target = "desktop"
)

$ErrorActionPreference = "Stop"
$BuildDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir = Split-Path -Parent $BuildDir

Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "             EnderBridge Client Build Tool              " -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "[*] Root Directory: $RootDir" -ForegroundColor Gray

try {
    $dotnetVer = dotnet --version
    Write-Host "[*] Detected .NET SDK: $dotnetVer" -ForegroundColor Green
} catch {
    Write-Error "[ERROR] .NET SDK not found. Please install .NET 10 SDK: https://dotnet.microsoft.com/"
}

$DistDir = Join-Path $RootDir "dist"

switch ($Target) {
    "clean" {
        Write-Host "`n[*] Cleaning build artifacts..." -ForegroundColor Yellow
        dotnet clean (Join-Path $RootDir "app\EnderBridge.App.sln")
        if (Test-Path $DistDir) {
            Remove-Item -Recurse -Force $DistDir
        }
        Write-Host "[SUCCESS] Clean completed!" -ForegroundColor Green
    }

    "debug" {
        Write-Host "`n[*] Building Windows Desktop app (Debug)..." -ForegroundColor Yellow
        $proj = Join-Path $RootDir "app\src\EnderBridge.App.Desktop\EnderBridge.App.Desktop.csproj"
        dotnet build $proj -c Debug
        Write-Host "`n[SUCCESS] Debug build completed!" -ForegroundColor Green
    }

    "desktop" {
        Write-Host "`n[*] Building and publishing Windows Desktop app (Release)..." -ForegroundColor Yellow
        $proj = Join-Path $RootDir "app\src\EnderBridge.App.Desktop\EnderBridge.App.Desktop.csproj"
        $out = Join-Path $DistDir "desktop"
        
        dotnet publish $proj -c Release -r win-x64 --self-contained true -p:PublishSingleFile=true -o $out
        Copy-Item -Path (Join-Path $out "EnderBridge.exe") -Destination (Join-Path $BuildDir "EnderBridge.exe") -Force -ErrorAction SilentlyContinue

        Write-Host "`n========================================================" -ForegroundColor Green
        Write-Host "[SUCCESS] Windows Desktop app published successfully!" -ForegroundColor Green
        Write-Host "Output: $(Join-Path $out 'EnderBridge.App.Desktop.exe')" -ForegroundColor White
        Write-Host "========================================================" -ForegroundColor Green
    }

    "android" {
        Write-Host "`n[*] Building Android APK (Release)..." -ForegroundColor Yellow
        $proj = Join-Path $RootDir "app\src\EnderBridge.App.Android\EnderBridge.App.Android.csproj"
        
        try {
            dotnet build $proj -c Release
            Write-Host "`n[SUCCESS] Android APK built successfully!" -ForegroundColor Green
        } catch {
            Write-Warning "Android build failed. Ensure .NET Android workload is installed: dotnet workload install android"
        }
    }
}
