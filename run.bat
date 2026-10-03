@echo off
echo ========================================================
echo AuraSpread: MCX Gold Relative-Value Monitor
echo ========================================================
echo.

if "%1"=="test" (
    echo Running unit tests...
    python -m pytest pipeline/tests -v
    goto end
)

if "%1"=="data" (
    echo Running quantitative pipeline...
    python -m pipeline.run_pipeline
    goto end
)

if "%1"=="serve" (
    echo Starting local web server at http://localhost:8000 ...
    python -m http.server 8000 --directory web
    goto end
)

echo Usage:
echo   run.bat test   - Run unit tests
echo   run.bat data   - Run quantitative pipeline
echo   run.bat serve  - Start web server at http://localhost:8000
echo.
echo Defaulting to serving website...
python -m http.server 8000 --directory web

:end
