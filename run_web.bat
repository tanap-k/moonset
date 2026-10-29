@echo off
chcp 65001 >nul
cd /d "%~dp0"
streamlit run app.py
pause
