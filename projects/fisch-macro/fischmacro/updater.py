"""In-app updates from the project's GitHub releases (public; nothing is signed in to, no account needed).

Every Windows build that passes CI is published as a release tagged ``fischmacro-b<build number>`` with two
files: the app zip and its SHA-256. The app compares its own build number with the newest release:

1. check: one request to the GitHub API (never more than once per start unless asked);
2. download: the zip goes to the data folder (next to the app, never drive C), its size and SHA-256 are
   checked, then it is unpacked to ``updates/staging``;
3. install: a small PowerShell script waits for the app to close, copies the new files over the app folder
   (the ``data`` folder is never touched or deleted), and starts the app again. Its log is
   ``updates/install.log``.

Only the packaged Windows app can update itself; from source, ``git pull`` does the job.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

from fischmacro import paths

log = logging.getLogger(__name__)

REPO = "Stas1kBas1k/ui-ux-pro-max-skill"
TAG_PREFIX = "fischmacro-b"
ASSET = "FischMacro-windows.zip"
API = f"https://api.github.com/repos/{REPO}/releases?per_page=20"
ALLOWED_HOSTS = ("api.github.com", "github.com", "objects.githubusercontent.com",
                 "release-assets.githubusercontent.com")
USER_AGENT = "FischMacro (desktop app; update check)"


def build_info() -> dict:
    """{"build": n, "commit": sha} written by CI into the package; build 0 when run from source."""
    try:
        return json.loads(paths.resource_path("fischmacro", "build_info.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"build": 0, "commit": ""}


def current_build() -> int:
    try:
        return int(build_info().get("build", 0))
    except (TypeError, ValueError):
        return 0


@dataclass
class Release:
    build: int
    tag: str
    notes: str
    url: str
    size: int
    sha_url: str


def parse_releases(data) -> Release | None:
    """The newest app release in a GitHub API answer, or None."""
    best = None
    for rel in data if isinstance(data, list) else []:
        tag = str(rel.get("tag_name", ""))
        m = re.fullmatch(re.escape(TAG_PREFIX) + r"(\d+)", tag)
        if not m or rel.get("draft"):
            continue
        assets = {a.get("name"): a for a in rel.get("assets", []) or []}
        z, h = assets.get(ASSET), assets.get(ASSET + ".sha256")
        if not z or not h:
            continue
        r = Release(int(m.group(1)), tag, str(rel.get("body") or "").strip(), z.get("browser_download_url", ""),
                    int(z.get("size", 0)), h.get("browser_download_url", ""))
        if best is None or r.build > best.build:
            best = r
    return best


def _allowed(url: str) -> bool:
    m = re.match(r"https://([^/]+)/", url)
    return bool(m and m.group(1) in ALLOWED_HOSTS)


def _open(url: str, timeout: float = 30.0):
    if not _allowed(url):
        raise ValueError(f"not an update address: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/octet-stream"
                                               if "/releases/download/" in url else "application/json"})
    return urllib.request.urlopen(req, timeout=timeout)  # noqa: S310 - https GitHub hosts only


def can_self_update() -> bool:
    return sys.platform == "win32" and bool(getattr(sys, "frozen", False))


class Updater:
    """States: idle, checking, latest, available, downloading, ready, installing, error, off."""

    def __init__(self) -> None:
        self.state = "idle"
        self.message = ""
        self.progress = 0.0
        self.release: Release | None = None
        self.build = current_build()
        self._lock = threading.Lock()
        self._busy = False

    def as_dict(self) -> dict:
        r = self.release
        return {"state": self.state, "message": self.message, "progress": round(self.progress, 3),
                "build": self.build, "new_build": r.build if r else None,
                "notes": (r.notes[:600] if r else ""), "size_mb": round(r.size / 1e6) if r else 0,
                "can_install": can_self_update()}

    def _run(self, fn) -> bool:
        with self._lock:
            if self._busy:
                return False
            self._busy = True

        def go():
            try:
                fn()
            except Exception as exc:  # noqa: BLE001 - shown to the player, never crashes the app
                log.warning("Update: %s", exc)
                self.state, self.message = "error", f"Update failed: {exc}"
            finally:
                self._busy = False
        threading.Thread(target=go, name="updater", daemon=True).start()
        return True

    # -- check
    def check(self, background: bool = True) -> None:
        if os.environ.get("FISCHMACRO_NO_NETWORK"):
            self.state, self.message = "off", "Update checks are off (no network)."
            return
        (self._run if background else (lambda f: f()))(self._check)

    def _check(self) -> None:
        self.state, self.message = "checking", "Looking for a newer build..."
        with _open(API, timeout=15) as r:
            data = json.loads(r.read(2_000_000).decode("utf-8"))
        rel = parse_releases(data)
        self.release = rel
        if rel is None or rel.build <= self.build:
            self.state = "latest"
            self.message = f"You have the newest build ({self.build})." if self.build else \
                "Running from source: no build number."
        else:
            self.state = "available"
            self.message = f"Build {rel.build} is available (you have {self.build or 'an older one'})."
        log.info("Update check: %s", self.message)

    # -- download
    def download(self) -> bool:
        if self.release is None or self.state not in ("available", "error"):
            return False
        return self._run(self._download)

    def folder(self) -> Path:
        d = paths.data_dir() / "updates"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _download(self) -> None:
        rel = self.release
        folder = self.folder()
        self.state, self.progress = "downloading", 0.0
        self.message = f"Downloading build {rel.build} ({rel.size / 1e6:.0f} MB)..."
        with _open(rel.sha_url, timeout=30) as r:
            want = r.read(1000).decode("ascii", "replace").split()[0].strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", want):
            raise ValueError("the release has no valid SHA-256")
        target = folder / f"FischMacro-b{rel.build}.zip"
        h, done = hashlib.sha256(), 0
        with _open(rel.url, timeout=60) as r, open(target, "wb") as out:
            while chunk := r.read(1 << 20):
                out.write(chunk)
                h.update(chunk)
                done += len(chunk)
                self.progress = done / rel.size if rel.size else 0.0
        if rel.size and done != rel.size:
            raise ValueError(f"download incomplete ({done} of {rel.size} bytes)")
        if h.hexdigest() != want:
            target.unlink(missing_ok=True)
            raise ValueError("the download is damaged (SHA-256 does not match) - try again")
        self.message = "Unpacking..."
        staging = folder / "staging"
        shutil.rmtree(staging, ignore_errors=True)
        unpack(target, staging)
        target.unlink(missing_ok=True)
        self.state, self.progress = "ready", 1.0
        self.message = f"Build {rel.build} is ready. Press Install: the app closes, updates and opens again."
        log.info("Update: build %s downloaded and checked", rel.build)

    # -- install
    def install(self) -> bool:
        """Start the installer script. The caller then quits the app."""
        if self.state != "ready" or not can_self_update():
            return False
        app_dir = Path(sys.executable).resolve().parent
        staging = self.folder() / "staging"
        src = app_root(staging)
        if src is None:
            self.state, self.message = "error", "The downloaded update has no FischMacro.exe."
            return False
        script = self.folder() / "install.ps1"
        script.write_text(install_script(os.getpid(), src, app_dir, staging, self.folder() / "install.log"),
                          encoding="utf-8")
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) \
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
                          "-File", str(script)], creationflags=flags, close_fds=True)
        self.state, self.message = "installing", "Installing - the app will open again in a few seconds."
        log.info("Update: installing build %s into %s", self.release.build if self.release else "?", app_dir)
        return True


def unpack(zip_path: Path, dest: Path) -> None:
    """Unzip, refusing any entry that would land outside ``dest`` or inside a ``data`` folder."""
    dest.mkdir(parents=True, exist_ok=True)
    root = dest.resolve()
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            target = (dest / info.filename).resolve()
            if not target.is_relative_to(root):
                raise ValueError(f"unsafe file in the update: {info.filename}")
            parts = [x.lower() for x in Path(info.filename).parts]
            if parts[:1] == ["data"] or parts[:2] == ["fischmacro", "data"]:
                continue  # the app folder's own data folder is the player's: never shipped over
            z.extract(info, dest)


def app_root(staging: Path) -> Path | None:
    """The folder in the unpacked update that holds FischMacro.exe (the zip root, or one folder down)."""
    if (staging / "FischMacro.exe").is_file():
        return staging
    for sub in staging.iterdir() if staging.is_dir() else []:
        if sub.is_dir() and (sub / "FischMacro.exe").is_file():
            return sub
    return None


def _ps(path: Path | str) -> str:
    return "'" + str(path).replace("'", "''") + "'"


def install_script(pid: int, src: Path, app_dir: Path, staging: Path, log_file: Path) -> str:
    """PowerShell: wait for the app to close, copy the new build over it (no deletions, so the data folder
    and anything else of the player's stays), clean up, start the app."""
    return f"""$ErrorActionPreference = 'Continue'
$log = {_ps(log_file)}
"$(Get-Date -Format s) waiting for the app (pid {pid}) to close" | Out-File -Append -Encoding utf8 $log
Wait-Process -Id {pid} -Timeout 60 -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 800
robocopy {_ps(src)} {_ps(app_dir)} /E /IS /IT /R:10 /W:1 /NP /NFL /NDL | Out-File -Append -Encoding utf8 $log
$rc = $LASTEXITCODE
"$(Get-Date -Format s) copy finished with code $rc (below 8 = success)" | Out-File -Append -Encoding utf8 $log
if ($rc -lt 8) {{ Remove-Item -Recurse -Force {_ps(staging)} -ErrorAction SilentlyContinue }}
Start-Process -FilePath {_ps(app_dir / "FischMacro.exe")} -WorkingDirectory {_ps(app_dir)}
"""


_UPDATER: Updater | None = None


def shared() -> Updater:
    global _UPDATER
    if _UPDATER is None:
        _UPDATER = Updater()
    return _UPDATER
