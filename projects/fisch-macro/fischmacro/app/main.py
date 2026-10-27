"""Application entry point."""
from __future__ import annotations

import argparse
import logging
import sys
import threading


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fischmacro", description="Fisch Macro desktop app")
    parser.add_argument("--simulation", action="store_true", help="start with the built-in simulated game")
    parser.add_argument("--smoke-test", type=float, default=0.0, metavar="SECONDS",
                        help="open the window, run for N seconds, then exit (used to verify builds)")
    parser.add_argument("--self-test", action="store_true",
                        help="check OCR and the vision engine without a window, print the result and exit")
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()

    from fischmacro.vision.win32 import enable_dpi_awareness
    enable_dpi_awareness()  # before any window or capture so coordinates are physical pixels

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from fischmacro import APP_NAME
    from fischmacro.app.context import AppContext
    from fischmacro.diagnostics.logs import setup_logging
    from fischmacro.profiles.manager import SettingsStore
    from fischmacro.ui.main_window import MainWindow, app_icon
    from fischmacro.ui.theme import apply_theme, stylesheet

    settings = SettingsStore().load()
    setup_logging(settings.logging.level, settings.logging.max_log_files)
    log = logging.getLogger("fischmacro")

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")

    ctx = AppContext()

    def style_app() -> None:
        a = ctx.settings.appearance
        apply_theme(a.theme, a.text_size, a.reduce_motion)
        app.setStyleSheet(stylesheet())

    style_app()
    app.setWindowIcon(app_icon())
    if args.simulation:
        ctx.use_simulation_for_this_run()

    def excepthook(exc_type, exc, tb):
        # Any unexpected error: release inputs first, then log.
        try:
            ctx.engine.inputs.release_all()
        finally:
            log.critical("Unhandled error", exc_info=(exc_type, exc, tb))

    sys.excepthook = excepthook
    threading.excepthook = lambda a: excepthook(a.exc_type, a.exc_value, a.exc_traceback)

    win = MainWindow(ctx)
    ctx.start_hotkeys()
    win.install_local_shortcuts()
    win.hotkeys.update_view()
    holder = {"win": win}

    def rebuild_window() -> None:
        """Theme or text size changed: rebuild the window; engine, hotkeys and session keep running."""
        old = holder["win"]
        page = old.stack.currentIndex()
        geometry = old.saveGeometry()
        maximized = old.isMaximized()
        old.detach()
        style_app()
        new = MainWindow(ctx)
        new.install_local_shortcuts()
        new.hotkeys.update_view()
        new.restoreGeometry(geometry)
        new.select_page(page)
        new.showMaximized() if maximized else new.show()
        old.close()
        old.deleteLater()
        holder["win"] = new
        new.toast("Appearance", f"Theme '{ctx.settings.appearance.theme}', text {ctx.settings.appearance.text_size.lower()}")

    # Deferred so the settings page that emitted the signal is not destroyed inside its own slot.
    ctx.appearance_changed.connect(lambda: QTimer.singleShot(0, rebuild_window))
    if ctx.settings.startup.start_minimized:
        win.showMinimized()
    else:
        win.show()
    if not ctx.settings.risk_acknowledged and not args.smoke_test:
        QTimer.singleShot(300, win.ensure_acknowledged)
    if ctx.settings.startup.start_preview_on_launch:
        ctx.engine.start_vision()  # vision only - automation never starts on launch
    log.info("%s started (capture mode: %s)", APP_NAME, ctx.settings.capture.mode)
    if args.smoke_test:
        QTimer.singleShot(int(args.smoke_test * 1000), lambda: holder["win"].close())
    return app.exec()


def self_test() -> int:
    """Headless checks for packaged builds: OCR reads text and the vision engine finds a reel."""
    import cv2
    import numpy as np

    from fischmacro.profiles.schema import Profile
    from fischmacro.simulation.game import SimulatedFischGame
    from fischmacro.vision.engine import VisionEngine
    from fischmacro.vision.frame import Frame
    from fischmacro.vision.ocr import OcrEngine, fuzzy_contains

    ok = True
    img = np.full((90, 640, 3), 30, np.uint8)
    cv2.putText(img, "Megalodon Hunt has started", (12, 58), cv2.FONT_HERSHEY_DUPLEX, 1.1, (255, 255, 255), 2)
    text = OcrEngine.shared().text(img)
    ocr_ok = fuzzy_contains(text, "Megalodon Hunt")
    print(f"OCR: {'ok' if ocr_ok else 'FAILED'} ({text!r}) {OcrEngine.shared().error}")
    ok &= ocr_ok
    g = SimulatedFischGame(seed=1)
    g._start_reel()
    g.step(0.1)
    obs = VisionEngine(Profile()).process(Frame(g.render(), (g.width, g.height)))
    print(f"Vision: {'ok' if obs.reel.present else 'FAILED'} (reel confidence {obs.reel.confidence:.2f})")
    ok &= obs.reel.present
    # any rod skin: a random skin with no calibration must still be read
    from fischmacro.simulation.game import random_skin
    g = SimulatedFischGame(seed=3)
    g.skin = random_skin(3)
    g._start_reel()
    g.step(0.1)
    obs = VisionEngine(Profile()).process(Frame(g.render(), (g.width, g.height)))
    print(f"Any skin: {'ok' if obs.reel.present else 'FAILED'} (bar found {obs.reel.bar_found})")
    ok &= obs.reel.present
    try:
        import anthropic  # noqa: F401 - the AI assistant's SDK must be bundled
        print("AI assistant SDK: ok")
    except ImportError as exc:
        print(f"AI assistant SDK: FAILED ({exc})")
        ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
