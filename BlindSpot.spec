# Build from the BlindSpot directory with:
# python -m PyInstaller --noconfirm BlindSpot.spec

import subprocess
import sys
from pathlib import Path

import wx


# Build the translation catalogues the application loads at run time.
subprocess.run(
    [sys.executable, "scripts/i18n.py", "compile"],
    check=True,
)
translations = [
    (str(path), str(path.parent))
    for path in sorted(Path("locale").glob("*/LC_MESSAGES/*.mo"))
]
# wxWidgets' own catalogues translate stock buttons such as OK and Cancel.
wx_locale = Path(wx.__file__).resolve().parent / "locale"
for catalogue in sorted(Path("locale").glob("*/LC_MESSAGES/*.mo")):
    code = catalogue.parent.parent.name
    stock = wx_locale / code / "LC_MESSAGES" / "wxstd.mo"
    if stock.is_file():
        translations.append(
            (str(stock), str(Path("wx") / "locale" / code / "LC_MESSAGES"))
        )


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
        *translations,
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
