@echo off
setlocal DisableDelayedExpansion
set "compiler=%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if not exist "%compiler%" set "compiler=%WINDIR%\Microsoft.NET\Framework\v4.0.30319\csc.exe"
if not exist "%compiler%" (
  echo The Windows .NET Framework C# compiler is unavailable.
  exit /b 1
)
set "destination=%~dp0build"
if not "%~1"=="" set "destination=%~f1"
if not exist "%destination%" mkdir "%destination%"
"%compiler%" /nologo /target:winexe /platform:anycpu /optimize+ /utf8output /out:"%destination%\ROB_RUN_CN.exe" /win32manifest:"%~dp0app.manifest" /r:System.Windows.Forms.dll /r:System.Drawing.dll /r:System.Web.Extensions.dll /r:System.Core.dll "%~dp0Program.cs" "%~dp0Manager.cs" "%~dp0DeltaPatch.cs"
if errorlevel 1 exit /b %errorlevel%
if not exist "%destination%\data\addon" mkdir "%destination%\data\addon"
copy /y "%~dp0..\data\addon\manifest.json" "%destination%\data\addon\manifest.json" >nul
if errorlevel 1 exit /b 1
for %%F in ("%~dp0..\data\addon\*.rrpatch" "%~dp0..\data\addon\catalog.hash") do (
  copy /y "%%~F" "%destination%\data\addon\%%~nxF" >nul
  if errorlevel 1 exit /b 1
)
for %%F in (DISCLAIMER.md THIRD_PARTY_NOTICES.md FONT_LICENSE.txt LIBERTINUS_LICENSE.txt BSDIFF4_LICENSE.txt README.md) do (
  copy /y "%~dp0..\%%F" "%destination%\%%F" >nul
  if errorlevel 1 exit /b 1
)
copy /y "%~dp0start.bat" "%destination%\start.bat" >nul
exit /b %errorlevel%
