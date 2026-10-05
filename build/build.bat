@echo off
setlocal
cd /d "%~dp0.."

echo ========================================================
echo       EnderBridge Client Build Tool
echo ========================================================
echo.

where dotnet >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [ERROR] .NET SDK not found. Please install .NET 10 SDK: https://dotnet.microsoft.com/
    pause
    exit /b 1
)

for /f "tokens=*" %%i in ('dotnet --version') do set "DOTNET_VER=%%i"
echo [*] .NET SDK: %DOTNET_VER%
echo [*] Project Root: %cd%
echo.

set "CHOICE=%~1"
if not "%CHOICE%"=="" goto :check_choice

echo Build options:
echo  1. Publish Windows Desktop Release [Single File EXE] - Recommended
echo  2. Build Windows Desktop Debug
echo  3. Build Android APK Release
echo  4. Clean build cache
echo.
set /p CHOICE=Please select [1-4, Default 1]: 

:check_choice
if "%CHOICE%"=="" set "CHOICE=1"
if "%CHOICE%"=="1" goto :do_desktop
if "%CHOICE%"=="2" goto :do_debug
if "%CHOICE%"=="3" goto :do_android
if "%CHOICE%"=="4" goto :do_clean
goto :do_desktop

:do_desktop
echo.
echo [*] Publishing Windows Desktop Single File (Release)...
dotnet publish app\src\EnderBridge.App.Desktop\EnderBridge.App.Desktop.csproj -c Release -r win-x64 --self-contained true -p:PublishSingleFile=true -o dist\desktop
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Build failed! Check errors above.
    pause
    exit /b %ERRORLEVEL%
)

copy /y dist\desktop\EnderBridge.exe build\EnderBridge.exe >nul 2>nul

echo.
echo ========================================================
echo [SUCCESS] Windows Desktop build complete!
echo Output:
echo   1. %cd%\dist\desktop\EnderBridge.exe
echo   2. %cd%\build\EnderBridge.exe
echo ========================================================
echo.
exit /b 0

:do_debug
echo.
echo [*] Building Windows Desktop (Debug)...
dotnet build app\src\EnderBridge.App.Desktop\EnderBridge.App.Desktop.csproj -c Debug
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Debug build failed!
    pause
    exit /b %ERRORLEVEL%
)
echo.
echo [SUCCESS] Debug build complete!
exit /b 0

:do_android
echo.
echo [*] Building Android APK (Release)...
dotnet build app\src\EnderBridge.App.Android\EnderBridge.App.Android.csproj -c Release
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Android build failed. Ensure .NET Android workload is installed:
    echo   dotnet workload install android
    pause
    exit /b %ERRORLEVEL%
)
echo.
echo [SUCCESS] Android build complete!
exit /b 0

:do_clean
echo.
echo [*] Cleaning build cache...
dotnet clean app\EnderBridge.App.sln
if exist "dist" rmdir /s /q "dist"
if exist "build\EnderBridge.exe" del /f /q "build\EnderBridge.exe"
echo [SUCCESS] Clean completed!
exit /b 0
