@echo off
echo Stopping any existing FlowScope server...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8000" ^| findstr "LISTENING"') do (
    taskkill /PID %%a /F >nul 2>&1
)
echo Starting FlowScope Miner on http://127.0.0.1:8000 ...
venv\Scripts\uvicorn backend.main:app --reload --app-dir .
