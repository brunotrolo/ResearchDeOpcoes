@echo off
REM ===========================================================================
REM run_once.bat — entrypoint chamado pelo Task Scheduler (uma execução).
REM Ativa o venv e roda o motor. O proprio motor decide, via /market/status,
REM se o mercado esta aberto.
REM ===========================================================================
cd /d "%~dp0.."
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" main.py
) else (
    python main.py
)
exit /b %ERRORLEVEL%
