# Build from the BlindSpot directory with:
# python -m PyInstaller --noconfirm BlindSpot.spec

import sys


a = Analysis(
    ["src/blindspot_launcher.py"],
    pathex=["src"],
    binaries=[],
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
