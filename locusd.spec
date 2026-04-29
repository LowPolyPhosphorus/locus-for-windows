# -*- mode: python ; coding: utf-8 -*-
# locusd.spec — Windows PyInstaller spec (replaces macOS version)
# Build with: pyinstaller locusd.spec

a = Analysis(
    ['locusd_entry.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('config.example.json', '.'),
    ],
    hiddenimports=[
        'focuslock.app',
        'focuslock.paths',
        'focuslock.analytics',
        'focuslock.session',
        'focuslock.dialogs',
        'focuslock.notion_client',
        'focuslock.ical_client',
        'focuslock.claude_client',
        'focuslock.url_monitor',
        'focuslock.app_blocker',
        # Windows-specific deps
        'win32gui',
        'win32process',
        'win32con',
        'win32api',
        'psutil',
        'websocket',
        'PyQt6',
        'PyQt6.QtWidgets',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # macOS-only — not present on Windows
        'rumps',
        'objc',
        'Cocoa',
        'AppKit',
        'Foundation',
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='locusd',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # no console window — runs as background process
    disable_windowed_traceback=False,
    argv_emulation=False,   # macOS-only flag, harmless but set False explicitly
    target_arch=None,
    codesign_identity=None, # macOS-only, ignored on Windows
    entitlements_file=None, # macOS-only, ignored on Windows
)
