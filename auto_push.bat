@echo off
echo Nastavujem automaticke zalohovanie na GitHub kazdych 60 sekund...
echo Pre ukoncenie stlac CTRL+C.
echo.

:loop
git add .
git diff-index --quiet HEAD || (git commit -m "Auto-update: Automaticky odoslane zmeny" && git push)
timeout /t 60 >nobreak
goto loop
