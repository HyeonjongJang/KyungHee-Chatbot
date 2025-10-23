@echo off
setlocal ENABLEDELAYEDEXPANSION

REM ===== 설정 =====
set FUSEKI_VER=4.10.0
set PORT=3030
set DATASET=ds
REM MODE=MEM 또는 TDB2
set MODE=MEM
set TDB2_DIR=C:\fuseki-base
set GRAPH_URI=http://kg.khu.ac.kr/graph/regulations
set OUT_TTL=%~dp0out.ttl
set ADMIN_USER=
set ADMIN_PASS=
REM =================

set FUSEKI_BASE=C:\tools\apache-jena-fuseki-%FUSEKI_VER%
set FUSEKI_ZIP=%TEMP%\fuseki.zip
set URL=https://archive.apache.org/dist/jena/binaries/apache-jena-fuseki-%FUSEKI_VER%.zip
set CURL_AUTH=
if not "%ADMIN_USER%"=="" if not "%ADMIN_PASS%"=="" set CURL_AUTH=-u %ADMIN_USER%:%ADMIN_PASS%
set MIN_SIZE=5000000

echo [0] preflight...
where curl >nul 2>nul || (echo [ERR] curl not found & exit /b 1)
if not exist "C:\tools" mkdir "C:\tools" >nul 2>nul

echo [1] download: %URL%
del "%FUSEKI_ZIP%" >nul 2>nul
curl -L -o "%FUSEKI_ZIP%" "%URL%"
for %%F in ("%FUSEKI_ZIP%") do set SIZE=%%~zF
echo     size=%SIZE% bytes
if "%SIZE%"=="" (echo [ERR] download failed & goto :fail)
if %SIZE% LSS %MIN_SIZE% (
  echo [ERR] downloaded file too small. If behind a proxy, download manually:
  echo   %URL%
  echo   save as: %FUSEKI_ZIP%
  pause
  goto :fail
)

echo [2] extract to %FUSEKI_BASE% ...
rmdir /s /q "%FUSEKI_BASE%" >nul 2>nul
tar -xf "%FUSEKI_ZIP%" -C "C:\tools"
if not exist "%FUSEKI_BASE%\fuseki-server.bat" (
  echo [ERR] fuseki-server.bat not found under %FUSEKI_BASE%
  goto :fail
)

echo [3] start fuseki (port=%PORT% dataset=/%DATASET% mode=%MODE%) ...
if /I "%MODE%"=="TDB2" (
  if not exist "%TDB2_DIR%" mkdir "%TDB2_DIR%" >nul 2>nul
  start "Fuseki %DATASET%" "%FUSEKI_BASE%\fuseki-server.bat" --port %PORT% --update --loc="%TDB2_DIR%" /%DATASET%
) else (
  start "Fuseki %DATASET%" "%FUSEKI_BASE%\fuseki-server.bat" --port %PORT% --update --mem /%DATASET%
)

echo     waiting server...
set tries=0
:wait
set /a tries=tries+1
if %tries% GTR 40 (echo [ERR] server not ready & goto :fail)
curl -s "http://localhost:%PORT%/" >nul 2>nul || (ping -n 1 127.0.0.1 >nul & goto :wait)
echo     up: http://localhost:%PORT%/%DATASET%/

if not exist "%OUT_TTL%" (
  echo [4] skip upload: not found %OUT_TTL%
  goto :health
)

echo [4] upload %OUT_TTL% -> graph=%GRAPH_URI%
curl %CURL_AUTH% -X POST -H "Content-Type: text/turtle" --data-binary "@%OUT_TTL%" "http://localhost:%PORT%/%DATASET%?graph=%GRAPH_URI%"
if errorlevel 1 (echo [ERR] upload failed & goto :fail)

:health
echo [5] SPARQL count
set Q=SELECT (COUNT(*) AS ?n) WHERE { ?s a ^<https://kg.khu.ac.kr/uni#Clause^> . }
curl %CURL_AUTH% -G "http://localhost:%PORT%/%DATASET%/query" --data-urlencode "query=%Q%"
echo.
echo [6] done. UI: http://localhost:%PORT%/%DATASET%/
exit /b 0

:fail
echo FAILED.
exit /b 1
