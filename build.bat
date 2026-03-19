@echo off
echo ===================================================
echo Step 1: Compiling Python code with Nuitka...
echo ===================================================

:: Run Nuitka. 
:: We use --include-package-data=customtkinter to bundle the themes/fonts properly.
python -m nuitka --standalone --enable-plugin=tk-inter --include-package-data=customtkinter --windows-console-mode=disable --windows-icon-from-ico=assets/icons/hub.ico main.py

:: Check if Nuitka succeeded before moving on
if not exist "main.dist\main.exe" (
    echo.
    echo [ERROR] Nuitka compilation failed! Stopping build.
    pause
    exit /b
)

echo.
echo ===================================================
echo Step 2: Packaging into Setup.exe with Inno Setup...
echo ===================================================

:: Run Inno Setup Compiler
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss

echo.
echo ===================================================
echo Build Complete! Look for your new Setup.exe in the Output folder.
echo ===================================================
pause