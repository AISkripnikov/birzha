@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul && (py fut_bot.py) || (python fut_bot.py)
pause
