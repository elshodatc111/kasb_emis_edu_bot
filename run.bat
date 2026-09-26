@echo off
chcp 65001 >nul
cd /d %~dp0
if not exist .venv\Scripts\python.exe (
  echo .venv topilmadi, avval setup.bat ni ishga tushiring.
  pause & exit /b 1
)
.venv\Scripts\python.exe -c "import dotenv, aiogram, fastapi, openai" 2>nul
if errorlevel 1 (
  echo Kutubxonalar o'rnatilmagan, o'rnatilmoqda...
  .venv\Scripts\python.exe -m pip install -r requirements.txt
  if errorlevel 1 (
    echo XATO: o'rnatib bo'lmadi. Yuqoridagi xato matnini chatga yuboring.
    pause & exit /b 1
  )
)
.venv\Scripts\python.exe -m app.main
pause
