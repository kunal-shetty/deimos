# Deimos installer for Windows (PowerShell 5.1 or later).
#
#   irm https://raw.githubusercontent.com/kunal-shetty/deimos/main/scripts/install.ps1 | iex
#
# Installs Deimos into its own virtual environment in %USERPROFILE%\.deimos\venv
# and adds a `deimos` command to your user PATH. Running it again updates an
# existing install.
#
# Environment overrides:
#   $env:DEIMOS_REF     install a different branch (default: main)
#   $env:DEIMOS_HOME    where Deimos lives (default: %USERPROFILE%\.deimos)
#   $env:DEIMOS_SOURCE  install from a local checkout or another archive
#   $env:DEIMOS_NO_MODIFY_PATH = '1'  don't add the bin directory to your user PATH

$ErrorActionPreference = 'Stop'

$Repo       = 'kunal-shetty/deimos'
$Ref        = if ($env:DEIMOS_REF) { $env:DEIMOS_REF } else { 'main' }
$Source     = if ($env:DEIMOS_SOURCE) { $env:DEIMOS_SOURCE } else { "https://github.com/$Repo/archive/refs/heads/$Ref.zip" }
$DeimosHome = if ($env:DEIMOS_HOME) { $env:DEIMOS_HOME } else { Join-Path $env:USERPROFILE '.deimos' }
$Venv       = Join-Path $DeimosHome 'venv'
$BinDir     = Join-Path $DeimosHome 'bin'
$VenvPy     = Join-Path $Venv 'Scripts\python.exe'
$VenvExe    = Join-Path $Venv 'Scripts\deimos.exe'

function Say($msg)  { Write-Host "  $msg" }
# throw rather than exit: under `irm | iex`, exit would close the user's PowerShell window
function Fail($msg) { Write-Host ""; Write-Host "  Error: $msg" -ForegroundColor Red; Write-Host ""; throw "Deimos install failed." }

function Invoke-Checked {
    param([string]$Exe, [string[]]$Arguments, [string]$What)
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { Fail "$What failed (exit code $LASTEXITCODE)." }
}

Write-Host ""
Write-Host "  Installing Deimos"
Write-Host ""

# ── 1. Python 3.11+ ──────────────────────────────────────────────────────────
# Prefer the py launcher; skip the Microsoft Store stub, which only opens the Store.
$Python = $null
$candidates = @(
    @('py', '-3.13'), @('py', '-3.12'), @('py', '-3.11'), @('py', '-3'),
    @('python', $null), @('python3', $null)
)
foreach ($c in $candidates) {
    $exe, $flag = $c
    $cmd = Get-Command $exe -ErrorAction SilentlyContinue
    if (-not $cmd -or $cmd.Source -like '*\WindowsApps\*') { continue }
    $probe = @('-c', 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)')
    if ($flag) { $probe = @($flag) + $probe }
    try { & $exe @probe 2>$null | Out-Null } catch { continue }  # e.g. py -3.13 when 3.13 isn't installed
    if ($LASTEXITCODE -eq 0) { $Python = @($exe) + @($flag | Where-Object { $_ }); break }
}
if (-not $Python) {
    Fail "Python 3.11 or newer is required. Install it from https://www.python.org/downloads/ (tick 'Add python.exe to PATH') and run this again."
}
$pyExe  = $Python[0]
$pyArgs = @($Python | Select-Object -Skip 1)
# No double quotes inside -c: Windows PowerShell 5.1 strips them from native arguments
$found  = & $pyExe @pyArgs -c "import sys; print('Python', sys.version.split()[0], 'at', sys.executable)"
Say "Using $found"

# ── 2. Private virtual environment ───────────────────────────────────────────
New-Item -ItemType Directory -Force -Path $DeimosHome | Out-Null
if (-not (Test-Path $VenvPy)) {
    Say "Creating an environment in $Venv"
    Invoke-Checked $pyExe ($pyArgs + @('-m', 'venv', $Venv)) 'Creating the virtual environment'
}

# ── 3. Install Deimos ────────────────────────────────────────────────────────
Say 'Downloading and installing Deimos (this can take a minute)'
$pip = @('-m', 'pip', 'install', '--quiet', '--disable-pip-version-check')
Invoke-Checked $VenvPy ($pip + @('--upgrade', 'pip')) 'Updating pip'
Invoke-Checked $VenvPy ($pip + @('--upgrade', '--force-reinstall', '--no-deps', "deimos @ $Source")) 'Installing Deimos'
Invoke-Checked $VenvPy ($pip + @("deimos @ $Source")) 'Installing dependencies'
if (-not (Test-Path $VenvExe)) { Fail "The install finished but $VenvExe is missing." }

# ── 4. Put `deimos` on the PATH ──────────────────────────────────────────────
# A small launcher keeps the environment's python.exe and pip.exe off your PATH.
New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
$launcher = Join-Path $BinDir 'deimos.cmd'
Set-Content -Path $launcher -Encoding ascii -Value "@echo off`r`n`"$VenvExe`" %*"
Say "Created $launcher"

$pathNote = $null
if ($env:DEIMOS_NO_MODIFY_PATH -eq '1') {
    $pathNote = "Add $BinDir to your PATH to run deimos from anywhere."
} else {
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    $entries  = @($userPath -split ';' | Where-Object { $_ })
    if ($entries -notcontains $BinDir) {
        [Environment]::SetEnvironmentVariable('Path', (($entries + $BinDir) -join ';'), 'User')
        Say "Added $BinDir to your user PATH"
        $pathNote = 'Open a new terminal so the deimos command is found.'
    }
    if (($env:Path -split ';') -notcontains $BinDir) { $env:Path = "$env:Path;$BinDir" }
}

# ── 5. Done ──────────────────────────────────────────────────────────────────
$version = $null
try { $version = & $VenvExe --version 2>$null } catch { }
if (-not $version) { $version = 'deimos' }
Write-Host ""
Write-Host "  Installed $version" -ForegroundColor Green
Write-Host ""
if ($pathNote) { Say $pathNote }
Say "Run 'deimos' in any project folder. The first run asks for your Groq API key."
Say "Update later with 'deimos update'. Uninstall by deleting $DeimosHome and removing $BinDir from your user PATH."
Write-Host ""
