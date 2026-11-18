import json

from craftd import paths
from craftd.instances import InstanceManager


def test_old_blockn_data_moves_to_craftd(tmp_path, monkeypatch):
    old = tmp_path / "Blockn"
    (old / "instances" / "survival").mkdir(parents=True)
    (old / "instances" / "survival" / "blockn-instance.json").write_text(json.dumps(
        {"id": "survival", "name": "Survival", "game_version": "26.2", "loader": "fabric"}))
    monkeypatch.delenv("CRAFTD_HOME", raising=False)
    monkeypatch.setattr(paths.sys, "platform", "darwin")
    monkeypatch.setattr(paths.Path, "home", lambda: tmp_path / "home")
    new = tmp_path / "Craftd"
    monkeypatch.setattr(paths, "APP_NAME", "Craftd")

    paths._migrate_from_blockn(new)
    assert not old.exists()
    assert [i.name for i in InstanceManager(new).list()] == ["Survival"]
