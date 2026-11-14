@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul && (py backtest.py --split 2022-01-01) || (python backtest.py --split 2022-01-01)
pause
