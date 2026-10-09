@echo off
rem Windows launcher used by the VS Code tasks (Ctrl+Shift+B): runs judge.py with the Python launcher "py"
rem when it is installed (python.org installer), otherwise with "python" (e.g. Microsoft Store Python).
rem Plain "python" alone fails when Python was installed without "Add python.exe to PATH".
where py >nul 2>nul || goto nopy
py -3 "%~dp0judge.py" %*
exit /b %errorlevel%
:nopy
python "%~dp0judge.py" %*
exit /b %errorlevel%
