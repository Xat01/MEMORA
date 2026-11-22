@echo off
REM MEMORA Windows Installation Script (CMD version)
REM Run as Administrator for best results (required for PATH modification)
REM Avoids the broken Microsoft Store Python execution alias.

setlocal enabledelayedexpansion

set PYTHON_PATH=
set INSTALL_DIR=%LOCALAPPDATA%\MEMORA
set ADD_TO_PATH=1
set SKIP_DOCKER_ASSETS=0
set SOURCE_DIR=%~dp0

echo === MEMORA Windows Installer ===
echo Install directory: %INSTALL_DIR%
echo Source directory: %SOURCE_DIR%

REM =========================================================================
REM Find Python - Avoid Microsoft Store alias
REM =========================================================================
echo Checking Python...

REM Strategy 1: Use 'py' launcher (most reliable on Windows)
py --version >nul 2>&1
if not errorlevel 1 (
    for /f "tokens=2 delims=. " %%a in ('py -c "import sys; print(sys.version_info.major, sys.version_info.minor)" 2^>nul') do (
        set PY_MAJOR=%%a
        set PY_MINOR=%%b
    )
    if %PY_MAJOR% EQU 3 if %PY_MINOR% GEQ 10 (
        set PYTHON_PATH=py
        echo Found Python %PY_MAJOR%.%PY_MINOR% via 'py' launcher
        goto :python_found
    )
)

REM Strategy 2: Check common installation paths (avoid WindowsApps)
set COMMON_PATHS=^
"%LOCALAPPDATA%\Python\python.exe" ^
"%LOCALAPPDATA%\Programs\Python\Python312\python.exe" ^
"%LOCALAPPDATA%\Programs\Python\Python311\python.exe" ^
"%LOCALAPPDATA%\Programs\Python\Python310\python.exe" ^
"C:\Python312\python.exe" ^
"C:\Python311\python.exe" ^
"C:\Python310\python.exe" ^
"C:\Program Files\Python312\python.exe" ^
"C:\Program Files\Python311\python.exe" ^
"C:\Program Files\Python310\python.exe" ^
"C:\Program Files (x86)\Python312\python.exe" ^
"C:\Program Files (x86)\Python311\python.exe" ^
"C:\Program Files (x86)\Python310\python.exe"

for %%P in (%COMMON_PATHS%) do (
    if defined PYTHON_PATH goto :python_found
    %%P --version >nul 2>&1
    if not errorlevel 1 (
        for /f "tokens=2 delims=. " %%a in ('%%P -c "import sys; print(sys.version_info.major, sys.version_info.minor)" 2^>nul') do (
            set PY_MAJOR=%%a
            set PY_MINOR=%%b
        )
        if %PY_MAJOR% EQU 3 if %PY_MINOR% GEQ 10 (
            set PYTHON_PATH=%%P
            echo Found Python %PY_MAJOR%.%PY_MINOR% at %%P
            goto :python_found
        )
    )
)

REM Strategy 3: Check py launcher for specific versions
if not defined PYTHON_PATH (
    for /f "tokens=*" %%v in ('py --list 2^>nul ^| findstr /R "^ *-3\.[1-9][0-9]*$"') do (
        if not defined PYTHON_PATH (
            set PYTHON_PATH=py %%v
            echo Found Python %%v via 'py' launcher
            goto :python_found
        )
    )
)

:python_found
if not defined PYTHON_PATH (
    echo ERROR: No suitable Python 3.10+ installation found.
    echo Please install Python 3.10+ from https://python.org
    echo Or set PYTHON_PATH environment variable before running.
    exit /b 1
)

echo Using Python: %PYTHON_PATH%

REM Ensure pip
echo Ensuring pip...
%PYTHON_PATH% -m ensurepip --upgrade >nul 2>&1
%PYTHON_PATH% -m pip install --upgrade pip >nul 2>&1

REM Create install directory
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"

REM Copy project files (exclude build artifacts, runtime data, and sensitive .env)
echo Copying project files...
REM Create exclude file
echo .venv>%TEMP%\memora_exclude.txt
echo __pycache__>>%TEMP%\memora_exclude.txt
echo *.pyc>>%TEMP%\memora_exclude.txt
echo .pytest_cache>>%TEMP%\memora_exclude.txt
echo .git>>%TEMP%\memora_exclude.txt
echo data>>%TEMP%\memora_exclude.txt
echo logs>>%TEMP%\memora_exclude.txt
echo *.db>>%TEMP%\memora_exclude.txt
echo *.db-journal>>%TEMP%\memora_exclude.txt
echo .env>>%TEMP%\memora_exclude.txt
xcopy /E /I /Y /Q /EXCLUDE:%TEMP%\memora_exclude.txt "%SOURCE_DIR%*" "%INSTALL_DIR%\"
del %TEMP%\memora_exclude.txt

REM Initialize configuration (templates only, preserve user config)
echo Initializing configuration...
if not exist "%INSTALL_DIR%\.env.docker" (
    if exist "%SOURCE_DIR%\.env.docker" (
        copy /Y "%SOURCE_DIR%\.env.docker" "%INSTALL_DIR%\.env.docker" >nul
        echo Copied .env.docker template
    ) else (
        echo WARNING: Source .env.docker not found
    )
) else (
    echo .env.docker already exists, preserving existing
)

if not exist "%INSTALL_DIR%\.env.example" (
    if exist "%SOURCE_DIR%\.env.example" (
        copy /Y "%SOURCE_DIR%\.env.example" "%INSTALL_DIR%\.env.example" >nul
        echo Copied .env.example template
    ) else (
        echo WARNING: Source .env.example not found
    )
) else (
    echo .env.example already exists, preserving existing
)

