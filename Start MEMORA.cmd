@echo off
REM =========================================================================
REM MEMORA Desktop Startup Launcher
REM =========================================================================
REM This script locates the installed MEMORA runtime and starts it.
REM It can be pinned to Start Menu or Taskbar for one-click startup.
REM =========================================================================

setlocal enabledelayedexpansion

REM -------------------------------------------------------------------------
REM Configuration
REM -------------------------------------------------------------------------
set MEMORA_INSTALL_DIR=%LOCALAPPDATA%\MEMORA
set MEMORA_EXE=%MEMORA_INSTALL_DIR%\scripts\memora.bat
set MEMORA_PS1=%MEMORA_INSTALL_DIR%\scripts\memora.ps1

REM -------------------------------------------------------------------------
REM Colors for output
REM -------------------------------------------------------------------------
for /f %%a in ('echo prompt $E ^| cmd') do set ESC=%%a
set RED=%ESC%[91m
set GREEN=%ESC%[92m
set YELLOW=%ESC%[93m
set CYAN=%ESC%[96m
set RESET=%ESC%[0m

REM -------------------------------------------------------------------------
REM Helper functions
REM -------------------------------------------------------------------------
:print_info
echo %CYAN%[INFO]%RESET% %*
goto :eof

:print_ok
echo %GREEN%[OK]%RESET% %*
goto :eof

:print_warn
echo %YELLOW%[WARN]%RESET% %*
goto :eof

:print_error
echo %RED%[ERROR]%RESET% %*
goto :eof

:print_header
echo.
echo %CYAN%=========================================%RESET%
echo %CYAN%  MEMORA Desktop Startup Launcher%RESET%
echo %CYAN%=========================================%RESET%
echo.
goto :eof

REM -------------------------------------------------------------------------
REM Main execution
REM -------------------------------------------------------------------------
call :print_header

REM Check if MEMORA is installed
if not exist "%MEMORA_INSTALL_DIR%\" (
    call :print_error "MEMORA not found at %MEMORA_INSTALL_DIR%"
    call :print_info "Please run the installer first: install.ps1 or install.bat"
    pause
    exit /b 1
)

call :print_ok "Found MEMORA installation at %MEMORA_INSTALL_DIR%"

REM Check for wrapper scripts
if not exist "%MEMORA_EXE%" (
    call :print_error "Wrapper script not found: %MEMORA_EXE%"
    call :print_info "Installation may be corrupted. Please reinstall."
    pause
    exit /b 1
)

call :print_ok "Found startup script: %MEMORA_EXE%"

REM Check if Docker Desktop is running (optional but recommended)
call :print_info "Checking Docker Desktop..."
docker info >nul 2>&1
if errorlevel 1 (
    call :print_warn "Docker Desktop is not running"
    call :print_info "MEMORA will attempt to start Docker Desktop automatically"
) else (
    call :print_ok "Docker Desktop is running"
)

REM Check if Ollama is running (for host mode)
call :print_info "Checking Ollama..."
ollama list >nul 2>&1
if errorlevel 1 (
    call :print_warn "Ollama is not running"
    call :print_info "MEMORA will attempt to start Ollama automatically (host mode)"
) else (
    call :print_ok "Ollama is running"
)

REM -------------------------------------------------------------------------
REM Start MEMORA
REM -------------------------------------------------------------------------
echo.
call :print_info "Starting MEMORA with automatic dependency management..."
echo.

REM Execute MEMORA startup with full preflight validation
"%MEMORA_EXE%" --start

REM Capture exit code
set EXIT_CODE=%ERRORLEVEL%

echo.
if %EXIT_CODE% EQU 0 (
    call :print_ok "MEMORA started successfully!"
    call :print_info "MEMORA is ready at http://127.0.0.1:8080"
) else (
    call :print_error "MEMORA startup failed with exit code %EXIT_CODE%"
    call :print_info "Check the output above for details"
)

echo.
pause
exit /b %EXIT_CODE%