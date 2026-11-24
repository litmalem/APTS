@echo off
setlocal

if not exist .venv (
    py -m venv .venv
)

call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt pyinstaller
pyinstaller --noconfirm --clean --windowed --name VulnDesk --add-data ".env;." main.py

echo.
echo Build selesai. Lihat folder dist\VulnDesk
pause
