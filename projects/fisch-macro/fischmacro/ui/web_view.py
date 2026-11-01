"""The HTML/CSS interface inside the app window: a QWebEngineView plus a QWebChannel bridge to ``WebApi``.

The page (``fischmacro/web``) is loaded from local files only; it never navigates anywhere else. Every call
from the page goes through ``Bridge.call(method, json_args)`` and returns ``{"result": ...}`` or
``{"error": "..."}``; engine state is pushed to the page five times a second.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView

from fischmacro.paths import resource_path
from fischmacro.profiles.manager import ProfileError
from fischmacro.ui.web_api import ApiError, WebApi, json_safe

log = logging.getLogger(__name__)

WEB_DIR = resource_path("fischmacro", "web")
EXPECTED = (ApiError, ProfileError, ValueError, KeyError, TypeError)


class Bridge(QObject):
    stateChanged = Signal(str)
    notice = Signal(str, str)

    def __init__(self, api: WebApi, parent=None):
        super().__init__(parent)
        self.api = api

    @Slot(str, str, result=str)
    def call(self, method: str, args: str) -> str:
        return self.handle(method, args)

    def handle(self, method: str, args: str) -> str:
        try:
            parsed = json.loads(args) if args else {}
            if not isinstance(parsed, dict):
                raise ApiError("arguments must be an object")
            return json.dumps({"result": json_safe(self.api.call(method, parsed))})
        except EXPECTED as exc:
            msg = str(exc).strip("'\"") or exc.__class__.__name__
            return json.dumps({"error": msg})
        except Exception as exc:  # noqa: BLE001 - never let a page call crash the app
            log.exception("Interface call %s failed", method)
            return json.dumps({"error": f"Something went wrong ({exc.__class__.__name__}). Details are in the log."})

    def push_state(self) -> None:
        try:
            self.stateChanged.emit(json.dumps(json_safe(self.api.api_state())))
        except Exception:  # noqa: BLE001
            log.debug("state push failed", exc_info=True)


class LocalPage(QWebEnginePage):
    """Stays on the bundled files; links to the web open in the normal browser."""

    def acceptNavigationRequest(self, url: QUrl, nav_type, is_main_frame: bool) -> bool:  # noqa: N802
        if url.isLocalFile():
            try:
                return Path(url.toLocalFile()).resolve().is_relative_to(WEB_DIR.resolve())
            except (OSError, ValueError):
                return False
        if url.scheme() in ("http", "https"):
            QDesktopServices.openUrl(url)
        return False

    errors: list[str]

    def javaScriptConsoleMessage(self, level, message, line, source):  # noqa: N802
        if level == QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel:
            text = f"{message} ({source.rsplit('/', 1)[-1]}:{line})"
            self.errors = (getattr(self, "errors", []) + [text])[-50:]
            log.warning("interface: %s", text)


class WebInterface(QWebEngineView):
    def __init__(self, api: WebApi, parent=None):
        super().__init__(parent)
        self.api = api
        self.bridge = Bridge(api, self)
        self.loaded = False
        # An in-memory profile: the interface is the app's own local files, so nothing needs to be cached or
        # stored, and nothing is written to drive C (the default profile lives in %LOCALAPPDATA%).
        self.web_profile = memory_profile()
        page = LocalPage(self.web_profile, self)
        page.setBackgroundColor(QColor("#08090e"))  # no white flash while loading
        self.setPage(page)
        s = page.settings()
        s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        self.channel = QWebChannel(page)
        self.channel.registerObject("bridge", self.bridge)
        page.setWebChannel(self.channel)
        self.setContextMenuPolicy(Qt.NoContextMenu)
        self.loadFinished.connect(self._loaded)
        self.load(QUrl.fromLocalFile(str(WEB_DIR / "index.html")))
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._push)
        self.timer.start(200)

    def _loaded(self, ok: bool) -> None:
        self.loaded = ok
        if ok:
            log.info("New interface loaded")
        else:
            log.error("The interface page did not load from %s", WEB_DIR)

    def _push(self) -> None:
        if self.loaded and self.isVisible():
            self.bridge.push_state()

    def notify(self, title: str, text: str) -> None:
        self.bridge.notice.emit(title, text)


_PROFILE = None


def memory_profile() -> QWebEngineProfile:
    """One in-memory profile for the whole app, owned by the application so it outlives every page."""
    global _PROFILE
    if _PROFILE is None:
        from PySide6.QtWidgets import QApplication
        from fischmacro import paths
        folder = str(paths.data_dir() / "ui-engine")  # next to the app (drive D), never %APPDATA% on drive C
        for prof in (QWebEngineProfile.defaultProfile(),):  # anything that falls back to the default profile
            prof.setPersistentStoragePath(folder)
            prof.setCachePath(folder)
            prof.setHttpCacheType(QWebEngineProfile.HttpCacheType.MemoryHttpCache)
        _PROFILE = QWebEngineProfile(QApplication.instance())  # no storage name = off the record
        _PROFILE.setPersistentStoragePath(folder)
        _PROFILE.setCachePath(folder)
        _PROFILE.setHttpCacheType(QWebEngineProfile.HttpCacheType.MemoryHttpCache)
        _PROFILE.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies)
    return _PROFILE


def available() -> bool:
    return (WEB_DIR / "index.html").is_file()
