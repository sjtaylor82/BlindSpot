# Build from the BlindSpot directory with:
# python -m PyInstaller --noconfirm BlindSpot.spec

import sys
from pathlib import Path

import wx


binaries = []
if sys.platform == "win32":
    webview2_loader = Path(wx.__file__).resolve().parent / "WebView2Loader.dll"
    if not webview2_loader.is_file():
        raise FileNotFoundError(
            f"wxPython WebView2 loader was not found: {webview2_loader}"
        )
    binaries.append((str(webview2_loader), "wx"))


a = Analysis(
    ["src/blindspot_launcher.py"],
    pathex=["src"],
    binaries=binaries,
    datas=[
        ("manual.html", "."),
        ("LICENSE", "."),
        ("portable_updater.ps1", "."),
    ],
    hiddenimports=(
        ["appscript", "accessible_output2.outputs.voiceover"]
        if sys.platform == "darwin"
        else []
    ),
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="BlindSpot",
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="BlindSpot",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="BlindSpot.app",
        bundle_identifier="au.com.blindspot.player",
        info_plist={
            "CFBundleDisplayName": "BlindSpot",
            "CFBundleName": "BlindSpot",
            "NSPrincipalClass": "NSApplication",
            "NSHighResolutionCapable": True,
        },
    )
