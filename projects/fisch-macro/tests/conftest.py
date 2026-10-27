import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["FISCHMACRO_HOME"] = tempfile.mkdtemp(prefix="fischmacro-test-")

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("FISCHMACRO_HOME", str(tmp_path))
    return tmp_path
