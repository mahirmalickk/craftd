"""Signing in to Minecraft with a Microsoft account (the same way Prism and the official launcher do).

1. Microsoft: Craftd shows a short code; you enter it at microsoft.com/link and sign in on Microsoft's own
   page (the "device code" flow), so Craftd never sees your password. Microsoft gives Craftd a token, plus
   a refresh token so you don't have to do this every time.
2. Xbox Live: that token is swapped for an Xbox Live token, then an XSTS token for Minecraft.
3. Minecraft: the XSTS token is swapped for a Minecraft token, which is what the game needs to launch.
   Then Craftd reads your Minecraft name, UUID and skin.

Craftd's Azure app ID was approved by Mojang (2026-11), which is what lets step 3 work. Sign-in uses the
"consumers" tenant with the XboxLive.signin scope (Minecraft accounts are personal Microsoft accounts).
Tokens are never written to craftd.log.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import requests

from .accounts import Account
from .log import log
from .modrinth import USER_AGENT, apply_proxy

CLIENT_ID = "896ef6d6-b5b3-4bae-b358-bca6d09ecc83"  # Craftd's Azure app (not a secret)
SCOPE = "XboxLive.signin offline_access"
MS_BASE = "https://login.microsoftonline.com/consumers/oauth2/v2.0"
XBL_AUTH = "https://user.auth.xboxlive.com/user/authenticate"
XSTS_AUTH = "https://xsts.auth.xboxlive.com/xsts/authorize"
MC_BASE = "https://api.minecraftservices.com"
REFRESH_MARGIN = 5 * 60  # refresh the Minecraft token when it has less than 5 minutes left

Progress = Callable[[str], None]

# What Xbox Live's error numbers mean, in words a player can act on
XBOX_ERRORS = {
    2148916227: "This account is banned from Xbox Live.",
    2148916229: "This account's parental controls don't allow playing online. An adult in its Microsoft "
                "Family group can change that at family.microsoft.com.",
    2148916233: "This Microsoft account doesn't have an Xbox profile yet. Sign in once at xbox.com to "
                "create one (it's free), then try again.",
    2148916234: "This account hasn't accepted the Xbox terms yet. Sign in once at xbox.com, accept them, "
                "then try again.",
    2148916235: "Xbox Live isn't available in this account's country or region.",
    2148916236: "This account needs adult verification (South Korea). Verify it on xbox.com, then try again.",
    2148916237: "This account needs adult verification (South Korea). Verify it on xbox.com, then try again.",
    2148916238: "This is a child account. An adult needs to add it to a Microsoft Family group at "
                "family.microsoft.com before it can sign in.",
}


class AuthError(Exception):
    """Signing in didn't work. The message says why, for the player."""

    expected = True  # a normal outcome (declined, child account...): logged as one line, not a crash

    def __init__(self, message: str, needs_sign_in: bool = False):
        super().__init__(message)
        self.needs_sign_in = needs_sign_in  # the saved sign-in is no good: sign in again


class SignInCancelled(AuthError):
    pass


@dataclass
class DeviceCode:
    user_code: str  # e.g. "ABCD-EFGH": what you type at microsoft.com/link
    device_code: str
    verification_uri: str
    expires_in: int
    interval: int
    message: str = ""


