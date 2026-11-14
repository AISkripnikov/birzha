@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul && (py fut_backtest.py --split 2025-06-01) || (python fut_backtest.py --split 2025-06-01)
pause
