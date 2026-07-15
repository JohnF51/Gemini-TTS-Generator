@echo off
setlocal enabledelayedexpansion

echo ===================================================
echo   Gemini TTS Generator - Zostavenie MSI Inštalátora
echo ===================================================
echo.

REM 1. Kontrola existencie virtuálneho prostredia
if not exist ".venv" (
    echo [CHYBA] Virtuálne prostredie '.venv' nebolo nájdené.
    echo Spustite tento skript v koreňovom priečinku projektu, kde sa nachádza '.venv'.
    goto error
)

REM 2. Aktivácia virtuálneho prostredia
echo [1/5] Aktivujem virtuálne prostredie...
call .venv\Scripts\activate.bat
if !errorlevel! neq 0 (
    echo [CHYBA] Nepodarilo sa aktivovať virtuálne prostredie.
    goto error
)
echo.

REM 3. Inštalácia cx_Freeze a Pillow pre zostavenie
echo [2/5] Inštalujem potrebné knižnice (cx_Freeze, Pillow)...
python -m pip install --upgrade pip
python -m pip install cx_Freeze>=7.1.1 Pillow
if !errorlevel! neq 0 (
    echo [CHYBA] Inštalácia závislostí zlyhala.
    goto error
)
echo.

REM 4. Prevod PNG ikony do formátu ICO
echo [3/5] Konvertujem PNG ikonu do formátu ICO...
python convert_icon.py
if not exist "gemini_tts_icon.ico" (
    echo [CHYBA] Súbor gemini_tts_icon.ico sa nepodarilo vytvoriť.
    goto error
)
echo.

REM 5. Spustenie kompilácie a tvorby MSI
echo [4/5] Spúšťam cx_Freeze na vytvorenie MSI inštalátora...
python setup.py bdist_msi
if !errorlevel! neq 0 (
    echo [CHYBA] Tvorba MSI inštalátora zlyhala.
    goto error
)
echo.

REM 6. Výpis výsledku
echo ===================================================
echo [5/5] ÚSPEŠNE DOKONČENÉ!
echo ===================================================
echo MSI inštalátor bol vytvorený v priečinku:
echo   %~dp0dist\
echo.
goto end

:error
echo.
echo [CHYBA] Proces bol prerušený kvôli chybe.
echo.

:end
pause
