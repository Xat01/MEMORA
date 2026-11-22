<#
.SYNOPSIS
    MEMORA Windows Installation Script

.DESCRIPTION
    Installs MEMORA CLI and dependencies on Windows.
    Creates a persistent installation in %LOCALAPPDATA%\MEMORA and adds it to user PATH.

.NOTES
    Run in PowerShell as Administrator for best results (required for PATH modification).
    For non-admin install, use -UserScope switch.
    This script avoids the broken Microsoft Store Python execution alias.

.PARAMETER UserScope
    Install for current user only (no admin required). Adds to user PATH.

.PARAMETER PythonPath
    Path to Python executable. If not specified, auto-detects using 'py' launcher.

.PARAMETER InstallDir
    Custom installation directory. Defaults to $env:LOCALAPPDATA\MEMORA

.PARAMETER AddToPath
    Automatically add to PATH. Defaults to $true.

.PARAMETER SkipDockerAssets
    Skip Docker asset verification. Defaults to $false.

.EXAMPLE
    .\install.ps1

.EXAMPLE
    .\install.ps1 -UserScope

.EXAMPLE
    .\install.ps1 -PythonPath "C:\Python312\python.exe"
#>

param(
    [switch]$UserScope,
    [string]$PythonPath = "",
    [string]$InstallDir = "$env:LOCALAPPDATA\MEMORA",
    [switch]$AddToPath = $true,
    [switch]$SkipDockerAssets
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Log {
    param([string]$Message, [string]$Level = "INFO")
    $timestamp = Get-Date -Format "HH:mm:ss"
    $color = switch ($Level) {
        "ERROR" { "Red" }
        "WARN"  { "Yellow" }
        "OK"    { "Green" }
        default { "Cyan" }
    }
    Write-Host "[$timestamp] [$Level] $Message" -ForegroundColor $color
}

function Test-Command {
    param([string]$Command)
    try {
        $null = & $Command --version 2>$null
        return $true
    } catch {
        return $false
    }
}

function Find-Python {
    <#
    .SYNOPSIS
        Find a suitable Python 3.10+ installation on Windows.
    .DESCRIPTION
        Avoids the Microsoft Store execution alias (python.exe in WindowsApps)
        by using the 'py' launcher or checking known installation paths.
    #>
    Write-Log "Detecting Python installation..."

    # Strategy 1: Use 'py' launcher (most reliable on Windows)
    if (Test-Command "py") {
        $version = & py -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
        if ($version -and ($version -match '^3\.(1[0-9]|[2-9]\d)$')) {
            Write-Log "Found Python $version via 'py' launcher" "OK"
            return "py"
        }
    }

    # Strategy 2: Check if provided PythonPath works
    if ($PythonPath -and (Test-Command $PythonPath)) {
        $version = & $PythonPath -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
        $parts = $version.Split('.')
        if ([int]$parts[0] -eq 3 -and [int]$parts[1] -ge 10) {
            Write-Log "Using provided Python $version at $PythonPath" "OK"
            return $PythonPath
        }
    }

    # Strategy 3: Check common installation paths (avoid WindowsApps)
    $commonPaths = @(
        "$env:LOCALAPPDATA\Python\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe",
        "C:\Python312\python.exe",
        "C:\Python311\python.exe",
        "C:\Python310\python.exe",
        "C:\Program Files\Python312\python.exe",
        "C:\Program Files\Python311\python.exe",
        "C:\Program Files\Python310\python.exe",
        "C:\Program Files (x86)\Python312\python.exe",
        "C:\Program Files (x86)\Python311\python.exe",
        "C:\Program Files (x86)\Python310\python.exe"
    )

    foreach ($path in $commonPaths) {
        if (Test-Path $path -and (Test-Command $path)) {
            $version = & $path -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
            $parts = $version.Split('.')
            if ([int]$parts[0] -eq 3 -and [int]$parts[1] -ge 10) {
                Write-Log "Found Python $version at $path" "OK"
                return $path
            }
        }
    }

    # Strategy 4: Check py launcher for specific versions
    try {
        $pyVersions = & py --list 2>$null
        if ($pyVersions) {
            foreach ($line in $pyVersions.Split("`n")) {
                if ($line -match '^\s*-3\.(1[0-9]|[2-9]\d)') {
                    $ver = $line.Trim().TrimStart('-')
                    Write-Log "Found Python $ver via 'py' launcher (specific version)" "OK"
                    return "py -$ver"
                }
            }
        }
    } catch { }

    Write-Log "ERROR: No suitable Python 3.10+ installation found." "ERROR"
    Write-Log "Please install Python 3.10+ from https://python.org" "ERROR"
    Write-Log "Or provide path via -PythonPath parameter" "ERROR"
    exit 1
}

function Ensure-Pip {
    param([string]$PythonPath)
    Write-Log "Ensuring pip is available..."
    & $PythonPath -m ensurepip --upgrade 2>$null | Out-Null
    & $PythonPath -m pip install --upgrade pip 2>$null | Out-Null
    Write-Log "pip ready" "OK"
}

# =========================================================================
# Required Docker assets that MUST be present for Docker deployment
# =========================================================================
$requiredDockerAssets = @(
    "Dockerfile",
    "docker-compose.yml",
    "docker-entrypoint.sh",
    "requirements.txt",
    "pyproject.toml",
    "memora",
    ".env.docker",
    ".env.example"
)

function Verify-DockerAssets {
    param([string]$InstallDir)
    Write-Log "Verifying required Docker assets..."

    $missing = @()
    foreach ($asset in $requiredDockerAssets) {
        $path = Join-Path $InstallDir $asset
        if (-not (Test-Path $path)) {
            $missing += $asset
            Write-Log "Missing required asset: $asset" "ERROR"
        } else {
            Write-Log "Found: $asset" "OK"
        }
    }

    if ($missing.Count -gt 0) {
        Write-Log "Missing $($missing.Count) required Docker asset(s): $($missing -join ', ')" "ERROR"
        return $false
    }

    Write-Log "All $($requiredDockerAssets.Count) required Docker assets verified" "OK"
    return $true
}

function Initialize-Config {
    param([string]$InstallDir, [string]$SourceDir)
    Write-Log "Initializing configuration..."

    # .env.docker - copy template if not exists (never overwrite)
    $envDockerDst = Join-Path $InstallDir ".env.docker"
    $envDockerSrc = Join-Path $SourceDir ".env.docker"
    if (-not (Test-Path $envDockerDst)) {
        if (Test-Path $envDockerSrc) {
            Copy-Item -Path $envDockerSrc -Destination $envDockerDst -Force | Out-Null
            Write-Log "Copied .env.docker template" "OK"
        } else {
            Write-Log "Source .env.docker not found at $envDockerSrc" "WARN"
        }
    } else {
        Write-Log ".env.docker already exists, preserving existing" "OK"
    }

    # .env.example - copy template if not exists
    $envExampleDst = Join-Path $InstallDir ".env.example"
    $envExampleSrc = Join-Path $SourceDir ".env.example"
    if (-not (Test-Path $envExampleDst)) {
        if (Test-Path $envExampleSrc) {
            Copy-Item -Path $envExampleSrc -Destination $envExampleDst -Force | Out-Null
            Write-Log "Copied .env.example template" "OK"
        } else {
            Write-Log "Source .env.example not found at $envExampleSrc" "WARN"
        }
    } else {
        Write-Log ".env.example already exists, preserving existing" "OK"
    }

    # .env - create from .env.example if not exists (NEVER copy source .env)
    $envDst = Join-Path $InstallDir ".env"
    if (-not (Test-Path $envDst)) {
        if (Test-Path $envExampleDst) {
            Copy-Item -Path $envExampleDst -Destination $envDst -Force | Out-Null
            Write-Log "Created .env from .env.example template" "OK"
            Write-Log "IMPORTANT: Edit .env and set VAULT_PATH to your Obsidian vault" "WARN"
        } else {
            Write-Log "No .env.example template available to create .env" "WARN"
        }
    } else {
        Write-Log ".env already exists, preserving existing configuration" "OK"
    }
}

function Copy-ProjectFiles {
    param([string]$SourceDir, [string]$InstallDir)
    Write-Log "Copying project files..."

    # Define exclusions - only exclude build artifacts and runtime data
    $exclusions = @(
        ".venv",
        "__pycache__",
        "*.pyc",
        ".pytest_cache",
        ".git",
        "data",
        "logs",
        "*.db",
        "*.db-journal",
        ".env"  # Never copy source .env (may contain secrets)
    )

    # Copy all files recursively (suppress output)
    Copy-Item -Path "$SourceDir\*" -Destination $InstallDir -Recurse -Force -Exclude $exclusions | Out-Null

    # Ensure required directories exist
    $requiredDirs = @("memora", "memora\lifecycle", "tests", "docs")
    foreach ($dir in $requiredDirs) {
        $path = Join-Path $InstallDir $dir
        if (-not (Test-Path $path)) {
            Write-Log "Required directory missing: $dir" "ERROR"
        }
    }

    Write-Log "Project files copied" "OK"
}

function Install-Memora {
    param([string]$PythonPath, [string]$InstallDir, [string]$SourceDir)
    Write-Log "Installing MEMORA to $InstallDir"

    # Create install directory
    if (-not (Test-Path $InstallDir)) {
        New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
    }

    # Copy project files
    Copy-ProjectFiles $SourceDir $InstallDir

    # Initialize configuration (templates only, preserve user config)
    Initialize-Config $InstallDir $SourceDir

    # Verify required Docker assets
    if (-not $SkipDockerAssets) {
        $assetsOk = Verify-DockerAssets $InstallDir
        if (-not $assetsOk) {
            Write-Log "Installation failed: missing required Docker assets" "ERROR"
            exit 1
        }
    }

    # Create virtual environment
    $venvDir = "$InstallDir\.venv"
    Write-Log "Creating virtual environment at $venvDir..."
    & $PythonPath -m venv $venvDir | Out-Null
    if (-not (Test-Path "$venvDir\Scripts\python.exe")) {
        Write-Log "Virtual environment creation failed" "ERROR"
        exit 1
    }
    Write-Log "Virtual environment created" "OK"

    # Install MEMORA in editable mode
    $pip = "$venvDir\Scripts\pip.exe"
    Write-Log "Installing MEMORA package..."
    & $pip install -e $InstallDir --no-cache-dir | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Log "MEMORA package installation failed" "ERROR"
        exit 1
    }
    Write-Log "MEMORA package installed" "OK"

    # Verify console script was generated
    $memoraExe = "$venvDir\Scripts\memora.exe"
    $memoraScript = "$venvDir\Scripts\memora"
    if (-not (Test-Path $memoraExe) -and -not (Test-Path $memoraScript)) {
        Write-Log "WARNING: Console script 'memora' not found in venv Scripts" "WARN"
    } else {
        Write-Log "Console script verified in venv" "OK"
    }

    # Create wrapper scripts
    $scriptsDir = "$InstallDir\scripts"
    if (-not (Test-Path $scriptsDir)) {
        New-Item -ItemType Directory -Path $scriptsDir -Force | Out-Null
    }

    # Create memora.bat for CMD
    $batContent = @"
@echo off
set MEMORA_HOME=$InstallDir
call "$venvDir\Scripts\activate.bat" >nul 2>&1
memora %%*
"@
    Set-Content -Path "$scriptsDir\memora.bat" -Value $batContent -Encoding ASCII

    # Create memora.ps1 for PowerShell
    $ps1Content = @"
# MEMORA PowerShell Wrapper
\$env:MEMORA_HOME = "$InstallDir"
& "$venvDir\Scripts\Activate.ps1" > \$null 2>&1
& memora @args
"@
    Set-Content -Path "$scriptsDir\memora.ps1" -Value $ps1Content -Encoding UTF8

    Write-Log "Created wrapper scripts in $scriptsDir" "OK"
    return $scriptsDir
}

