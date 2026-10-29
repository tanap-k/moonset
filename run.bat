@echo off
chcp 65001 >nul
cd /d "%~dp0"
set /p SYM=ใส่ชื่อหุ้น (เช่น PTTEP.BK): 
python moonset.py %SYM%
pause
