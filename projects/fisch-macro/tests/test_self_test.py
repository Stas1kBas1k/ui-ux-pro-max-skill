"""The packaged app's --self-test, run with the tests too (build 31 failed it only in the Windows build step)."""
import pytest


def test_self_test_passes(capsys):
    from fischmacro.vision.ocr import OcrEngine
    if not OcrEngine.shared().available:
        pytest.skip("OCR engine not installed")
    from fischmacro.app.main import self_test
    assert self_test() == 0, capsys.readouterr().out
