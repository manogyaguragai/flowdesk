# -*- mode: python ; coding: utf-8 -*-
"""
FlowDesk.spec — PyInstaller spec for building FlowDesk.exe

Build with:  pyinstaller FlowDesk.spec --clean --noconfirm
Output:      dist/FlowDesk.exe  (single-file, no console window)
"""
import os, sys
site_packages = os.path.join(os.path.dirname(sys.executable), '..', 'Lib', 'site-packages')

a = Analysis(
    ['launcher.py'],
    pathex=['.'],
    binaries=[],
    datas=[
    ('frontend', 'frontend'),
    ('assets', 'assets'),
    ('models/yolo26n.pt', 'models'),
    (os.path.join(site_packages, 'nepali_datetime', 'data'), 'nepali_datetime/data'),
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
        'multiprocessing',
        'multiprocessing.resource_tracker',
        'logging',
        'logging.handlers',
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
    icon='assets/flowdesk.ico',
)
