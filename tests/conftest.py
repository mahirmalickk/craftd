import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fake_modrinth import FakeModrinth, make_jar  # noqa: E402

from craftd.auth import MicrosoftAuth
from craftd.core import Craftd  # noqa: E402


@pytest.fixture(autouse=True)
def no_real_launchers(tmp_path_factory, monkeypatch):
    """Tests must never see (or create instances in) the Prism Launcher installed on this computer.

    Prism's folder is found through APPDATA (Windows) or the home folder, so both point at an empty temp
    folder during tests. A test that wants a launcher sets one up itself."""
    fake_home = tmp_path_factory.mktemp("fake-user-home")
    for var in ("APPDATA", "LOCALAPPDATA", "USERPROFILE", "HOME", "XDG_DATA_HOME"):
        monkeypatch.setenv(var, str(fake_home))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))


@pytest.fixture
def servers():
    """Fake Microsoft / Xbox Live / Minecraft sign-in servers: tests never touch the real ones."""
    from fake_auth import FakeAuthServers
    return FakeAuthServers()


@pytest.fixture
def fake():
    """A catalogue that mirrors the 26.2 -> 26.3 example."""
    f = FakeModrinth()
    f.v = {}
    f.v["api262"], _ = f.add_version("fabric-api", "Fabric API", "0.120+26.2", ["26.2"], ["fabric"])
    f.v["sodium262"], _ = f.add_version("sodium", "Sodium", "0.7.0+26.2", ["26.2"], ["fabric", "neoforge"])
    f.v["lithium262"], _ = f.add_version("lithium", "Lithium", "0.16+26.2", ["26.2"], ["fabric"])
    f.v["yacl262"], _ = f.add_version("yacl", "YetAnotherConfigLib", "3.7+26.2", ["26.2"], ["fabric"], deps=("fabric-api",))
    # 26.3 builds exist for everything except YACL
    f.v["api263"], _ = f.add_version("fabric-api", "Fabric API", "0.125+26.3", ["26.3"], ["fabric"])
    f.v["sodium263"], _ = f.add_version("sodium", "Sodium", "0.7.2+26.3", ["26.3"], ["fabric", "neoforge"])
    f.v["lithium263"], _ = f.add_version("lithium", "Lithium", "0.17+26.3", ["26.3"], ["fabric"])
    f.v["modmenu263"], _ = f.add_version("modmenu", "Mod Menu", "16.0+26.3", ["26.3"], ["fabric"], deps=("fabric-api",))
    return f


@pytest.fixture
def app(tmp_path, fake, servers):
    a = Craftd(home=tmp_path / "home", client=fake, auth=MicrosoftAuth(session=servers))
    a.refresh_game_versions()
    return a


@pytest.fixture
def setup_262(app, fake):
    """Instance 26.2 with Fabric API, Sodium, Lithium, YACL and one jar that isn't on Modrinth."""
    src = app.manager.create("Survival 26.2", "26.2", "fabric")
    for key in ("api262", "sodium262", "lithium262", "yacl262"):
        fake.place(fake.v[key], src.mods_dir)
    (src.mods_dir / "my-private-mod-1.0.jar").write_bytes(make_jar("privatemod", "My Private Mod", "1.0"))
    return src
