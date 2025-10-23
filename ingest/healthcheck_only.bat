@echo off
setlocal

set "PORT=3030"
set "DATASET=ds"
set "GRAPH_URI=http://kg.khu.ac.kr/graph/regulations"
set "BASE=http://localhost:%PORT%"
set "QUERY_URL=%BASE%/%DATASET%/query"

echo [H] Ping...
curl -s "%BASE%/$/ping" >nul 2>nul || ( echo [ERR] server down & exit /b 2 )

REM PowerShell로 쿼리 실행 + JSON 파싱 + 종료코드 반환
powershell -NoProfile -Command ^
  "$base='%BASE%'; $ds='%DATASET%'; $graph='%GRAPH_URI%';" ^
  "try {" ^
  "  $q='SELECT (COUNT(*) AS ?n) WHERE { GRAPH <'+$graph+'> { ?s a <https://kg.khu.ac.kr/uni#Clause> . } }';" ^
  "  $enc=[Uri]::EscapeDataString($q);" ^
  "  $url=$base+'/'+$ds+'/query?query='+$enc;" ^
  "  $res=Invoke-RestMethod -Method Get -Uri $url -ErrorAction Stop;" ^
  "  if(-not $res.results -or -not $res.results.bindings -or $res.results.bindings.Count -eq 0) { Write-Output '[ERR] empty bindings'; exit 5 }" ^
  "  $n=[int]$res.results.bindings[0].n.value;" ^
  "  Write-Output ('[H] Clauses(named)='+$n);" ^
  "  if($n -lt 1){ exit 5 } else { exit 0 }" ^
  "} catch { Write-Output ('[ERR] '+$_.Exception.Message); exit 3 }"

exit /b %ERRORLEVEL%
