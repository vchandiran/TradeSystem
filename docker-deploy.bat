@echo off
REM =============================================================================
REM NSE Automated Trading Desk - Docker Desktop Deployment Script
REM =============================================================================
echo ================================================================
echo   Deploying NSE Automated Trading Desk to Docker Desktop...
echo   Broker: Alice Blue (pya3) | Exchange: NSE India
echo ================================================================

REM Check Docker Desktop is running
docker info >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Docker Desktop is not running. Please start Docker Desktop first.
    pause
    exit /b 1
)

echo [1/3] Building Docker image (React Dashboard + Python Trading Engine)...
docker compose build

echo [2/3] Starting container in background...
docker compose up -d

echo [3/3] Verifying container status...
docker ps --filter "name=nse-trading-desk"

echo.
echo ================================================================
echo   [SUCCESS] Deployment complete!
echo   Dashboard UI is live at:  http://localhost:8050
echo   API Health endpoint:      http://localhost:8050/api/status
echo.
echo   To view container logs:   docker compose logs -f
echo   To stop the container:    docker compose down
echo ================================================================
pause
