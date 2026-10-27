# ============================================================
# Hikvision AI CCTV Platform - Windows 11 Environment Setup
# Prerequisites: Windows 11, NVIDIA Game Ready Driver 525+
# Run as Administrator in PowerShell
# ============================================================

param(
    [switch]$SkipWSL,
    [switch]$SkipDocker,
    [switch]$SkipNvidiaCheck
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

Write-Host ""
Write-Host "+==============================================================+" -ForegroundColor Cyan
Write-Host "|     Hikvision AI CCTV Platform - Environment Setup           |" -ForegroundColor Cyan
Write-Host "|     Windows 11 / WSL2 / Docker Desktop / NVIDIA GPU          |" -ForegroundColor Cyan
Write-Host "+==============================================================+" -ForegroundColor Cyan
Write-Host ""

# -------------------------------------------------------
# Step 1: Verify Windows version
# -------------------------------------------------------
Write-Host "[1/7] Checking Windows version..." -ForegroundColor Yellow
$osVersion = [System.Environment]::OSVersion.Version
if ($osVersion.Build -lt 19041) {
    Write-Host "  ERROR: Windows build $($osVersion.Build) detected. WSL2 requires build 19041+." -ForegroundColor Red
    exit 1
}
Write-Host "  OK: Windows $($osVersion.Major).$($osVersion.Minor) Build $($osVersion.Build)" -ForegroundColor Green

# -------------------------------------------------------
# Step 2: Check NVIDIA Driver
# -------------------------------------------------------
if (-not $SkipNvidiaCheck) {
    Write-Host "[2/7] Checking NVIDIA GPU driver..." -ForegroundColor Yellow
    try {
        $nvidiaSmi = & "nvidia-smi" --query-gpu=driver_version,name,memory.total --format=csv,noheader 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  OK: $nvidiaSmi" -ForegroundColor Green
        } else {
            Write-Host "  WARNING: nvidia-smi returned error. Install NVIDIA Game Ready Driver 525+." -ForegroundColor Yellow
        }
    } catch {
        Write-Host "  WARNING: nvidia-smi not found. Install NVIDIA drivers from https://www.nvidia.com/drivers" -ForegroundColor Yellow
    }
} else {
    Write-Host "[2/7] Skipping NVIDIA check (-SkipNvidiaCheck)" -ForegroundColor DarkGray
}

# -------------------------------------------------------
# Step 3: Enable and update WSL2
# -------------------------------------------------------
if (-not $SkipWSL) {
    Write-Host "[3/7] Configuring WSL2..." -ForegroundColor Yellow
    
    # Check if WSL is installed
    $wslStatus = wsl --status 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  Installing WSL2..." -ForegroundColor Cyan
        wsl --install --no-distribution
        Write-Host "  WSL2 installed. A REBOOT may be required." -ForegroundColor Yellow
    } else {
        Write-Host "  WSL2 is already installed." -ForegroundColor Green
        # Update WSL
        Write-Host "  Updating WSL kernel..." -ForegroundColor Cyan
        wsl --update 2>$null
    }
    
    # Set WSL2 as default
    wsl --set-default-version 2 2>$null
    Write-Host "  OK: WSL2 set as default version." -ForegroundColor Green
} else {
    Write-Host "[3/7] Skipping WSL setup (-SkipWSL)" -ForegroundColor DarkGray
}

