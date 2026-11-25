"""Signed-in Minecraft accounts (Settings → Accounts), saved in accounts.json in Craftd's data folder.

What's saved per account: the Minecraft name, UUID and skin, plus the tokens Craftd needs to launch the
game without asking you to sign in every time. Passwords are never seen or saved: signing in happens on
Microsoft's own page.

The tokens are as good as a sign-in, so they're protected:
- On Windows they're encrypted with DPAPI, which ties them to your Windows user account: copying
  accounts.json to another computer or user gives nothing usable.
- Elsewhere the file is only readable by you (chmod 600).
If a token can't be read back (e.g. a copied file), that account just needs signing in again.
"""

from __future__ import annotations

import base64
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .log import log

ACCOUNTS_FILE = "accounts.json"
_ENTROPY = b"craftd-accounts-v1"


class TokenUnreadable(Exception):
    """A saved token can't be decrypted here (different user/computer, or damaged)."""


# ---- protecting tokens -----------------------------------------------------------------------------
def _dpapi(data: bytes, encrypt: bool) -> bytes:
    """Windows DPAPI (CryptProtectData / CryptUnprotectData) for the current user, no prompts."""
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def blob(raw: bytes):
        buf = ctypes.create_string_buffer(raw, len(raw))
        return Blob(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf

    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    crypt32.CryptProtectData.restype = wintypes.BOOL
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    inp, _keep_in = blob(data)
    entropy, _keep_ent = blob(_ENTROPY)
    out = Blob()
    fn = crypt32.CryptProtectData if encrypt else crypt32.CryptUnprotectData
    CRYPTPROTECT_UI_FORBIDDEN = 0x01
    if not fn(ctypes.byref(inp), None, ctypes.byref(entropy), None, None, CRYPTPROTECT_UI_FORBIDDEN,
              ctypes.byref(out)):
        raise OSError(ctypes.GetLastError(), "DPAPI failed")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(out.pbData, ctypes.c_void_p))


def protect(secret: str) -> str:
    if not secret:
        return ""
    if sys.platform.startswith("win"):
        try:
            return "dpapi:" + base64.b64encode(_dpapi(secret.encode(), True)).decode()
        except (OSError, AttributeError, ValueError):
            log.warning("Couldn't encrypt a token with Windows DPAPI; saving it unencrypted")
    return "plain:" + secret


def unprotect(stored: str) -> str:
    if not stored:
        return ""
    kind, _, value = stored.partition(":")
    if kind == "plain":
        return value
    if kind == "dpapi":
        if not sys.platform.startswith("win"):
            raise TokenUnreadable("This sign-in was saved on Windows")
        try:
            return _dpapi(base64.b64decode(value), False).decode()
        except (OSError, AttributeError, ValueError) as exc:
            raise TokenUnreadable("This sign-in was saved by another Windows user or computer") from exc
    raise TokenUnreadable("Unknown token format")


# ---- accounts --------------------------------------------------------------------------------------
@dataclass
class Account:
    uuid: str  # Minecraft UUID, without dashes
    name: str  # Minecraft name
    refresh_token: str = ""  # Microsoft refresh token: gets new tokens without signing in again
    mc_token: str = ""  # Minecraft access token, used to launch the game
    mc_expires: float = 0  # when mc_token stops working (Unix time)
    skin_url: str = ""
    skin_variant: str = ""  # "CLASSIC" (Steve) or "SLIM" (Alex)
    needs_sign_in: bool = False  # its tokens stopped working: sign in again
    extra: dict = field(default_factory=dict)

    @property
    def dashed_uuid(self) -> str:
        u = self.uuid.replace("-", "")
        return f"{u[:8]}-{u[8:12]}-{u[12:16]}-{u[16:20]}-{u[20:]}" if len(u) == 32 else self.uuid


class AccountStore:
    def __init__(self, home: Path):
        self.path = home / ACCOUNTS_FILE
        self.accounts: list[Account] = []
        self.active_uuid: str = ""
        self.load()

    # ---- file --------------------------------------------------------------------------------------
    def load(self) -> None:
        self.accounts, self.active_uuid = [], ""
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("Couldn't read %s (%s): starting with no accounts", self.path.name, exc)
            return
        for raw in data.get("accounts", []):
            if not isinstance(raw, dict) or not raw.get("uuid") or not raw.get("name"):
                continue
            acc = Account(uuid=str(raw["uuid"]), name=str(raw["name"]), skin_url=raw.get("skin_url", ""),
                          skin_variant=raw.get("skin_variant", ""), mc_expires=float(raw.get("mc_expires") or 0))
            try:
                acc.refresh_token = unprotect(raw.get("refresh_token", ""))
                acc.mc_token = unprotect(raw.get("mc_token", ""))
            except TokenUnreadable as exc:
                log.warning("Account %s needs signing in again: %s", acc.name, exc)
                acc.refresh_token = acc.mc_token = ""
                acc.needs_sign_in = True
            acc.needs_sign_in = acc.needs_sign_in or bool(raw.get("needs_sign_in")) or not acc.refresh_token
            self.accounts.append(acc)
        active = data.get("active", "")
        self.active_uuid = active if any(a.uuid == active for a in self.accounts) else ""
        if not self.active_uuid and self.accounts:
            self.active_uuid = self.accounts[0].uuid

    def save(self) -> None:
        data = {"format": 1, "active": self.active_uuid, "accounts": [
            {"uuid": a.uuid, "name": a.name, "skin_url": a.skin_url, "skin_variant": a.skin_variant,
             "mc_expires": a.mc_expires, "needs_sign_in": a.needs_sign_in,
             "refresh_token": protect(a.refresh_token), "mc_token": protect(a.mc_token)}
            for a in self.accounts]}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".craftd-tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        if not sys.platform.startswith("win"):
            os.chmod(tmp, 0o600)  # only you can read it
        tmp.replace(self.path)

    # ---- changes -----------------------------------------------------------------------------------
    def get(self, uuid: str) -> Account | None:
        return next((a for a in self.accounts if a.uuid == uuid), None)

    def active(self) -> Account | None:
        return self.get(self.active_uuid)

    def add(self, account: Account, make_active: bool = True) -> Account:
        """Add a signed-in account, or update it if it's already here (signing in again)."""
        existing = self.get(account.uuid)
        if existing:
            self.accounts[self.accounts.index(existing)] = account
        else:
            self.accounts.append(account)
        if make_active or not self.active_uuid:
            self.active_uuid = account.uuid
        self.save()
        return account

    def remove(self, uuid: str) -> None:
        self.accounts = [a for a in self.accounts if a.uuid != uuid]
        if self.active_uuid == uuid:
            self.active_uuid = self.accounts[0].uuid if self.accounts else ""
        self.save()

    def set_active(self, uuid: str) -> None:
        if self.get(uuid):
            self.active_uuid = uuid
            self.save()

    def __iter__(self):
        return iter(self.accounts)

    def __len__(self) -> int:
        return len(self.accounts)
