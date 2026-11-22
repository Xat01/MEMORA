<#
.SYNOPSIS
    MEMORA Desktop Startup Launcher (PowerShell)

.DESCRIPTION
    This script locates the installed MEMORA runtime and starts it with
    automatic dependency management. It can be pinned to Start Menu or
    Taskbar for one-click startup.

.NOTES
    Run in PowerShell. For best results, run as Administrator if you
    need to manage Docker Desktop or system PATH.

.PARAMETER StopDependencies
    Also stop MEMORA-owned Ollama process on exit (if MEMORA started it).
    Docker Desktop is never terminated by MEMORA.

.EXAMPLE
    .\Start-MEMORA.ps1

.EXAMPLE
    .\Start-MEMORA.ps1 -StopDependencies
#>

param(
    [switch]$StopDependencies
)

# -------------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------------
$MemoraInstallDir = Join-Path $env:LOCALAPPDATA "MEMORA"
$MemoraBat = Join-Path $MemoraInstallDir "scripts\memora.bat"
$MemoraPs1 = Join-Path $MemoraInstallDir "scripts\memora.ps1"

# Colors for output
$Colors = @{
    Red     = [ConsoleColor]::Red
    Green   = [ConsoleColor]::Green
    Yellow  = [ConsoleColor]::Yellow
    Cyan    = [ConsoleColor]::Cyan
    Gray    = [ConsoleColor]::DarkGray
    White   = [ConsoleColor]::White
}

function Write-Colored($Message, $Color = 'White', $Prefix = '') {
    $originalColor = $Host.UI.RawUI.ForegroundColor
    $Host.UI.RawUI.ForegroundColor = $Colors[$Color]
    Write-Host "$Prefix$Message"
    $Host.UI.RawUI.ForegroundColor = $originalColor
}

function Write-Info($Message) { Write-Colored $Message 'Cyan' '[INFO] ' }
function Write-Ok($Message)     { Write-Colored $Message 'Green' '[OK] ' }
function Write-Warn($Message)   { Write-Colored $Message 'Yellow' '[WARN] ' }
function Write-Error($Message)  { Write-Colored $Message 'Red' '[ERROR] ' }

# -------------------------------------------------------------------------
# Main execution
# -------------------------------------------------------------------------
Write-Host ""
Write-Colored "=========================================" 'Cyan'
Write-Colored "  MEMORA Desktop Startup Launcher" 'Cyan'
Write-Colored "=========================================" 'Cyan'
Write-Host ""

# Check if MEMORA is installed
if (-not (Test-Path $MemoraInstallDir)) {
    Write-Error "MEMORA not found at $MemoraInstallDir"
    Write-Info "Please run the installer first: install.ps1 or install.bat"
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Ok "Found MEMORA installation at $MemoraInstallDir"

# Check for wrapper scripts
$wrapperScript = if (Test-Path $MemoraPs1) { $MemoraPs1 } elseif (Test-Path $MemoraBat) { $MemoraBat } else { $null }

if (-not $wrapperScript) {
    Write-Error "Wrapper script not found in $MemoraInstallDir\scripts\"
    Write-Info "Installation may be corrupted. Please reinstall."
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Ok "Found startup script: $wrapperScript"

# Check if Docker Desktop is running
Write-Info "Checking Docker Desktop..."
try {
    $dockerInfo = docker info 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Ok "Docker Desktop is running"
    } else {
        Write-Warn "Docker Desktop is not running"
        Write-Info "MEMORA will attempt to start Docker Desktop automatically"
    }
} catch {
    Write-Warn "Could not check Docker Desktop status"
    Write-Info "MEMORA will attempt to start Docker Desktop automatically"
}

# Check if Ollama is running
Write-Info "Checking Ollama..."
try {
    $ollamaList = ollama list 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Ok "Ollama is running"
    } else {
        Write-Warn "Ollama is not running"
        Write-Info "MEMORA will attempt to start Ollama automatically (host mode)"
    }
} catch {
    Write-Warn "Could not check Ollama status"
    Write-Info "MEMORA will attempt to start Ollama automatically (host mode)"
}

# -------------------------------------------------------------------------
# Start MEMORA
# -------------------------------------------------------------------------
Write-Host ""
Write-Info "Starting MEMORA with automatic dependency management..."
Write-Host ""

# Execute MEMORA startup with full preflight validation
& $wrapperScript --start

$exitCode = $LASTEXITCODE

Write-Host ""
if ($exitCode -eq 0) {
    Write-Ok "MEMORA started successfully!"
    Write-Info "MEMORA is ready at http://127.0.0.1:8080"
} else {
    Write-Error "MEMORA startup failed with exit code $exitCode"
    Write-Info "Check the output above for details"
}

Write-Host ""
if ($StopDependencies) {
    Write-Info "Stopping MEMORA-owned Ollama..."
    & $wrapperScript --stop --stop-dependencies
}

Read-Host "Press Enter to exit"
exit $exitCode