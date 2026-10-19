@echo off
rem Punto di ingresso per l'Utilita' di pianificazione di Windows.
rem Apre MSYS2 (ambiente UCRT64, lo stesso che serve al Makefile per /ucrt64/bin/node)
rem ed esegue scripts/run_refresh.sh, che lancia 'make refresh' e scrive il log in logs\.
set "MSYSTEM=UCRT64"
"C:\msys64\usr\bin\bash.exe" -l "%~dp0run_refresh.sh"
exit /b %ERRORLEVEL%
