@echo off
rem Double-cliquer pour ouvrir l'interface roadbook (installe tout au premier lancement).
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Premiere utilisation : installation de roadbook...
  python -m venv .venv || goto erreur
  .venv\Scripts\python -m pip install -e . || goto erreur
)
.venv\Scripts\python -m roadbook interface
goto :eof
:erreur
echo.
echo Python 3.11 ou plus recent est necessaire : https://www.python.org/downloads/
echo (cocher "Add python.exe to PATH" pendant l'installation), puis relancer ce fichier.
pause
