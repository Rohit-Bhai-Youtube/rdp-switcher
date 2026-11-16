@echo off
echo Detected RDP windows:
echo.
py -3.12 "%~dp0rdp_switcher.py" --list
echo.
pause
