@echo off
setlocal
cd /d "%~dp0"

echo Starting project...
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"
set "PROJECT_EXIT_CODE=%ERRORLEVEL%"

echo.
if not "%PROJECT_EXIT_CODE%"=="0" (
    echo Startup failed. Exit code: %PROJECT_EXIT_CODE%
    echo Check Docker Desktop, JDK 17, pnpm, and uv.
) else (
    echo Startup command completed.
    echo Open: http://127.0.0.1:16552
)

echo.
pause
endlocal & exit /b %PROJECT_EXIT_CODE%
