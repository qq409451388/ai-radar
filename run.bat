@echo off
setlocal

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo ^>^>^> Creating virtual environment ^(.venv^)
    where py >nul 2>nul
    if not errorlevel 1 (
        py -3 -m venv .venv
    ) else (
        where python >nul 2>nul
        if errorlevel 1 (
            echo ERROR: Python 3.11 or newer was not found.
            echo Install Python from https://www.python.org/downloads/windows/
            pause
            exit /b 1
        )
        python -m venv .venv
    )
    if errorlevel 1 (
        echo ERROR: Failed to create the virtual environment.
        pause
        exit /b 1
    )
)

".venv\Scripts\python.exe" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
if errorlevel 1 (
    echo ERROR: AI Radar requires Python 3.11 or newer.
    echo Delete .venv after installing a newer Python, then run this file again.
    pause
    exit /b 1
)

echo ^>^>^> Installing dependencies
".venv\Scripts\python.exe" -m pip install -q -r requirements.txt
if errorlevel 1 (
    echo ERROR: Dependency installation failed.
    pause
    exit /b 1
)

echo ^>^>^> Starting AI Radar
echo Open http://localhost:8501 if the browser does not open automatically.
".venv\Scripts\python.exe" -m streamlit run app.py --server.headless true

endlocal
