@echo off
setlocal

cd /d "%~dp0"

if not exist "gerar_exe.bat" (
  echo gerar_exe.bat nao encontrado.
  pause
  exit /b 1
)

call "gerar_exe.bat"
if errorlevel 1 (
  echo Falha ao gerar o EXE.
  pause
  exit /b 1
)

if not exist "gerar_zip.bat" (
  echo gerar_zip.bat nao encontrado.
  pause
  exit /b 1
)

call "gerar_zip.bat"
