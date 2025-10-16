@echo off
ECHO "--- Setting up environment for Skipera ---"

REM Check if Python is installed and available in PATH
python --version >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    ECHO "Error: Python is not installed or not found in your PATH."
    ECHO "Please install Python and ensure it's added to your system's PATH."
    pause
    exit /b
)

REM Check if the venv directory exists
IF NOT EXIST ".\venv" (
    ECHO "Virtual environment not found. Creating one..."
    python -m venv venv
    IF %ERRORLEVEL% NEQ 0 (
        ECHO "Error: Failed to create virtual environment."
        pause
        exit /b
    )
)

ECHO "Activating virtual environment..."
CALL ".\venv\Scripts\activate.bat"

ECHO "Installing/Verifying required packages..."
pip install -r requirements.txt >nul

:: =================================================================
:: Main program loop starts here
:main_loop

cls
ECHO "--- Skipera ---"
ECHO "Please enter the course slug (e.g., 'python-for-everybody' from the URL)."
set /p course_name="Course Slug: "

IF NOT DEFINED course_name (
    ECHO "Error: Course slug cannot be empty."
    pause
    goto main_loop
)

ECHO "--- Setup complete. Launching application for course: %course_name% ---"
echo.

REM --- Run the Python script with the provided course slug ---
py main.py --slug %course_name% --llm

echo.
ECHO "--- Course processing finished. ---"
echo.

:: Ask user if they want to continue
set /p continue_choice="Do you want to process another course? (Y/N): "

:: Check the user's input (case-insensitive) and either loop or exit
IF /I "%continue_choice%"=="Y" (
    goto main_loop
)

ECHO "--- Exiting program. ---"
pause
exit /b