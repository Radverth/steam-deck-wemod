@echo off
@title wemod-deck
REM Runs inside the game's Proton prefix, started by wemod-deck as:
REM   proton waitforexitandrun start <this.bat> <game.exe> [args...]
REM Headless version of upstream wemod.bat: it never waits for input.
REM   WEMOD_DECK_EXE            Windows path of Wand.exe / WeMod.exe (required)
REM   WEMOD_DECK_EARLY_SECONDS  a game that exits sooner than this is treated
REM                             as a launcher hand-off: the app is left open
REM                             (close it yourself or use Steam > Exit Game).
if "%~1"==":wemod-deck-timer" goto timer
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
REM A background copy of this file creates %marker% after %early% seconds.
REM If it exists when the game exits, the game ran long enough. (No %TIME%
REM maths: its format depends on the locale and may lack seconds.)
set "marker=%TEMP%\wemod-deck-ran-%RANDOM%%RANDOM%.tmp"
if exist "%marker%" del "%marker%"
set /A pings=early+1
start "" /b cmd /c call "%~f0" :wemod-deck-timer "%marker%" %pings%

echo wemod-deck: running %*
start /wait "" %*
if not defined appexe goto done

if not exist "%marker%" (
    echo wemod-deck: the game exited within %early% s, probably a launcher handing off.
    echo wemod-deck: leaving %appname% open; close it or use Steam ^> Exit Game.
    goto done
)
del "%marker%"
echo wemod-deck: closing %appname%
C:\windows\system32\taskkill.exe /IM %appname% /F >NUL 2>&1
C:\windows\system32\taskkill.exe /IM %appname% /F >NUL 2>&1

:done
endlocal
exit /b 0

REM Background timer: <this.bat> :wemod-deck-timer <marker> <pings>
:timer
ping -n %~3 localhost >NUL
type nul > "%~2"
exit /b 0