class MicrosoftAuth:
    def __init__(self, session: requests.Session | None = None, timeout: float = 20, client_id: str = CLIENT_ID):
        self.session = session or requests.Session()
        if hasattr(self.session, "headers"):
            self.session.headers.update({"User-Agent": USER_AGENT})
        self.timeout = timeout
        self.client_id = client_id

    def configure_network(self, proxy: str = "system", host: str = "", port: int = 8080, timeout: float = 20) -> None:
        self.timeout = timeout
        if isinstance(self.session, requests.Session):
            apply_proxy(self.session, proxy, host, port)

    # ---- plumbing ----------------------------------------------------------------------------------
    def _send(self, method: str, url: str, what: str, **kwargs):
        try:
            return self.session.request(method, url, timeout=self.timeout, **kwargs)
        except requests.RequestException as exc:
            raise AuthError(f"Couldn't reach {what}. Check your internet connection (and Settings → Network). "
                            f"({exc.__class__.__name__})") from exc

    @staticmethod
    def _json(resp) -> dict:
        try:
            data = resp.json()
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    # ---- 1. Microsoft ------------------------------------------------------------------------------
    def start_device_code(self) -> DeviceCode:
        resp = self._send("POST", f"{MS_BASE}/devicecode", "Microsoft",
                          data={"client_id": self.client_id, "scope": SCOPE})
        data = self._json(resp)
        if resp.status_code != 200 or "device_code" not in data:
            raise AuthError(f"Microsoft didn't start the sign-in: {data.get('error_description') or resp.status_code}")
        return DeviceCode(user_code=data["user_code"], device_code=data["device_code"],
                          verification_uri=data.get("verification_uri", "https://www.microsoft.com/link"),
                          expires_in=int(data.get("expires_in", 900)), interval=int(data.get("interval", 5)),
                          message=data.get("message", ""))

    def wait_for_sign_in(self, code: DeviceCode, cancelled: Callable[[], bool] = lambda: False,
                         sleep: Callable[[float], None] = time.sleep) -> dict:
        """Ask Microsoft every few seconds whether you've finished signing in on its page."""
        interval, waited = max(code.interval, 1), 0.0
        while waited < code.expires_in:
            for _ in range(int(interval * 4)):  # check for Cancel 4 times a second while waiting
                if cancelled():
                    raise SignInCancelled("Sign-in was cancelled.")
                sleep(0.25)
            waited += interval
            resp = self._send("POST", f"{MS_BASE}/token", "Microsoft", data={
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "client_id": self.client_id, "device_code": code.device_code})
            data = self._json(resp)
            if resp.status_code == 200 and data.get("access_token"):
                return data
            error = data.get("error", "")
            if error == "authorization_pending":
                continue
            if error == "slow_down":
                interval += 5
                continue
            if error == "authorization_declined":
                raise SignInCancelled("Sign-in was declined on Microsoft's page.")
            if error in ("expired_token", "code_expired"):
                break
            detail = data.get("error_description") or error or resp.status_code
            if "AADSTS7000218" in str(detail):  # the Azure app isn't set up for device-code sign-in
                detail = ("Craftd's Azure app needs \"Allow public client flows\" turned on "
                          "(Azure → App registrations → Craftd → Authentication).")
            raise AuthError(f"Microsoft sign-in failed: {detail}")
        raise AuthError("The code expired before sign-in finished. Click Add Account to get a new one.")

    def refresh_microsoft(self, refresh_token: str) -> dict:
        resp = self._send("POST", f"{MS_BASE}/token", "Microsoft", data={
            "grant_type": "refresh_token", "client_id": self.client_id, "refresh_token": refresh_token,
            "scope": SCOPE})
        data = self._json(resp)
        if resp.status_code == 200 and data.get("access_token"):
            return data
        if data.get("error") in ("invalid_grant", "interaction_required", "consent_required"):
            raise AuthError("This account's sign-in has expired. Sign in again.", needs_sign_in=True)
        raise AuthError(f"Microsoft couldn't refresh the sign-in: {data.get('error_description') or resp.status_code}")

    # ---- 2. Xbox Live ------------------------------------------------------------------------------
    def xbox_live(self, ms_access_token: str) -> tuple[str, str]:
        resp = self._send("POST", XBL_AUTH, "Xbox Live", json={
            "Properties": {"AuthMethod": "RPS", "SiteName": "user.auth.xboxlive.com",
                           "RpsTicket": f"d={ms_access_token}"},
            "RelyingParty": "http://auth.xboxlive.com", "TokenType": "JWT"},
            headers={"Accept": "application/json", "x-xbl-contract-version": "1"})
        data = self._json(resp)
        if resp.status_code != 200 or not data.get("Token"):
            raise AuthError(f"Xbox Live sign-in failed ({resp.status_code}).")
        return data["Token"], data["DisplayClaims"]["xui"][0]["uhs"]

    def xsts(self, xbl_token: str) -> tuple[str, str]:
        resp = self._send("POST", XSTS_AUTH, "Xbox Live", json={
            "Properties": {"SandboxId": "RETAIL", "UserTokens": [xbl_token]},
            "RelyingParty": "rp://api.minecraftservices.com/", "TokenType": "JWT"},
            headers={"Accept": "application/json", "x-xbl-contract-version": "1"})
        data = self._json(resp)
        if resp.status_code == 401:
            xerr = data.get("XErr")
            raise AuthError(XBOX_ERRORS.get(xerr, f"Xbox Live refused this account (error {xerr})."))
        if resp.status_code != 200 or not data.get("Token"):
            raise AuthError(f"Xbox Live sign-in failed ({resp.status_code}).")
        return data["Token"], data["DisplayClaims"]["xui"][0]["uhs"]

    # ---- 3. Minecraft ------------------------------------------------------------------------------
    def minecraft_token(self, uhs: str, xsts_token: str) -> tuple[str, int]:
        resp = self._send("POST", f"{MC_BASE}/authentication/login_with_xbox", "Minecraft",
                          json={"identityToken": f"XBL3.0 x={uhs};{xsts_token}"})
        data = self._json(resp)
        if resp.status_code == 403 and "app registration" in str(data).lower():
            raise AuthError("Minecraft hasn't approved this copy of Craftd for sign-in "
                            "(\"Invalid app registration\"). Make sure you have the latest Craftd.")
        if resp.status_code == 429:
            raise AuthError("Too many sign-in attempts. Wait a minute, then try again.")
        if resp.status_code != 200 or not data.get("access_token"):
            raise AuthError(f"Minecraft sign-in failed ({resp.status_code}).")
        return data["access_token"], int(data.get("expires_in", 86400))

    def _mc_get(self, path: str, token: str):
        return self._send("GET", f"{MC_BASE}{path}", "Minecraft", headers={"Authorization": f"Bearer {token}"})

    def owns_game(self, mc_token: str) -> bool:
        resp = self._mc_get("/entitlements/mcstore", mc_token)
        items = self._json(resp).get("items", []) if resp.status_code == 200 else []
        return any(i.get("name") in ("game_minecraft", "product_minecraft") for i in items)

    def profile(self, mc_token: str) -> dict:
        resp = self._mc_get("/minecraft/profile", mc_token)
        if resp.status_code == 404:
            if self.owns_game(mc_token):
                raise AuthError("This account owns Minecraft but hasn't picked a Minecraft name yet. Open the "
                                "official Minecraft Launcher once to choose one, then try again.")
            raise AuthError("This Microsoft account doesn't own Minecraft: Java Edition. (Using Xbox Game "
                            "Pass? Launch Java Edition once from the official launcher first.)")
        data = self._json(resp)
        if resp.status_code != 200 or not data.get("id"):
            raise AuthError(f"Couldn't read the Minecraft profile ({resp.status_code}).")
        return data

    # ---- all together ------------------------------------------------------------------------------
    def finish_sign_in(self, ms_tokens: dict, progress: Progress = lambda _m: None) -> Account:
        """Microsoft tokens → a signed-in Minecraft account (Xbox Live, XSTS, Minecraft, profile)."""
        progress("Signing in to Xbox Live…")
        xbl, _ = self.xbox_live(ms_tokens["access_token"])
        xsts_token, uhs = self.xsts(xbl)
        progress("Signing in to Minecraft…")
        mc_token, expires_in = self.minecraft_token(uhs, xsts_token)
        progress("Reading your Minecraft profile…")
        prof = self.profile(mc_token)
        skin = next((s for s in prof.get("skins", []) if s.get("state") == "ACTIVE"), None) or \
            (prof.get("skins") or [{}])[0]
        account = Account(uuid=prof["id"].replace("-", ""), name=prof.get("name", "?"),
                          refresh_token=ms_tokens.get("refresh_token", ""), mc_token=mc_token,
                          mc_expires=time.time() + expires_in, skin_url=skin.get("url", ""),
                          skin_variant=skin.get("variant", ""))
        log.info("Signed in as %s", account.name)
        return account

    def sign_in(self, code: DeviceCode, cancelled: Callable[[], bool] = lambda: False,
                progress: Progress = lambda _m: None, sleep: Callable[[float], None] = time.sleep) -> Account:
        progress(f"Waiting for you to sign in at {code.verification_uri.split('://')[-1]}…")
        tokens = self.wait_for_sign_in(code, cancelled, sleep)
        return self.finish_sign_in(tokens, progress)

    def refresh(self, account: Account, force: bool = False, progress: Progress = lambda _m: None) -> Account:
        """Make sure the account's Minecraft token works for a while; get new tokens if it's about to expire.
        Also picks up a new name or skin. Raises AuthError(needs_sign_in=True) if you must sign in again."""
        if not force and account.mc_token and account.mc_expires - time.time() > REFRESH_MARGIN:
            return account
        if not account.refresh_token:
            raise AuthError(f"{account.name} needs to sign in again.", needs_sign_in=True)
        progress(f"Refreshing {account.name}'s sign-in…")
        tokens = self.refresh_microsoft(account.refresh_token)
        fresh = self.finish_sign_in(tokens, progress)
        if fresh.uuid != account.uuid:
            raise AuthError("That sign-in belongs to a different Minecraft account.", needs_sign_in=True)
        if not fresh.refresh_token:  # Microsoft doesn't always send a new one: keep the old
            fresh.refresh_token = account.refresh_token
        return fresh

    def download_skin(self, url: str, dest: Path) -> Path | None:
        """The skin PNG, kept in the cache for the account list's face icons."""
        if not url:
            return None
        if dest.is_file():
            return dest
        try:
            resp = self.session.request("GET", url, timeout=self.timeout)
        except requests.RequestException:
            return None
        if resp.status_code != 200 or not resp.content.startswith(b"\x89PNG"):
            return None
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(resp.content)
        return dest
