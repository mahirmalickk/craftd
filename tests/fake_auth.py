"""A stand-in for Microsoft, Xbox Live and Minecraft's sign-in servers, so sign-in can be tested offline.

It follows the real request/response shapes. Knobs on the instance make it fail the ways the real servers
do (still waiting for the code, declined, child account, app not approved, doesn't own the game...).
"""

from __future__ import annotations

import struct
import zlib


def tiny_png(color=(200, 120, 60)) -> bytes:
    """A real 64x64 PNG, like a Minecraft skin."""
    w = h = 64
    raw = b"".join(b"\x00" + bytes(color + (255,)) * w for _ in range(h))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


class FakeResponse:
    def __init__(self, status: int, data=None, content: bytes | None = None):
        self.status_code = status
        self._data = data
        self.content = content if content is not None else b""
        self.text = str(data)

    def json(self):
        if self._data is None:
            raise ValueError("no json")
        return self._data


class FakeAuthServers:
    """session-like: .request(method, url, **kwargs) and .headers."""

    def __init__(self):
        self.headers = {}
        self.calls: list[str] = []
        self.pending_polls = 2  # "authorization_pending" this many times before the code is entered
        self.poll_error = None  # e.g. "authorization_declined", "expired_token"
        self.xerr = None  # an Xbox error number for XSTS
        self.app_approved = True
        self.owns_game = True
        self.has_profile = True
        self.refresh_ok = True
        self.name, self.uuid = "Arkooo", "0f1e2d3c4b5a69788796a5b4c3d2e1f0"
        self.skin_url = "http://textures.minecraft.net/texture/abc123"
        self.issued = 0  # how many Minecraft tokens were handed out
        self.seen_tokens: list[str] = []

    def request(self, method, url, timeout=None, data=None, json=None, headers=None, **_kw):
        path = url.split("://", 1)[1]
        self.calls.append(path.split("?")[0])
        if path.endswith("/oauth2/v2.0/devicecode"):
            assert data["scope"] == "XboxLive.signin offline_access" and "/consumers/" in url
            return FakeResponse(200, {"user_code": "ABCD-EFGH", "device_code": "dev-123",
                                      "verification_uri": "https://www.microsoft.com/link", "expires_in": 900,
                                      "interval": 1, "message": "To sign in, use a web browser..."})
        if path.endswith("/oauth2/v2.0/token"):
            if data["grant_type"] == "refresh_token":
                if not self.refresh_ok:
                    return FakeResponse(400, {"error": "invalid_grant", "error_description": "expired"})
                return FakeResponse(200, {"access_token": "ms-access-2", "refresh_token": "ms-refresh-2"})
            if self.poll_error:
                return FakeResponse(400, {"error": self.poll_error})
            if self.pending_polls > 0:
                self.pending_polls -= 1
                return FakeResponse(400, {"error": "authorization_pending"})
            return FakeResponse(200, {"access_token": "ms-access-1", "refresh_token": "ms-refresh-1"})
        if path == "user.auth.xboxlive.com/user/authenticate":
            assert json["Properties"]["RpsTicket"].startswith("d=ms-access")
            return FakeResponse(200, {"Token": "xbl-token", "DisplayClaims": {"xui": [{"uhs": "uhs-1"}]}})
        if path == "xsts.auth.xboxlive.com/xsts/authorize":
            assert json["RelyingParty"] == "rp://api.minecraftservices.com/"
            if self.xerr:
                return FakeResponse(401, {"XErr": self.xerr, "Message": ""})
            return FakeResponse(200, {"Token": "xsts-token", "DisplayClaims": {"xui": [{"uhs": "uhs-1"}]}})
        if path == "api.minecraftservices.com/authentication/login_with_xbox":
            assert json["identityToken"] == "XBL3.0 x=uhs-1;xsts-token"
            if not self.app_approved:
                return FakeResponse(403, {"path": "/authentication/login_with_xbox",
                                          "errorMessage": "Invalid app registration, see https://aka.ms/AppRegInfo"})
            self.issued += 1
            return FakeResponse(200, {"access_token": f"mc-token-{self.issued}", "expires_in": 86400})
        if path.startswith("api.minecraftservices.com/"):
            self.seen_tokens.append(headers["Authorization"])
        if path == "api.minecraftservices.com/entitlements/mcstore":
            items = [{"name": "product_minecraft"}, {"name": "game_minecraft"}] if self.owns_game else []
            return FakeResponse(200, {"items": items})
        if path == "api.minecraftservices.com/minecraft/profile":
            if not (self.owns_game and self.has_profile):
                return FakeResponse(404, {"error": "NOT_FOUND"})
            return FakeResponse(200, {"id": self.uuid, "name": self.name, "skins": [
                {"id": "s1", "state": "ACTIVE", "url": self.skin_url, "variant": "CLASSIC"}], "capes": []})
        if path.startswith("textures.minecraft.net/"):
            return FakeResponse(200, content=tiny_png())
        raise AssertionError(f"unexpected request: {method} {url}")


