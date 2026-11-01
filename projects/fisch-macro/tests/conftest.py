import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("FISCHMACRO_NO_NETWORK", "1")  # no rod-picture downloads during tests
os.environ.setdefault("FISCHMACRO_UI", "classic")  # window tests drive the classic widgets; test_web_ui opts in
os.environ["FISCHMACRO_HOME"] = tempfile.mkdtemp(prefix="fischmacro-test-")

os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox --disable-gpu")
try:  # the new interface (QtWebEngine) needs this before any QApplication is created
    from PySide6.QtCore import QCoreApplication, Qt
    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
except ImportError:
    pass

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("FISCHMACRO_HOME", str(tmp_path))
    return tmp_path
