@echo off
REM Aktivujte virtuálne prostredie
call .venv\Scripts\activate

REM Spustite Python skript
python Gemini_TTS_v7.py

REM Udržte konzolu otvorenú
pause