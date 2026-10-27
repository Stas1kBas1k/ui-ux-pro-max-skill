@echo off
REM Builds dist\FischMacro\FischMacro.exe. Run from the project folder in a normal (non-admin) prompt.
setlocal
cd /d "%~dp0\.."
if not exist .venv (
    py -3 -m venv .venv || goto :error
)
call .venv\Scripts\activate.bat || goto :error
python -m pip install --upgrade pip || goto :error
python -m pip install -r requirements.txt || goto :error
python -m pytest -q || goto :error
pyinstaller packaging\fischmacro.spec --noconfirm --clean || goto :error
dist\FischMacro\FischMacro.exe --simulation --smoke-test 5 || goto :error
echo.
echo Build OK: dist\FischMacro\FischMacro.exe
exit /b 0
:error
echo Build FAILED (exit code %errorlevel%)
exit /b 1
