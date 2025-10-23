@echo off
setlocal

rem ===== 설정 =====
set "FUSEKI_DIR=C:\tools\apache-jena-fuseki-4.10.0"
set "PORT=3030"
set "DATASET=ds"
set "TDB2_DIR=C:\fuseki-base"

set "OUT_TTL=%~dp0out.ttl"
set "GRAPH_URI=http://kg.khu.ac.kr/graph/regulations"
set "UPLOAD_TO_NAMED=1"
set "UPLOAD_TO_DEFAULT=0"

set "ADMIN_USER="
set "ADMIN_PASS="
rem =================

set "CURL_AUTH="
if not "%ADMIN_USER%"=="" if not "%ADMIN_PASS%"=="" set "CURL_AUTH=-u %ADMIN_USER%:%ADMIN_PASS%"

echo [0] Preflight...
where curl >nul 2>nul || (echo [ERR] curl not found & goto :eof)
if not exist "%FUSEKI_DIR%\fuseki-server.bat" ( echo [ERR] Fuseki not found: %FUSEKI_DIR%\fuseki-server.bat & goto :eof )
if not exist "%TDB2_DIR%" ( echo [i] Create TDB2 dir: %TDB2_DIR% & mkdir "%TDB2_DIR%" >nul 2>nul )

echo [1] Checking server on http://localhost:%PORT%/
curl -s "http://localhost:%PORT%/$/ping" >nul 2>nul
if errorlevel 1 goto start_server
echo     Already running.
goto wait_ready

:start_server
echo     Not running. Starting Fuseki TDB2...
start "Fuseki %DATASET%" "%FUSEKI_DIR%\fuseki-server.bat" --port %PORT% --update --loc="%TDB2_DIR%" /%DATASET%

:wait_ready
echo [2] Waiting server ready...
set tries=0
:wait_loop
set /a tries+=1
if %tries% GTR 120 ( echo [ERR] server not ready after ~120s & goto :eof )
curl -s "http://localhost:%PORT%/$/ping" >nul 2>nul || ( ping -n 2 127.0.0.1 >nul & goto wait_loop )
echo     OK: http://localhost:%PORT%/%DATASET%/

if not exist "%OUT_TTL%" ( echo [WARN] Skip upload - TTL not found: %OUT_TTL% & goto health )

if "%UPLOAD_TO_NAMED%"=="1" goto upload_named
goto check_default

:upload_named
echo [3a] Upload to named graph: %GRAPH_URI%
curl %CURL_AUTH% -X POST -H "Content-Type: text/turtle" --data-binary "@%OUT_TTL%" "http://localhost:%PORT%/%DATASET%?graph=%GRAPH_URI%"
if errorlevel 1 ( echo [ERR] named-graph upload failed & goto :eof )

:check_default
if "%UPLOAD_TO_DEFAULT%"=="1" goto upload_default
goto health

:upload_default
echo [3b] Upload to default graph
curl %CURL_AUTH% -X POST -H "Content-Type: text/turtle" --data-binary "@%OUT_TTL%" "http://localhost:%PORT%/%DATASET%?default"
if errorlevel 1 ( echo [ERR] default-graph upload failed & goto :eof )

:health
echo [4] Health checks - writing rq files

set "TMP_RQ=%TEMP%\fuseki_rq"
mkdir "%TMP_RQ%" >nul 2>nul

rem Q1 named graph count
powershell -NoProfile -Command ^
  "$q='SELECT (COUNT(*) AS ?n) WHERE { GRAPH <%GRAPH_URI%> { ?s a <https://kg.khu.ac.kr/uni#Clause> . } }';" ^
  "[System.IO.File]::WriteAllText('%TMP_RQ%\q1.rq',$q,[System.Text.Encoding]::UTF8)" >nul 2>nul
echo   - Count Clauses named
curl %CURL_AUTH% -G "http://localhost:%PORT%/%DATASET%/query" --data-urlencode "query@%TMP_RQ%\q1.rq"
echo.

rem Q2 default graph count
powershell -NoProfile -Command ^
  "$q='SELECT (COUNT(*) AS ?n) WHERE { ?s a <https://kg.khu.ac.kr/uni#Clause> . }';" ^
  "[System.IO.File]::WriteAllText('%TMP_RQ%\q2.rq',$q,[System.Text.Encoding]::UTF8)" >nul 2>nul
echo   - Count Clauses default
curl %CURL_AUTH% -G "http://localhost:%PORT%/%DATASET%/query" --data-urlencode "query@%TMP_RQ%\q2.rq"
echo.

rem Q3 graph list
powershell -NoProfile -Command ^
  "$q='SELECT ?g (COUNT(*) AS ?n) WHERE { GRAPH ?g { ?s ?p ?o } } GROUP BY ?g ORDER BY DESC(?n) LIMIT 5';" ^
  "[System.IO.File]::WriteAllText('%TMP_RQ%\q3.rq',$q,[System.Text.Encoding]::UTF8)" >nul 2>nul
echo   - Graph list top 5
curl %CURL_AUTH% -G "http://localhost:%PORT%/%DATASET%/query" --data-urlencode "query@%TMP_RQ%\q3.rq"
echo.

echo [5] Done - UI http://localhost:%PORT%/%DATASET%/
goto :eof
