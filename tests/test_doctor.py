from __future__ import annotations

import pytest

from fakes.installer import repo_zip, run_install, serve_everything
from wemod_deck import cli, doctor, status
from wemod_deck.config import Config


def levels(results):
    return {label: level for level, label, _ in results}


def test_nothing_installed(monkeypatch, capsys):
    monkeypatch.delenv("STEAM_COMPAT_CLIENT_INSTALL_PATH", raising=False)
    assert cli.main(["doctor"]) == 1
    out = capsys.readouterr().out
    assert "FAIL  Steam" in out
    assert "Problems found." in out


@pytest.fixture
def installed(fake_steam, http_server, tmp_path):
    remote = serve_everything(http_server, tmp_path)
    zipped = repo_zip(tmp_path / "repo.zip")
    r = run_install(fake_steam, ["--zip", str(zipped), "--no-proton"], remote.env)
    assert r.returncode == 0, r.stderr
    return fake_steam


def test_healthy_install(installed, capsys):
    lv = levels(doctor.checks(Config()))
    assert lv["Compat tool"] == "OK"
    assert lv["GE-Proton"] == "OK"
    assert lv["Steam Linux Runtime"] == "OK"
    assert lv["wand"] == "OK"
    assert lv["DWriteCore.dll"] == "OK"
    assert "Tool manifest" not in lv
    assert "Launcher" not in lv
    assert doctor.main(Config()) == 0
    assert "All good." in capsys.readouterr().out


def test_detects_problems(installed):
    s = installed
    tool = s.steam_root / "compatibilitytools.d/WeMod-GE"
    (tool / "toolmanifest.vdf").write_text(
        '"manifest"\n{\n  "require_tool_appid" "1628350"\n}\n'
    )
    s.entry_point.unlink()
    status.write_status("1", "error", "boom")
    lv = levels(doctor.checks(Config()))
    assert lv["Tool manifest"] == "FAIL"
    assert lv["Steam Linux Runtime"] == "WARN"
    assert lv["Last launch"] == "WARN"


def test_read_tool_conf(tmp_path):
    p = tmp_path / "tool.conf"
    p.write_text("# c\nGE_PROTON=/a\\ b/proton\nRUNTIME_APPID=''\nX\n")
    assert doctor.read_tool_conf(p) == {"GE_PROTON": "/a b/proton", "RUNTIME_APPID": ""}


def test_doctor_reports_backups_and_pending(installed):
    from wemod_deck import backup

    s = installed
    cd = s.game().compatdata
    (cd / "pfx/drive_c/users/steamuser").mkdir(parents=True)
    (cd / "pfx/drive_c/users/steamuser/save").write_text("x")
    b = backup.create(cd, s.game().appid, "manual")
    backup.set_pending(s.game().appid, b.archive, cd)
    lv = levels(doctor.checks(Config()))
    assert lv["Save backups"] == "OK"
    assert lv["Pending restore"] == "WARN"
    assert lv["Compression"] in ("OK", "WARN")
