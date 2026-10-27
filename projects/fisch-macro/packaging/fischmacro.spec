# PyInstaller spec - build with:  pyinstaller packaging/fischmacro.spec --noconfirm
# Produces dist/FischMacro/FischMacro.exe (one-folder build: fast start, no temp extraction).
from pathlib import Path

ROOT = Path(SPECPATH).parent

a = Analysis(
    [str(ROOT / "run.py")],
    pathex=[str(ROOT)],
    datas=[(str(ROOT / "assets"), "assets")],
    hiddenimports=["pynput.keyboard._win32", "pynput.mouse._win32", "pynput.keyboard._xorg", "pynput.mouse._xorg"],
    excludes=["tkinter", "matplotlib", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
              "PySide6.Qt3DCore", "PySide6.QtQuick3D", "PySide6.QtMultimedia", "PySide6.QtPdf"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="FischMacro",
    console=False,
    icon=str(ROOT / "assets" / "app_icon.ico"),
    version=None,
    uac_admin=False,  # no administrator rights needed
)
coll = COLLECT(exe, a.binaries, a.datas, name="FischMacro")
