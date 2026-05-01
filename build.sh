
#!/bin/bash

echo "[FlowDesk] Installing build dependencies..."
pip install pyinstaller pywebview pillow

echo "[FlowDesk] Checking for yolo26n.pt..."
if [ ! -f "yolo26n.pt" ]; then
    echo "Downloading YOLO26 model..."
    python -c "from ultralytics import YOLO; YOLO('yolo26n.pt')"
fi

echo "[FlowDesk] Building exe..."
pyinstaller FlowDesk.spec --clean --noconfirm

echo "Done! Check dist/ folder."