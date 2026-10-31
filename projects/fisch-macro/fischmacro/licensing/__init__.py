"""Licensing - prepared for paid, one-device activation; NOT active and NOT a protection yet.

Design (for when the product is sold):

* A purchase gives a licence key. On first start the app sends ``{key, device_id, app_version}`` to the
  activation server (``POST /v1/activate``). The server - not the app - enforces one device per key and
  returns a **signed token** ``{key_id, device_id, expires, features}`` (Ed25519 signature).
* The app keeps the token locally and verifies the signature with the public key built into the app, so it
  starts offline; it re-validates with the server now and then (``POST /v1/validate``) to pick up revoked
  or transferred licences.
* Moving to a new PC: ``POST /v1/deactivate`` from the old device (or from the customer's account page,
  with whatever limits you set) frees the slot.
* ``device_id`` is a salted hash of machine identifiers (never sent in the clear, never personal data).

The rest of the app asks only one thing - ``current().allows(feature)`` - in one place (starting
automation). A local check like this can always be patched out of a Python app; what makes sharing hard is
the server keeping one activation per key. There is deliberately no fake local "protection" here.
"""
from __future__ import annotations

import hashlib
import platform
import uuid
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class LicenseStatus:
    state: str = "development"      # development | unlicensed | active | expired | revoked | offline_grace
    holder: str = ""
    key_hint: str = ""              # last characters of the key, for display
    device_id: str = ""
    expires: str = ""
    features: set[str] = field(default_factory=lambda: {"automation"})
    message: str = "Development build - licensing is not switched on."

    def allows(self, feature: str) -> bool:
        return self.state in ("development", "active", "offline_grace") and feature in self.features


class LicenseProvider(Protocol):
    def status(self) -> LicenseStatus: ...
    def activate(self, key: str) -> LicenseStatus: ...
    def deactivate(self) -> LicenseStatus: ...


def device_id() -> str:
    """A stable, anonymous id for this PC (salted hash; the raw identifiers never leave the machine)."""
    raw = ""
    try:
        import winreg  # type: ignore[import-not-found]
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as k:
            raw = winreg.QueryValueEx(k, "MachineGuid")[0]
    except Exception:  # noqa: BLE001 - not Windows, or no access
        for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
            try:
                with open(path, encoding="utf-8") as f:
                    raw = f.read().strip()
                    break
            except OSError:
                continue
    raw = raw or f"{platform.node()}-{uuid.getnode()}"
    return hashlib.sha256(("fisch-macro/v1/" + raw).encode()).hexdigest()[:32]


class DevelopmentLicense:
    """Used until a real server exists: everything allowed, clearly labelled as a development build."""

    def status(self) -> LicenseStatus:
        return LicenseStatus(device_id=device_id())

    def activate(self, key: str) -> LicenseStatus:
        s = self.status()
        s.message = "Activation is not available in this build yet - keys will work once the licence server is live."
        return s

    def deactivate(self) -> LicenseStatus:
        return self.status()


class ServerLicense:  # pragma: no cover - the contract for later, not used yet
    """Talks to the activation API described above. Needs: the server URL, the Ed25519 public key, and a
    local token store. Left unimplemented on purpose until the server exists."""

    def __init__(self, base_url: str, public_key: bytes):
        self.base_url, self.public_key = base_url, public_key

    def status(self) -> LicenseStatus:
        raise NotImplementedError

    def activate(self, key: str) -> LicenseStatus:
        raise NotImplementedError

    def deactivate(self) -> LicenseStatus:
        raise NotImplementedError


_provider: LicenseProvider = DevelopmentLicense()


def provider() -> LicenseProvider:
    return _provider


def set_provider(p: LicenseProvider) -> None:
    global _provider
    _provider = p


def current() -> LicenseStatus:
    return _provider.status()
