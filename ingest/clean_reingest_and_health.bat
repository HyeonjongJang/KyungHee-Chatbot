@echo off
setlocal

rem ===== 설정 =====
set "FUSEKI_DIR=C:\tools\apache-jena-fuseki-4.10.0"
set "PORT=3030"
set "DATASET=ds"
set "TDB2_DIR=C:\fuseki-base"

set "OUT_TTL=%~dp0out.ttl"
set "GRAPH_URI=http://kg.khu.ac.kr/graph/regulations"

rem 인증(필요 시)
set "ADMIN_USER="
set "ADMIN_PASS="
rem =================

set "CURL_AUTH="
if not "%ADMIN_USER%"=="" if not "%ADMIN_PASS%"=="" set "CURL_AUTH=-u %ADMIN_USER%:%ADMIN_PASS%"

echo [0] Preflight...
where curl >nul 2>nul || (echo [ERR] curl not found & goto :eof)
if not exist "%FUSEKI_DIR%\fuseki-server.bat" ( echo [ERR] Fuseki not found: %FUSEKI_DIR%\fuseki-server.bat & goto :eof )
if not exist "%TDB2_DIR%" ( echo [i] Create TDB2 dir: %TDB2_DIR% & mkdir "%TDB2_DIR%" >nul 2>nul )

echo [1] Check server...
curl -s "http://localhost:%PORT%/$/ping" >nul 2>nul
if errorlevel 1 (
  echo     Start Fuseki TDB2...
  start "Fuseki %DATASET%" "%FUSEKI_DIR%\fuseki-server.bat" --port %PORT% --update --loc="%TDB2_DIR%" /%DATASET%
)

echo [2] Wait ready...
set tries=0
:wait_loop
set /a tries+=1
if %tries% GTR 120 ( echo [ERR] server not ready ~120s & exit /b 1 )
curl -s "http://localhost:%PORT%/$/ping" >nul 2>nul || ( ping -n 2 127.0.0.1 >nul & goto wait_loop )
echo     OK: http://localhost:%PORT%/%DATASET%/

if not exist "%OUT_TTL%" ( echo [ERR] TTL not found: %OUT_TTL% & exit /b 1 )

echo [3] CLEAR named and default graphs
curl %CURL_AUTH% -X POST "http://localhost:%PORT%/%DATASET%/update" --data-urlencode "update=CLEAR GRAPH <%GRAPH_URI%>"
curl %CURL_AUTH% -X POST "http://localhost:%PORT%/%DATASET%/update" --data-urlencode "update=CLEAR DEFAULT"

echo [4] Upload to NAMED: %GRAPH_URI%
curl %CURL_AUTH% -X POST -H "Content-Type: text/turtle" --data-binary "@%OUT_TTL%" "http://localhost:%PORT%/%DATASET%?graph=%GRAPH_URI%"
if errorlevel 1 ( echo [ERR] upload failed & exit /b 1 )

echo [5] Health checks
set "TMP_RQ=%TEMP%\fuseki_rq_clean"
mkdir "%TMP_RQ%" >nul 2>nul

powershell -NoProfile -Command ^
  "$q='SELECT (COUNT(*) AS ?n) WHERE { GRAPH <%GRAPH_URI%> { ?s a <https://kg.khu.ac.kr/uni#Clause> . } }';" ^
  "[System.IO.File]::WriteAllText('%TMP_RQ%\q1.rq',$q,[System.Text.Encoding]::UTF8)" >nul 2>nul
echo   - Clauses (named)
curl %CURL_AUTH% -G "http://localhost:%PORT%/%DATASET%/query" --data-urlencode "query@%TMP_RQ%\q1.rq"

powershell -NoProfile -Command ^
  "$q='SELECT ?g (COUNT(*) AS ?n) WHERE { GRAPH ?g { ?s ?p ?o } } GROUP BY ?g ORDER BY DESC(?n) LIMIT 10';" ^
  "[System.IO.File]::WriteAllText('%TMP_RQ%\q2.rq',$q,[System.Text.Encoding]::UTF8)" >nul 2>nul
echo   - Graph list
curl %CURL_AUTH% -G "http://localhost:%PORT%/%DATASET%/query" --data-urlencode "query@%TMP_RQ%\q2.rq"

echo [6] Done - UI http://localhost:%PORT%/%DATASET%/
exit /b 0
