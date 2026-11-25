"""v2 step 1: signing in with a Microsoft account, and saving accounts."""

import json
import time

import pytest

from craftd.accounts import Account, AccountStore, protect, unprotect, TokenUnreadable
from craftd.auth import AuthError, SignInCancelled

no_wait = lambda _s: None  # noqa: E731  (don't really sleep between polls)


def test_full_sign_in(app, servers):
    code = app.auth.start_device_code()
    assert code.user_code == "ABCD-EFGH" and code.verification_uri == "https://www.microsoft.com/link"
    steps = []
    acc = app.auth.sign_in(code, progress=steps.append, sleep=no_wait)
    assert (acc.name, acc.uuid) == ("Arkooo", servers.uuid)
    assert acc.dashed_uuid == "0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0"
    assert acc.refresh_token == "ms-refresh-1" and acc.mc_token == "mc-token-1"
    assert acc.mc_expires > time.time() + 80000 and acc.skin_variant == "CLASSIC"
    assert steps[0].startswith("Waiting for you to sign in") and "Signing in to Minecraft…" in steps
    # the real order: Microsoft (polled until the code is entered) → Xbox → XSTS → Minecraft → profile
    assert servers.calls[-4:] == ["user.auth.xboxlive.com/user/authenticate", "xsts.auth.xboxlive.com/xsts/authorize",
                                  "api.minecraftservices.com/authentication/login_with_xbox",
                                  "api.minecraftservices.com/minecraft/profile"]
    assert servers.calls.count("login.microsoftonline.com/consumers/oauth2/v2.0/token") == 3  # 2 pending + done


@pytest.mark.parametrize("knob,value,words", [
    ("poll_error", "authorization_declined", "declined"),
    ("poll_error", "expired_token", "code expired"),
    ("xerr", 2148916233, "doesn't have an Xbox profile"),
    ("xerr", 2148916238, "child account"),
    ("xerr", 2148916235, "country"),
    ("app_approved", False, "Invalid app registration"),
    ("owns_game", False, "doesn't own Minecraft: Java Edition"),
    ("has_profile", False, "hasn't picked a Minecraft name"),
])
def test_sign_in_problems_are_explained(app, servers, knob, value, words):
    setattr(servers, knob, value)
    with pytest.raises(AuthError, match=words):
        app.auth.sign_in(app.auth.start_device_code(), sleep=no_wait)


def test_cancel_stops_waiting(app, servers):
    servers.pending_polls = 10_000
    checks = []

    def cancelled():
        checks.append(1)
        return len(checks) > 6

    with pytest.raises(SignInCancelled):
        app.auth.sign_in(app.auth.start_device_code(), cancelled=cancelled, sleep=no_wait)
    assert len(checks) == 7  # stopped as soon as Cancel was clicked


def test_refresh(app, servers):
    acc = app.auth.sign_in(app.auth.start_device_code(), sleep=no_wait)
    assert app.auth.refresh(acc) is acc  # still fresh: nothing to do
    acc.mc_expires = time.time() + 60  # about to expire
    fresh = app.auth.refresh(acc)
    assert fresh.mc_token == "mc-token-2" and fresh.refresh_token == "ms-refresh-2"
    servers.refresh_ok = False
    with pytest.raises(AuthError) as err:
        app.auth.refresh(fresh, force=True)
    assert err.value.needs_sign_in


def test_store_saves_and_protects(app, servers, tmp_path):
    store = app.accounts
    acc = store.add(app.auth.sign_in(app.auth.start_device_code(), sleep=no_wait))
    second = store.add(Account(uuid="ab" * 16, name="Alt", refresh_token="r2", mc_token="m2"), make_active=False)
    assert store.active().name == "Arkooo" and len(store) == 2

    raw = (app.home / "accounts.json").read_text()
    assert "ms-refresh-1" not in raw or '"plain:' in raw  # encrypted on Windows; marked plain elsewhere
    assert json.loads(raw)["active"] == acc.uuid

    again = AccountStore(app.home)  # restart Craftd
    assert [a.name for a in again] == ["Arkooo", "Alt"] and again.active().refresh_token == "ms-refresh-1"
    again.set_active(second.uuid)
    again.remove(acc.uuid)
    assert AccountStore(app.home).active().name == "Alt"

    # signing in again as the same person updates the account instead of adding a duplicate
    again.add(Account(uuid=second.uuid, name="Alt2", refresh_token="r3"))
    assert [a.name for a in AccountStore(app.home)] == ["Alt2"]


def test_unreadable_tokens_mean_sign_in_again(tmp_path):
    assert unprotect(protect("secret")) == "secret" and unprotect("") == ""
    with pytest.raises(TokenUnreadable):
        unprotect("dpapi:AAAA") if not __import__("sys").platform.startswith("win") else unprotect("dpapi:@@@")
    (tmp_path / "accounts.json").write_text(json.dumps({"active": "u1", "accounts": [
        {"uuid": "u1", "name": "Copied", "refresh_token": "dpapi:AAAA", "mc_token": ""},
        {"uuid": "", "name": "broken"}, "junk"]}))
    store = AccountStore(tmp_path)
    [acc] = store.accounts
    assert acc.name == "Copied" and acc.needs_sign_in and store.active() is acc
    (tmp_path / "accounts.json").write_text("{not json")
    assert len(AccountStore(tmp_path)) == 0  # a damaged file doesn't crash Craftd


def test_skin_download(app, servers):
    acc = app.auth.sign_in(app.auth.start_device_code(), sleep=no_wait)
    path = app.auth.download_skin(acc.skin_url, app.skin_file(acc))
    assert path and path.read_bytes().startswith(b"\x89PNG")
    assert app.auth.download_skin("", app.skin_file(acc)) is None


def test_tokens_never_logged(app, servers):
    from craftd import log
    path = log.setup(app.home)
    app.auth.sign_in(app.auth.start_device_code(), sleep=no_wait)
    for h in log.log.handlers:
        h.flush()
    text = path.read_text()
    assert "Signed in as Arkooo" in text
    assert not any(t in text for t in ("ms-access", "ms-refresh", "mc-token", "xsts-token", "xbl-token"))
