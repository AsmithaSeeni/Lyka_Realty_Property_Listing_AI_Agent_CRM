@echo off
title Lyka Realty - AI Agent + CRM
echo ============================================
echo   Lyka Realty - AI Agent + CRM
echo ============================================
echo.

REM --- Backend (FastAPI) on port 8000 ---
echo [1/2] Starting backend on http://localhost:8000 ...
start "Lyka Backend" cmd /k "cd /d %~dp0backend && python -m uvicorn app.main:app --host 127.0.0.1 --port 8000"

REM --- Frontend (Vite) on port 5173 ---
echo [2/2] Starting frontend on http://localhost:5173 ...
start "Lyka Frontend" cmd /k "cd /d %~dp0frontend && npm run dev"

echo.
echo Both servers are starting...
echo   Frontend: http://localhost:5173
echo   Backend:  http://localhost:8000/api/health
echo   API docs: http://localhost:8000/docs
echo.
echo Opening the app in your browser in 6 seconds...
timeout /t 6 /nobreak >nul
start "" http://localhost:5173
echo.
echo Close the two server windows ("Lyka Backend" / "Lyka Frontend") to stop.
pause
