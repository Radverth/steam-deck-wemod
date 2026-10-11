from __future__ import annotations

import json

from wemod_deck import paths, status


def test_paths_follow_home_and_xdg(isolated_home, tmp_path, monkeypatch):
    assert paths.config_file() == isolated_home / ".config/wemod-deck/config.toml"
    assert paths.data_dir() == isolated_home / ".local/share/wemod-deck"
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert paths.data_dir() == tmp_path / "xdg" / "wemod-deck"
    monkeypatch.setenv("XDG_DATA_HOME", "relative/ignored")
    assert paths.data_dir() == isolated_home / ".local/share/wemod-deck"


def test_write_and_read_status():
    status.write_status("10", "ok", "launched")
    status.write_status("20", "error", "boom")
    data = status.read_status()
    assert data["last"]["appid"] == "20"
    assert data["apps"]["10"]["state"] == "ok"
    assert data["apps"]["20"]["message"] == "boom"


def test_corrupt_status_file_is_replaced():
    p = paths.status_file()
    p.parent.mkdir(parents=True)
    p.write_text("{not json")
    status.write_status("1", "plain", "disabled")
    assert json.loads(p.read_text())["last"]["state"] == "plain"


def test_write_status_never_raises(monkeypatch, tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("")
    monkeypatch.setattr(paths, "status_file", lambda: blocker / "status.json")
    status.write_status("1", "ok", "x")  # parent is a file: must not raise


def test_logging_to_file(isolated_home):
    status.setup_logging("debug", stderr=False)
    status.log.debug("hello %s", "log")
    for h in status.log.handlers:
        h.flush()
    assert "hello log" in paths.log_file().read_text()


def test_logging_survives_unwritable_dir(monkeypatch, tmp_path, capsys):
    blocker = tmp_path / "file"
    blocker.write_text("")
    monkeypatch.setattr(paths, "log_file", lambda: blocker / "x.log")
    status.setup_logging("info", stderr=False)
    status.log.info("still logging")
    assert "still logging" in capsys.readouterr().err
