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

:: --nofollow-import-to=PIL._avif drops Pillow's AVIF codec (~7.5MB) - confirmed
:: unnecessary by actually deleting the built _avif.pyd and re-testing: Pillow's
:: own plugin registration wraps each format's import in try/except, so a
:: missing codec is silently skipped, not a crash. Pillow is only used here to
:: load the tray icon's .ico file, so nothing else needs it either.
:: (--noinclude-dlls doesn't apply here: _avif.pyd is a genuine Python
:: extension MODULE Nuitka finds via import-following, not a "dependency DLL"
:: pulled in by PE analysis of an already-included binary - confirmed by
:: testing --noinclude-dlls first and finding it had no effect at all.)
python -m nuitka --standalone ^
    --assume-yes-for-downloads ^
    --include-package=onnxruntime.capi ^
    --include-package-data=onnxruntime_genai ^
    --include-package-data=onnxruntime ^
    --include-data-files="%OGA_DIR%\onnxruntime-genai.dll=onnxruntime_genai/onnxruntime-genai.dll" ^
    --nofollow-import-to=PIL._avif ^
    --windows-console-mode=disable ^
    --windows-icon-from-ico=assets/icons/hub.ico ^
    --output-filename=OfflineHub.exe ^
    main.py

if not exist "main.dist\OfflineHub.exe" (
    echo.
    echo [ERROR] Nuitka compilation failed! Stopping build.
    :: %CI% is set to "true" by GitHub Actions - skip the interactive pause
    :: there so a failed build doesn't hang the workflow until it times out.
    :: exit /b with no code left this at 0 (success!) even on failure - the
    :: workflow needs a real nonzero code to detect the build broke.
    if not "%CI%"=="true" pause
    exit /b 1
)

:: Nuitka also copies onnxruntime-genai.dll to main.dist's top level, on top
:: of the onnxruntime_genai/onnxruntime-genai.dll copy the --include-data-files
:: flag above places (a duplicate ~7.2MB, confirmed byte-identical). Confirmed
:: safe to delete by testing: onnxruntime_genai.pyd finds its DLL via Windows'
:: default "check the loading module's own directory first" search order, so
:: only the copy sitting next to it in onnxruntime_genai/ is ever actually used.
if exist "main.dist\onnxruntime-genai.dll" del "main.dist\onnxruntime-genai.dll"

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
if errorlevel 1 (
    echo.
    echo [ERROR] Inno Setup packaging failed! Stopping build.
    if not "%CI%"=="true" pause
    exit /b 1
)

echo.
echo ===================================================
echo Build Complete! Look for your new Setup.exe in the Output folder.
echo.
echo IMPORTANT: run main.dist\OfflineHub.exe directly now and confirm a ZIM
echo module opens and one chat message completes. libzim/onnxruntime-genai
echo missing-DLL failures only show up in the frozen build, never when
echo running "python main.py" from source.
echo ===================================================
