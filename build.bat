@echo off
echo ===================================================
echo Step 1: Compiling Python code with Nuitka...
echo ===================================================

:: No GUI toolkit anymore (customtkinter removed) - this is a Flask app with
:: a tray icon. libzim ships as a single top-level .pyd (not a package), so
:: Nuitka's normal dependency walk already grabs it - no extra flag needed.
::
:: onnxruntime and onnxruntime-genai need real work, confirmed by an actual
:: frozen-build smoke test (not a guess): onnxruntime's __init__.py imports
:: capi/onnxruntime_pybind11_state.pyd in a way Nuitka's static analysis
:: never traces, so the whole capi/ subpackage - .pyd included - was silently
:: absent from main.dist. --include-package=onnxruntime.capi forces Nuitka
:: to compile it in properly, and its own dll-files plugin then auto-detects
:: onnxruntime.dll / onnxruntime_providers_shared.dll from that module's PE
:: import table - confirmed by its own "Found 2 files DLLs from onnxruntime
:: installation" log line, so those two need no manual handling.
:: onnxruntime-genai.dll is different: onnxruntime_genai loads it at runtime
:: via os.add_dll_directory (see onnxruntime_genai/_dll_directory.py), not a
:: PE-level static link, so Nuitka's dependency walker never finds it and it
:: has to be copied in by hand as a plain data file.
for /f "delims=" %%P in ('python -c "import onnxruntime_genai, os; print(os.path.dirname(onnxruntime_genai.__file__))"') do set OGA_DIR=%%P

python -m nuitka --standalone ^
    --assume-yes-for-downloads ^
    --include-package=onnxruntime.capi ^
    --include-package-data=onnxruntime_genai ^
    --include-package-data=onnxruntime ^
    --include-data-files="%OGA_DIR%\onnxruntime-genai.dll=onnxruntime_genai/onnxruntime-genai.dll" ^
    --windows-console-mode=disable ^
    --windows-icon-from-ico=assets/icons/hub.ico ^
    main.py

if not exist "main.dist\main.exe" (
    echo.
    echo [ERROR] Nuitka compilation failed! Stopping build.
    pause
    exit /b
)

echo.
echo Copying templates/, assets/, and VERSION into main.dist (none of these
echo are Python imports, so Nuitka won't bundle them itself - and main.dist
echo needs to be directly runnable for the smoke test below, before the
echo installer would otherwise be the only thing that adds assets/)...
xcopy /E /I /Y templates main.dist\templates >nul
xcopy /E /I /Y assets main.dist\assets >nul
copy /Y VERSION main.dist\VERSION >nul

echo.
echo ===================================================
echo Step 2: Packaging into Setup.exe with Inno Setup...
echo ===================================================

"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss

echo.
echo ===================================================
echo Build Complete! Look for your new Setup.exe in the Output folder.
echo.
echo IMPORTANT: run main.dist\main.exe directly now and confirm a ZIM
echo module opens and one chat message completes. libzim/onnxruntime-genai
echo missing-DLL failures only show up in the frozen build, never when
echo running "python main.py" from source.
echo ===================================================
