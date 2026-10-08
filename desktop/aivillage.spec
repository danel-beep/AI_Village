# PyInstaller recipe for "AI Village.app" (.github/workflows/desktop.yml: pyinstaller desktop/aivillage.spec).
# build_info.json ({"version": <run number>, ...}) is written by CI just before the build.
import os

here = SPECPATH
a = Analysis([os.path.join(here, "aivillage_app.py")],
             datas=[(os.path.join(here, "build_info.json"), ".")],
             hiddenimports=["webview.platforms.cocoa"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="AI Village", console=False)
coll = COLLECT(exe, a.binaries, a.datas, name="AI Village")
app = BUNDLE(coll, name="AI Village.app", icon=os.path.join(here, "icon.png"),
             bundle_identifier="com.danelbeep.aivillage",
             info_plist={"CFBundleDisplayName": "AI Village", "NSHighResolutionCapable": True,
                         "LSMinimumSystemVersion": "11.0",
                         "LSApplicationCategoryType": "public.app-category.simulation-games",
                         # the game is a local server at http://127.0.0.1:<port>
                         "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True}})
