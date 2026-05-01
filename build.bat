@echo off
echo ========================================
echo  FlowDesk — Windows Build Script
echo ========================================
echo.

echo [FlowDesk] Installing dependencies...
pip install -r requirements.txt
pip install pywebview pyinstaller pillow

echo.
echo [FlowDesk] Checking for yolo26n.pt...
if not exist yolo26n.pt (
    echo Downloading YOLO26 model...
    python -c "from ultralytics import YOLO; m=YOLO('yolo26n.pt')"
    for /r "%USERPROFILE%\.cache\ultralytics" %%f in (yolo26n.pt) do copy "%%f" "yolo26n.pt"
)

echo.
echo [FlowDesk] Building FlowDesk.exe...
pyinstaller FlowDesk.spec --clean --noconfirm

echo.
echo ========================================
echo  Done! FlowDesk.exe is in dist\
echo.
echo  File size: approx 200-250 MB
echo  Copy dist\FlowDesk.exe to any Windows
echo  10 or 11 machine and run directly.
echo ========================================
pause
