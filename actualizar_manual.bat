@echo off
REM ============================================================================
REM  actualizar_manual.bat
REM  Rutina diaria: traduce DESCARGAS DIARIAS -> DATOS_CSV y lo sube al repo,
REM  para que el cron de GitHub (22:30 Madrid) use TUS datos manuales.
REM
REM  Uso: doble clic, o desde cmd:  actualizar_manual.bat
REM ============================================================================

cd /d C:\Users\m21lo\nq-proxy

echo.
echo ============================================================
echo   1/2  Traduciendo DESCARGAS DIARIAS  -^>  DATOS_CSV
echo ============================================================
python preparar_datos.py
if errorlevel 1 goto ERROR_PREPARAR

echo.
echo ============================================================
echo   2/2  Subiendo DATOS_CSV al repositorio
echo ============================================================
REM Orden correcto: primero commiteamos LO NUESTRO (deja el working tree
REM limpio), y DESPUES hacemos pull --rebase (git SI sabe rebasear un commit
REM local tuyo sobre lo nuevo que haya llegado del cron). Al reves (pull antes
REM de commitear) siempre falla con "cannot pull with rebase: unstaged changes"
REM porque preparar_datos.py acaba de dejar DATOS_CSV modificado sin commitear.
git add DATOS_CSV PCR.txt
git commit -m "data manual: DATOS_CSV + PCR.txt %date% %time%"
if errorlevel 1 echo   (sin cambios que commitear, o commit vacio - continuando)

git pull --rebase
if errorlevel 1 goto ERROR_PULL

git push
if errorlevel 1 goto ERROR_PUSH

echo.
echo ============================================================
echo   LISTO. El cron de las 22:30 (L-V) usara estos datos.
echo ============================================================
goto FIN

:ERROR_PREPARAR
echo.
echo  *** ERROR en preparar_datos.py. No se sube nada. Revisa el mensaje. ***
pause
exit /b 1

:ERROR_PULL
echo.
echo  *** git pull --rebase fallo (posible conflicto real con el remoto). ***
echo  *** Tu commit local SI se hizo, no se ha perdido nada. ***
echo  *** Revisa manualmente con: git status ***
pause
exit /b 1

:ERROR_PUSH
echo.
echo  *** git push fallo. Tu commit local esta a salvo, solo falta subirlo. ***
echo  *** Revisa tu conexion/credenciales y ejecuta:  git push ***
pause
exit /b 1

:FIN
pause
