@echo off
rem Windows:  judge     judge the whole set (double-click works too)
rem           judge 5   judge problem 5 only        (PowerShell: .\judge 5)
setlocal
cd /d "%~dp0"
set "ARG="
if not "%~1"=="" set "ARG=%~n1.cpp"
where py >nul 2>nul
if errorlevel 1 (
  python "..\Judge\judge.py" %ARG%
) else (
  py -3 "..\Judge\judge.py" %ARG%
)
if "%~1"=="" pause
