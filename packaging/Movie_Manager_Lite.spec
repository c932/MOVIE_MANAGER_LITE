# -*- mode: python ; coding: utf-8 -*-
import os
ROOT = os.path.abspath(os.path.join(SPECPATH, '..'))

a = Analysis(
    [os.path.join(ROOT, 'main.py')],
    pathex=[ROOT],
    binaries=[],
    datas=[
        (os.path.join(ROOT, 'logo'), 'logo'),
        (os.path.join(ROOT, 'styles'), 'styles'),
        (os.path.join(ROOT, 'Movie_Manager_Lite.ico'), '.'),
    ],
    hiddenimports=[
        'PyQt6.sip',
        'PyQt6.QtSvg',
        'scraper',
        'scraper.douban_cli',
        'scraper.douban_ranking',
        'scraper.new_movie_checker',
        'scraper.qt_tasks',
        'utils.bilibili',
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
    name='LocalMovieWall',
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
    name='LocalMovieWall',
)
