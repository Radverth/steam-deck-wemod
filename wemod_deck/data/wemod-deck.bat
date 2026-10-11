@echo off
@title wemod-deck
REM Runs inside the game's Proton prefix, started by wemod-deck as:
REM   proton waitforexitandrun start <this.bat> <game.exe> [args...]
REM Headless version of upstream wemod.bat: it never waits for input.
REM   WEMOD_DECK_EXE            Windows path of Wand.exe / WeMod.exe (required)
REM   WEMOD_DECK_EARLY_SECONDS  a game that exits sooner than this is treated
REM                             as a launcher hand-off: the app is left open
REM                             (close it yourself or use Steam > Exit Game).
setlocal
set "appexe=%WEMOD_DECK_EXE%"
if not defined appexe goto rungame
for %%F in ("%appexe%") do set "appname=%%~nxF"
set "early=%WEMOD_DECK_EARLY_SECONDS%"
if not defined early set early=60

echo wemod-deck: starting %appexe%
start "" "%appexe%"

REM Give the app time to appear before the game starts (4 tries, 5 s apart).
set tries=0
:search
set appPID=
for /F "tokens=1,2 delims=," %%a in ('C:\windows\system32\tasklist.exe /FO CSV /NH /FI "IMAGENAME eq %appname%"') do set appPID=%%~b
if defined appPID goto found
set /A tries+=1
if %tries% GTR 3 goto notfound
ping -n 6 localhost >NUL
goto search
:notfound
echo wemod-deck: %appname% not seen in the process list, starting the game anyway
:found

:rungame
echo wemod-deck: running %*
call :seconds started
start /wait "" %*
call :seconds ended
set /A elapsed=ended-started
if %elapsed% LSS 0 set /A elapsed+=86400
echo wemod-deck: game exited after %elapsed% s
if not defined appexe goto done

if %elapsed% LSS %early% (
    echo wemod-deck: that was quick, probably a launcher handing off to the game.
    echo wemod-deck: leaving %appname% open; close it or use Steam ^> Exit Game.
    goto done
)
echo wemod-deck: closing %appname%
C:\windows\system32\taskkill.exe /IM %appname% /F >NUL 2>&1
C:\windows\system32\taskkill.exe /IM %appname% /F >NUL 2>&1

:done
endlocal
exit /b 0

REM Seconds since midnight from %time% ("H:MM:SS.cc", hour may be space-padded).
:seconds
set "t=%time: =0%"
for /F "tokens=1-3 delims=:.," %%a in ("%t%") do set /A "%1=(1%%a-100)*3600+(1%%b-100)*60+(1%%c-100)"
exit /b 0