if not exist "%INSTALL_DIR%\.env" (
    if exist "%INSTALL_DIR%\.env.example" (
        copy /Y "%INSTALL_DIR%\.env.example" "%INSTALL_DIR%\.env" >nul
        echo Created .env from .env.example template
        echo IMPORTANT: Edit .env and set VAULT_PATH to your Obsidian vault
    ) else (
        echo WARNING: No .env.example template available to create .env
    )
) else (
    echo .env already exists, preserving existing configuration
)

REM Verify required Docker assets
if %SKIP_DOCKER_ASSETS% EQU 0 (
    echo Verifying required Docker assets...
    set REQUIRED_ASSETS=Dockerfile docker-compose.yml docker-entrypoint.sh requirements.txt pyproject.toml memora .env.docker .env.example
    set MISSING_COUNT=0
    for %%A in (%REQUIRED_ASSETS%) do (
        if not exist "%INSTALL_DIR%\%%A" (
            echo ERROR: Missing required asset: %%A
            set /a MISSING_COUNT+=1
        ) else (
            echo Found: %%A
        )
    )
    if %MISSING_COUNT% GTR 0 (
        echo ERROR: Missing %MISSING_COUNT% required Docker asset(s)
        exit /b 1
    )
    echo All required Docker assets verified
)

REM Create virtual environment
echo Creating virtual environment...
%PYTHON_PATH% -m venv "%INSTALL_DIR%\.venv"
if not exist "%INSTALL_DIR%\.venv\Scripts\python.exe" (
    echo ERROR: Virtual environment creation failed
    exit /b 1
)
echo Virtual environment created

REM Install MEMORA
echo Installing MEMORA package...
"%INSTALL_DIR%\.venv\Scripts\pip.exe" install -e "%INSTALL_DIR%" --no-cache-dir
if errorlevel 1 (
    echo ERROR: MEMORA package installation failed
    exit /b 1
)
echo MEMORA package installed

REM Verify console script was generated
if exist "%INSTALL_DIR%\.venv\Scripts\memora.exe" (
    echo Console script verified in venv
) else if exist "%INSTALL_DIR%\.venv\Scripts\memora" (
    echo Console script verified in venv
) else (
    echo WARNING: Console script 'memora' not found in venv Scripts
)

REM Create wrapper scripts
if not exist "%INSTALL_DIR%\scripts" mkdir "%INSTALL_DIR%\scripts"

echo @echo off > "%INSTALL_DIR%\scripts\memora.bat"
echo set MEMORA_HOME=%INSTALL_DIR% >> "%INSTALL_DIR%\scripts\memora.bat"
echo call "%INSTALL_DIR%\.venv\Scripts\activate.bat" ^>nul 2^>^&1 >> "%INSTALL_DIR%\scripts\memora.bat"
echo memora %%* >> "%INSTALL_DIR%\scripts\memora.bat"

echo # MEMORA PowerShell Wrapper > "%INSTALL_DIR%\scripts\memora.ps1"
echo $env:MEMORA_HOME = "%INSTALL_DIR%" >> "%INSTALL_DIR%\scripts\memora.ps1"
echo ^& "%INSTALL_DIR%\.venv\Scripts\Activate.ps1" ^> $null 2^>^&1 >> "%INSTALL_DIR%\scripts\memora.ps1"
echo ^& memora @args >> "%INSTALL_DIR%\scripts\memora.ps1"

echo Created wrapper scripts in %INSTALL_DIR%\scripts

REM Add to PATH
set SCRIPTS_DIR=%INSTALL_DIR%\scripts
set CURRENT_PATH=
for /f "usebackq tokens=2*" %%a in (`reg query "HKCU\Environment" /v PATH 2^>nul`) do set CURRENT_PATH=%%b

if not "!CURRENT_PATH:%SCRIPTS_DIR%=!"=="!CURRENT_PATH!" (
    echo Already in PATH
) else (
    set NEW_PATH=!CURRENT_PATH!;%SCRIPTS_DIR%
    reg add "HKCU\Environment" /v PATH /t REG_EXPAND_SZ /d "!NEW_PATH!" /f >nul
    echo Added to user PATH
    echo NOTE: Restart your terminal for changes to take effect
)

REM Verify installation
echo Verifying installation...
if not exist "%SCRIPTS_DIR%\memora.bat" (
    echo ERROR: memora.bat wrapper missing
    exit /b 1
)
if not exist "%SCRIPTS_DIR%\memora.ps1" (
    echo ERROR: memora.ps1 wrapper missing
    exit /b 1
)

REM Verify using venv python directly (works in current session)
"%INSTALL_DIR%\.venv\Scripts\python.exe" -m memora.cli --version
if errorlevel 1 (
    echo ERROR: MEMORA CLI verification failed
    exit /b 1
)
echo MEMORA CLI verified
echo Installation verification passed

echo.
echo === Installation Complete ===
echo.
echo Next steps:
echo   1. Restart your terminal
echo   2. Configure your vault: edit %INSTALL_DIR%\.env and set VAULT_PATH to your Obsidian vault
echo   3. Run: memora --start
echo.
echo For Docker-based deployment, ensure Docker Desktop is installed and running.
echo.
echo Installed to: %INSTALL_DIR%
echo Virtual env:  %INSTALL_DIR%\.venv
echo Scripts dir:  %INSTALL_DIR%\scripts (added to PATH)

pause