# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['locusd_entry.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['focuslock.app', 'focuslock.paths', 'focuslock.analytics', 'focuslock.session', 'focuslock.dialogs', 'focuslock.notion_client', 'focuslock.ical_client', 'focuslock.claude_client', 'focuslock.url_monitor', 'focuslock.app_blocker'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