function Add-ToPath {
    param([string]$PathToAdd, [switch]$UserScope)
    Write-Log "Adding $PathToAdd to PATH..."

    $currentPath = [Environment]::GetEnvironmentVariable("PATH", "User")
    if ($currentPath -like "*$PathToAdd*") {
        Write-Log "Already in PATH" "OK"
        return
    }

    $newPath = "$currentPath;$PathToAdd"
    try {
        [Environment]::SetEnvironmentVariable("PATH", $newPath, "User")
        Write-Log "Added to user PATH" "OK"
        Write-Log "NOTE: Restart your terminal or run 'refreshenv' for changes to take effect" "WARN"
    } catch {
        Write-Log "Failed to update PATH: $_" "ERROR"
        Write-Log "You can manually add: $PathToAdd" "WARN"
    }
}

function Verify-Installation {
    param([string]$ScriptsDir, [string]$InstallDir, [string]$VenvDir)
    Write-Log "Verifying installation..."

    # Verify wrapper scripts exist
    $batPath = Join-Path $ScriptsDir "memora.bat"
    $ps1Path = Join-Path $ScriptsDir "memora.ps1"
    if (-not (Test-Path $batPath) -or -not (Test-Path $ps1Path)) {
        Write-Log "Wrapper scripts missing" "ERROR"
        return $false
    }

    # Verify memora --version works using the venv python directly
    $venvPython = Join-Path $VenvDir "Scripts\python.exe"
    $result = & $venvPython -m memora.cli --version 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Log "MEMORA CLI verified: $($result.Trim())" "OK"
    } else {
        Write-Log "MEMORA CLI verification failed" "ERROR"
        Write-Log "Output: $result" "ERROR"
        return $false
    }

    # Verify MEMORA_HOME resolves to install directory
    $envMemoraHome = $env:MEMORA_HOME
    if ($envMemoraHome -and (Test-Path (Join-Path $envMemoraHome "pyproject.toml"))) {
        Write-Log "MEMORA_HOME correctly points to installation" "OK"
    } else {
        Write-Log "MEMORA_HOME not set or invalid (will be set by wrapper scripts)" "WARN"
    }

    Write-Log "Installation verification passed" "OK"
    return $true
}

