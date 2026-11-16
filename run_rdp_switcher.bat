@echo off
setlocal
set "HERE=%~dp0"
set "SCRIPT=%HERE%rdp_switcher.py"
set "PYW=%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe"

REM Running latest RDP Switcher with Live Inboxious Integration (Python 3.12)
if exist "%PYW%" (
  start "" "%PYW%" "%SCRIPT%"
  goto :eof
)
start "" pyw -3.12 "%SCRIPT%"
