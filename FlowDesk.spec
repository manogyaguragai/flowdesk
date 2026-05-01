# -*- mode: python ; coding: utf-8 -*-
"""
FlowDesk.spec — PyInstaller spec for building FlowDesk.exe

Build with:  pyinstaller FlowDesk.spec --clean --noconfirm
Output:      dist/FlowDesk.exe  (single-file, no console window)
"""

a = Analysis(
    ['launcher.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('frontend', 'frontend'),
        ('models/yolo26n.pt', 'models'),
    ],
    hiddenimports=[
        'ultralytics',
        'ultralytics.nn',
        'ultralytics.nn.tasks',
        'ultralytics.nn.modules',
        'ultralytics.utils',
        'ultralytics.data',
        'ultralytics.models',
        'nepali_datetime',
        'apscheduler',
        'apscheduler.schedulers.background',
        'apscheduler.triggers.cron',
        'cv2',
        'numpy',
        'fastapi',
        'uvicorn',
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        'webview',
        'PIL',
        'clr',
    ],
    hookspath=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    name='FlowDesk',
    debug=False,
    console=False,
    icon=None,
)
