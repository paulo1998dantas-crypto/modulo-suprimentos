@echo off
setlocal

cd /d "%~dp0"

if not exist ".venv\Scripts\activate.bat" (
  echo Ambiente virtual nao encontrado em .venv. Crie o venv antes de gerar o EXE.
  exit /b 1
)

call ".venv\Scripts\activate.bat"

set "BUILD_NAME=ModuloSuprimentos"
set "DIST_DIR=%CD%\dist\%BUILD_NAME%"
set "ENVIO_DIR=%CD%\ModuloSuprimentos_envio"
set "ZIP_DEST=%CD%\ModuloSuprimentos_envio.zip"

if exist "%DIST_DIR%" rmdir /s /q "%DIST_DIR%"
if exist "%ENVIO_DIR%" rmdir /s /q "%ENVIO_DIR%"
if exist "%ZIP_DEST%" del /f /q "%ZIP_DEST%"

pyinstaller --noconfirm --clean --noconsole --name "%BUILD_NAME%" ^
  --icon "assets\icon.ico" ^
  --add-data "compras_app;compras_app" ^
  --add-data "compras_app\template_word;template_word" ^
  --add-data "compras_app\data;data" ^
  --hidden-import openpyxl ^
  --hidden-import PIL ^
  --hidden-import PIL.Image ^
  --collect-all pillow ^
  --collect-all pypdfium2 ^
  compras_app\app.py

if errorlevel 1 (
  echo Falha ao gerar o EXE.
  exit /b 1
)

robocopy "%DIST_DIR%" "%ENVIO_DIR%" /MIR >nul
set "ROBOCOPY_EXIT=%ERRORLEVEL%"
if %ROBOCOPY_EXIT% GEQ 8 (
  echo Falha ao copiar arquivos para %ENVIO_DIR%.
  exit /b %ROBOCOPY_EXIT%
)

if exist "assets\icon.ico" (
  copy /y "assets\icon.ico" "%ENVIO_DIR%\icon.ico" >nul
)

powershell -NoProfile -Command "Compress-Archive -Path 'ModuloSuprimentos_envio\\*' -DestinationPath 'ModuloSuprimentos_envio.zip' -Force"
if errorlevel 1 (
  echo Falha ao gerar o ZIP.
  exit /b 1
)

echo.
echo Build concluido.
echo EXE: %ENVIO_DIR%\ModuloSuprimentos.exe
echo PASTA: %ENVIO_DIR%
echo ZIP: %ZIP_DEST%

