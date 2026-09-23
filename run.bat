@echo off
rem ---------------------------------------------------------------
rem  Korean text is printed by run_all.py, not by this file.
rem  cmd.exe reads .bat in the system ANSI codepage, so Korean here
rem  would be mangled on some machines. Keep this file ASCII only.
rem ---------------------------------------------------------------
setlocal
cd /d "%~dp0"

set PY=
for %%C in (python py python3) do (
  if not defined PY (
    %%C -c "import sys" >nul 2>&1 && set PY=%%C
  )
)

if not defined PY (
  echo.
  echo   Python not found.
  echo   Install it from python.org and check "Add Python to PATH".
  echo   ^(python.org 에서 설치할 때 Add Python to PATH 를 체크하세요^)
  echo.
  pause
  exit /b 1
)

%PY% -X utf8 "scripts\run_all.py" %*
if errorlevel 1 pause
exit /b %errorlevel%
