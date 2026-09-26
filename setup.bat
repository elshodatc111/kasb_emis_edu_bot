@echo off
chcp 65001 >nul
cd /d %~dp0
echo === Texnikum yordamchi: o'rnatish ===
if not exist .venv\Scripts\python.exe (
  py -3.14 -m venv .venv 2>nul || py -3 -m venv .venv 2>nul || python -m venv .venv
)
if not exist .venv\Scripts\python.exe (
  echo XATO: Python topilmadi. Python 3.12+ o'rnating: https://www.python.org/downloads/
  pause & exit /b 1
)
.venv\Scripts\python.exe --version
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo XATO: kutubxonalarni o'rnatib bo'lmadi. Yuqoridagi xato matnini chatga yuboring.
  pause & exit /b 1
)
.venv\Scripts\python.exe -c "import dotenv, aiogram, fastapi, openai; print('Kutubxonalar OK')"
if errorlevel 1 (
  echo XATO: o'rnatilgan, lekin import qilinmadi. Xato matnini chatga yuboring.
  pause & exit /b 1
)
if not exist .env copy .env.example .env >nul
echo.
echo Tayyor. Endi .env faylini oching va BOT_TOKEN, ADMIN_IDS, OPENAI_API_KEY ni to'ldiring.
echo Keyin check.bat (tekshirish) va run.bat (ishga tushirish).
pause
