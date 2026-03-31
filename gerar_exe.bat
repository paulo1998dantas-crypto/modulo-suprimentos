@echo off
setlocal

cd /d "%~dp0"

if not exist ".venv\Scripts\activate.bat" (
  echo Ambiente virtual nao encontrado em .venv. Crie o venv antes de gerar o EXE.
  pause
  exit /b 1
)

call ".venv\Scripts\activate.bat"

pyinstaller --noconfirm --clean --noconsole --name "Emissor documentos" ^
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

echo.
echo Build concluido. Saida em: %CD%\dist\Emissor documentos
pause
