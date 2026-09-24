@echo off
title ClipForge Dashboard
cd /d "%~dp0"
python start.py
if errorlevel 1 (
    echo.
    echo Python nahi mila? https://www.python.org/downloads/ se install karo.
    echo Install ke time "Add python.exe to PATH" wala tick zaroor lagana.
)
pause
