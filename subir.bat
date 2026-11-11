@echo off
setlocal
title Subir la tabla de tipos de cambio a GitHub
cd /d "%~dp0"
rem el repositorio publico de la tabla (solo esta herramienta): github.com/ElvisChatzky/tipos-de-cambio
set "REPO=https://github.com/ElvisChatzky/tipos-de-cambio.git"
where git >nul 2>&1
if errorlevel 1 (
  echo No encuentro git en esta computadora.
  pause
  exit /b 1
)
rem el trabajo programado de GitHub va en .github\workflows; Claude no puede escribir ahi, asi que lo deja al lado y este paso lo pone en su lugar
if exist "actualizar.yml" (
  echo Este paso pone el trabajo programado de GitHub ^(actualizar.yml^) en .github\workflows.
  echo Es el que baja las cotizaciones y publica la tabla cada hora. Se puede leer antes: es un archivo de texto, comentado.
  choice /c SN /m "Lo pongo"
  if errorlevel 2 exit /b 0
  if not exist ".github\workflows" mkdir ".github\workflows"
  move /y "actualizar.yml" ".github\workflows\actualizar.yml" >nul || goto error
)
if not exist ".git" (
  git init -b main || goto error
  git remote add origin "%REPO%" || goto error
  git add -A || goto error
  git commit -m "Tabla de tipos de cambio del dolar (BNA)" || goto error
  git push -u origin main || goto error
  goto listo
)
git add -A || goto error
git diff --cached --quiet
if errorlevel 1 (
  git commit -m "Tabla de tipos de cambio: cambios" || goto error
)
rem GitHub guarda las cotizaciones nuevas en el repositorio: primero se traen, despues se sube lo de aca
git pull --rebase origin main || goto error
git push origin main || goto error

:listo
echo.
echo Listo. En unos minutos queda publicada en https://elvischatzky.github.io/tipos-de-cambio/
echo Para ver como fue: https://github.com/ElvisChatzky/tipos-de-cambio/actions
pause
exit /b 0

:error
echo.
echo No se pudo subir: el motivo esta arriba.
pause
exit /b 1