# Main execution
Write-Log "=== MEMORA Windows Installer ==="
Write-Log "Install directory: $InstallDir"
Write-Log "User scope: $UserScope"
Write-Log "Source directory: $PSScriptRoot"

# Find Python (avoids Microsoft Store alias)
$resolvedPython = Find-Python

# Ensure pip
Ensure-Pip $resolvedPython

# Install MEMORA
$scriptsDir = Install-Memora $resolvedPython $InstallDir $PSScriptRoot

# Add to PATH
if ($AddToPath) {
    Add-ToPath $scriptsDir -UserScope:$UserScope
}

# Verify
$venvDir = "$InstallDir\.venv"
if (-not (Verify-Installation $scriptsDir $InstallDir $venvDir)) {
    Write-Log "Installation verification failed" "ERROR"
    exit 1
}

Write-Log "=== Installation Complete ===" "OK"
Write-Log ""
Write-Log "Next steps:"
Write-Log "  1. Restart your terminal or run 'refreshenv'"
Write-Log "  2. Configure your vault: edit $InstallDir\.env and set VAULT_PATH to your Obsidian vault"
Write-Log "  3. Run: memora --start"
Write-Log ""
Write-Log "For Docker-based deployment, ensure Docker Desktop is installed and running."
Write-Log ""
Write-Log "Installed to: $InstallDir"
Write-Log "Virtual env:  $venvDir"
Write-Log "Scripts dir:  $scriptsDir (added to PATH)"