# -------------------------------------------------------
# Step 4: Check Docker Desktop
# -------------------------------------------------------
if (-not $SkipDocker) {
    Write-Host "[4/7] Checking Docker Desktop..." -ForegroundColor Yellow
    
    try {
        $dockerVersion = docker version --format '{{.Server.Version}}' 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  OK: Docker Desktop $dockerVersion" -ForegroundColor Green
        } else {
            throw "Docker not running"
        }
    } catch {
        Write-Host "  Docker Desktop not found or not running." -ForegroundColor Yellow
        Write-Host "  Please install Docker Desktop from: https://docs.docker.com/desktop/install/windows-install/" -ForegroundColor Cyan
        Write-Host "  After installation, enable:" -ForegroundColor Cyan
        Write-Host "    - Settings -> General -> 'Use the WSL 2 based engine'" -ForegroundColor White
        Write-Host "    - Settings -> Resources -> WSL Integration -> Enable for your distro" -ForegroundColor White
    }
    
    # Check NVIDIA Container Toolkit in Docker
    try {
        $gpuTest = docker run --rm --gpus all nvidia/cuda:12.2.2-base-ubuntu22.04 nvidia-smi 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  OK: NVIDIA GPU accessible inside Docker containers." -ForegroundColor Green
        } else {
            Write-Host "  WARNING: GPU passthrough test failed. Ensure Docker Desktop has WSL2 backend enabled." -ForegroundColor Yellow
        }
    } catch {
        Write-Host "  WARNING: Could not test GPU passthrough (Docker may not be running)." -ForegroundColor Yellow
    }
} else {
    Write-Host "[4/7] Skipping Docker check (-SkipDocker)" -ForegroundColor DarkGray
}

# -------------------------------------------------------
# Step 5: Create .env from template
# -------------------------------------------------------
Write-Host "[5/7] Setting up environment configuration..." -ForegroundColor Yellow

$envFile = Join-Path $ProjectRoot ".env"
$envExample = Join-Path $ProjectRoot ".env.example"

if (-not (Test-Path $envFile)) {
    if (Test-Path $envExample) {
        Copy-Item $envExample $envFile
        Write-Host "  Created .env from .env.example" -ForegroundColor Green
        Write-Host "  IMPORTANT: Edit .env with your actual NVR/DVR IPs, passwords, and Telegram bot token." -ForegroundColor Yellow
    } else {
        Write-Host "  WARNING: .env.example not found at $envExample" -ForegroundColor Yellow
    }
} else {
    Write-Host "  OK: .env already exists." -ForegroundColor Green
}

# -------------------------------------------------------
# Step 6: Create required directories
# -------------------------------------------------------
Write-Host "[6/7] Creating project directories..." -ForegroundColor Yellow

$dirs = @(
    "models",
    "media\snapshots",
    "media\clips", 
    "media\crops"
)

foreach ($dir in $dirs) {
    $fullPath = Join-Path $ProjectRoot $dir
    if (-not (Test-Path $fullPath)) {
        New-Item -ItemType Directory -Path $fullPath -Force | Out-Null
        Write-Host "  Created: $dir" -ForegroundColor DarkGray
    }
}
Write-Host "  OK: All directories ready." -ForegroundColor Green

# -------------------------------------------------------
# Step 7: Summary & Next Steps
# -------------------------------------------------------
Write-Host ""
Write-Host "+==============================================================+" -ForegroundColor Green
Write-Host "|                    Setup Complete!                           |" -ForegroundColor Green
Write-Host "+==============================================================+" -ForegroundColor Green
Write-Host ""
Write-Host "Next Steps:" -ForegroundColor Cyan
Write-Host "  1. Edit .env with your Hikvision NVR/DVR IPs and passwords" -ForegroundColor White
Write-Host "  2. Update config/frigate.yml with your camera RTSP URLs" -ForegroundColor White
Write-Host "  3. Start the platform:" -ForegroundColor White
Write-Host ""
Write-Host "     cd $ProjectRoot" -ForegroundColor Yellow
Write-Host "     docker compose up -d" -ForegroundColor Yellow
Write-Host ""
Write-Host "  4. Access the dashboard:" -ForegroundColor White
Write-Host "     Dashboard:  http://localhost:8000" -ForegroundColor Cyan
Write-Host "     API Docs:   http://localhost:8000/docs" -ForegroundColor Cyan
Write-Host "     Frigate UI: http://localhost:5000" -ForegroundColor Cyan
Write-Host ""
Write-Host "  5. Verify GPU inside container:" -ForegroundColor White
Write-Host "     docker exec -it cctv_backend nvidia-smi" -ForegroundColor Yellow
Write-Host ""
