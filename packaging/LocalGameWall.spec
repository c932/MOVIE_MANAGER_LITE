# -*- mode: python ; coding: utf-8 -*-
import os
ROOT = os.path.abspath(os.path.join(SPECPATH, '..'))

a = Analysis(
    [os.path.join(ROOT, 'game_main.py')],
    pathex=[ROOT],
    binaries=[],
    datas=[
        (os.path.join(ROOT, 'styles'), 'styles'),
    ],
    hiddenimports=[
        'PyQt6.sip',
        'openpyxl',
        'gamewall',
        'gamewall.game_models',
        'gamewall.name_utils',
        'gamewall.excel_parser',
        'gamewall.game_cache',
        'gamewall.steam_client',
        'gamewall.enrichment_worker',
        'gamewall.rating_scrapers',
        'gamewall.local_scanner',
        'gamewall.lnk_parser',
        'gamewall.cover_loader',
        'gamewall.game_card',
        'gamewall.game_detail_panel',
        'gamewall.game_main_window',
        'gamewall.settings_dialog',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='LocalGameWall',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(ROOT, 'Movie_Manager_Lite.ico'),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='LocalGameWall',
)
