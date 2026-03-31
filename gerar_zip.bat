@echo off
setlocal

cd /d "%~dp0"

if not exist "dist\Emissor documentos" (
  echo Nao encontrei dist\Emissor documentos. Gere o EXE primeiro.
  pause
  exit /b 1
)

if exist "assets\icon.ico" (
  copy /y "assets\icon.ico" "dist\Emissor documentos\icon.ico" >nul
)

set "ZIP_DEST=%CD%\EmissorCurto.zip"
if exist "%ZIP_DEST%" del /f /q "%ZIP_DEST%"

powershell -NoProfile -Command "Compress-Archive -Path 'dist\Emissor documentos\*' -DestinationPath '%ZIP_DEST%' -Force"

echo.
echo ZIP gerado em: %ZIP_DEST%
