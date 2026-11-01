# PyInstaller spec - build with:  pyinstaller packaging/fischmacro.spec --noconfirm
# Produces dist/FischMacro/FischMacro.exe (one-folder build: fast start, no temp extraction).
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent
ocr_data = collect_data_files("rapidocr_onnxruntime")  # OCR models + config
build_info = ROOT / "fischmacro" / "build_info.json"  # written by CI: the build number the updater compares
extra = [(str(build_info), "fischmacro")] if build_info.exists() else []

a = Analysis(
    [str(ROOT / "run.py")],
    pathex=[str(ROOT)],
    datas=[(str(ROOT / "assets"), "assets"),
           (str(ROOT / "fischmacro" / "web"), "fischmacro/web")] + ocr_data + extra,  # the new interface (HTML/CSS/JS)
    hiddenimports=["pynput.keyboard._win32", "pynput.mouse._win32", "pynput.keyboard._xorg", "pynput.mouse._xorg",
                   "onnxruntime", "anthropic", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineCore",
                   "PySide6.QtWebChannel"] + collect_submodules("rapidocr_onnxruntime"),  # imported dynamically
    excludes=["tkinter", "matplotlib", "PySide6.Qt3DCore", "PySide6.QtQuick3D", "PySide6.QtMultimedia", "PySide6.QtPdf"],
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
