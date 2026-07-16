# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — 凍結成 desktop/dist/SimStock.app（選單列 agent app）。

從專案根目錄執行： pyinstaller desktop/SimStock-app.spec
"""
import os
import sys
from PyInstaller.utils.hooks import collect_submodules

# spec 在 desktop/ 底下，PyInstaller 以 spec 所在目錄解析相對路徑 → 一律用專案根的絕對路徑
ROOT = os.path.dirname(SPECPATH)  # noqa: F821  (SPECPATH 由 PyInstaller 注入)
sys.path.insert(0, ROOT)          # 讓 collect_submodules("backend") 找得到本地套件

hidden = (
    collect_submodules("uvicorn")
    + collect_submodules("backend")
    + collect_submodules("starlette")
    + ["fastapi", "anyio", "h11", "httpx", "httpcore", "certifi", "rumps"]
)

_icns = os.path.join(ROOT, "desktop/icon.icns")
icon = _icns if os.path.exists(_icns) else None

_datas = [
    (os.path.join(ROOT, "frontend"), "frontend"),
    (os.path.join(ROOT, "desktop/menubar-icon.png"), "."),
]
_sample = os.path.join(ROOT, "desktop/sample-save.json")
if os.path.exists(_sample):
    _datas.append((_sample, "."))

a = Analysis(
    [os.path.join(ROOT, "desktop/app.py")],
    pathex=[ROOT],
    binaries=[],
    datas=_datas,
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    # 固定 loop=asyncio / http=h11，故 uvicorn[standard] 的原生加速套件全不需要；
    # 連同 GUI 桌面 app 用不到的 stdlib 一併排除以縮小體積。
    excludes=[
        "uvloop", "httptools", "watchfiles", "websockets", "yaml",
        "tkinter", "_tkinter", "turtledemo", "idlelib",
        "test", "tests", "lib2to3", "pydoc_data", "distutils",
        "setuptools", "pip", "ensurepip",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="SimStock",
          debug=False, strip=True, upx=False, console=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=True, upx=False, name="SimStock")
app = BUNDLE(
    coll,
    name="SimStock.app",
    icon=icon,
    bundle_identifier="com.rocavence.simstock",
    info_plist={
        "LSUIElement": True,  # 選單列 agent，不佔 Dock
        "CFBundleName": "SimStock",
        "CFBundleDisplayName": "台股模擬交易",
        "CFBundleShortVersionString": "0.1",
        "CFBundleVersion": "0.1",
        "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},  # 允許連 127.0.0.1
        "NSHighResolutionCapable": True,
    },
)
