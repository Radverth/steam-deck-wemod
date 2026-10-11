from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time

import pytest

from wemod_deck import backup, paths
from wemod_deck.backup import BackupError, NotEnoughSpace

U = backup.STEAMUSER
SAVE = os.urandom(300_000)


@pytest.fixture
def cd(fake_steam, tmp_path):
    """A played game's prefix with all kinds of save data."""
    c = fake_steam.game().compatdata
    files = {
        f"{U}/Saved Games/Game/slot1.sav": SAVE,
        f"{U}/Documents/My Games/Spïel/セーブ.dat": b"unicode save",
        f"{U}/AppData/LocalLow/Studio/Game/prefs.json": b"{}",
        f"{U}/Temp/junk.tmp": b"temp",
        f"{U}/AppData/Local/Temp/x.tmp": b"temp",
        "pfx/drive_c/ProgramData/Game/progress.dat": b"progress",
        "pfx/drive_c/windows/system32/x.dll": b"not a save",
        "pfx/user.reg": b"WINE REGISTRY Version 2\n\n[Software\\\\Studio\\\\Game] 1\n"
        b'"slot"=dword:00000001\n',
    }
    for rel, data in files.items():
        (c / rel).parent.mkdir(parents=True, exist_ok=True)
        (c / rel).write_bytes(data)
    (c / f"{U}/Empty Folder").mkdir()
    (c / f"{U}/Documents/to-saves").symlink_to("../Saved Games")
    central = tmp_path / "central"
    central.mkdir()
    (c / f"{U}/AppData/Roaming").mkdir(parents=True)
    (c / f"{U}/AppData/Roaming/Wand").symlink_to(central)
    return c


def state(c):
    """Everything in the backed-up areas, as comparable values."""
    out = {}
    for root in backup.ROOTS:
        top = c / root
        items = [top] + (
            list(top.rglob("*")) if top.is_dir() and not top.is_symlink() else []
        )
        for p in items:
            if not (p.exists() or p.is_symlink()):
                continue
            rel = p.relative_to(c).as_posix()
            if p.is_symlink():
                out[rel] = ("link", os.readlink(p))
            elif p.is_dir():
                out[rel] = ("dir",)
            else:
                out[rel] = ("file", p.read_bytes())
    return out


def expected_state(c):
    s = state(c)
    return {
        k: v
        for k, v in s.items()
        if not any(k == e or k.startswith(e + "/") for e in backup.EXCLUDE)
        and k not in backup.EXCLUDE_LINKS
    }


def test_collect_excludes_temp_and_login_links(cd):
    names = {e["path"] for e in backup.collect(cd)}
    assert f"{U}/Saved Games/Game/slot1.sav" in names
    assert "pfx/drive_c/ProgramData/Game/progress.dat" in names
    assert "pfx/user.reg" in names
    assert f"{U}/Documents/to-saves" in names
    assert not any("Temp" in n.split("/") for n in names)
    assert f"{U}/AppData/Roaming/Wand" not in names
    assert not any(n.startswith("pfx/drive_c/windows") for n in names)


BACKENDS = ["zstd", "zstd-cli", "gzip"]


@pytest.mark.parametrize("method", BACKENDS)
def test_roundtrip_each_backend(cd, monkeypatch, method):
    if method == "zstd" and backup._zstd is None:
        pytest.skip("no compression.zstd on this Python")
    if method == "zstd-cli" and not shutil.which("zstd"):
        pytest.skip("no zstd command")
    monkeypatch.setattr(backup, "compression", lambda: method)
    if method == "zstd-cli":
        monkeypatch.setattr(backup, "_zstd", None)  # read back via the CLI too
    before = expected_state(cd)
    b = backup.create(cd, "1234560", "manual")
    assert b.archive.suffixes[-1] == (".gz" if method == "gzip" else ".zst")
    assert b.manifest["compression"] == method
    shutil.rmtree(cd)
    cd.mkdir()
    backup.restore(b.archive, cd, mode="full")
    assert expected_state(cd) == before


def test_missing_mode_never_overwrites(cd):
    b = backup.create(cd, "1", "manual")
    slot = cd / f"{U}/Saved Games/Game/slot1.sav"
    slot.write_bytes(b"newer progress")
    (cd / "pfx/drive_c/ProgramData/Game/progress.dat").unlink()
    counts = backup.restore(b.archive, cd, mode="missing")
    assert slot.read_bytes() == b"newer progress"
    assert (
        cd / "pfx/drive_c/ProgramData/Game/progress.dat"
    ).read_bytes() == b"progress"
    assert counts["restored"] >= 1


def test_full_mode_overwrites_changed_files_only(cd):
    b = backup.create(cd, "1", "manual")
    slot = cd / f"{U}/Saved Games/Game/slot1.sav"
    slot.write_bytes(b"broken")
    extra = cd / f"{U}/Saved Games/Game/slot2.sav"
    extra.write_bytes(b"not in backup")
    counts = backup.restore(b.archive, cd, mode="full")
    assert slot.read_bytes() == SAVE
    assert extra.read_bytes() == b"not in backup"  # never deleted
    assert counts["unchanged"] > 0


def test_registry_is_merged(cd):
    b = backup.create(cd, "1", "manual")
    reg = cd / "pfx/user.reg"
    reg.write_text('WINE REGISTRY Version 2\n\n[Software\\\\Wine] 2\n"x"="y"\n')
    backup.restore(b.archive, cd, mode="missing")
    text = reg.read_text()
    assert '"x"="y"' in text and '"slot"=dword:00000001' in text


def test_dry_run_changes_nothing(cd):
    b = backup.create(cd, "1", "manual")
    shutil.rmtree(cd / U)
    before = state(cd)
    counts = backup.restore(b.archive, cd, mode="full", dry_run=True)
    assert counts["restored"] > 0
    assert state(cd) == before


def test_corrupt_archive_aborts_and_leaves_nothing(cd, monkeypatch):
    real_verify = backup.verify

    def truncate_then_verify(part, manifest):
        data = part.read_bytes()
        part.write_bytes(data[: len(data) // 2])
        real_verify(part, manifest)

    monkeypatch.setattr(backup, "verify", truncate_then_verify)
    with pytest.raises(BackupError):
        backup.create(cd, "1", "manual")
    assert list(backup.backups_dir("1").iterdir()) == []


def test_verify_detects_changed_content(cd):
    b = backup.create(cd, "1", "manual")
    for e in b.manifest["entries"]:
        if e["type"] == "file":
            e["sha256"] = "0" * 64
            break
    with pytest.raises(BackupError, match="does not match"):
        backup.verify(b.archive, b.manifest)


def test_not_enough_space(cd, monkeypatch):
    monkeypatch.setattr(backup, "SPACE_MARGIN", 1 << 62)
    with pytest.raises(NotEnoughSpace):
        backup.create(cd, "1", "manual")
    assert list(backup.backups_dir("1").iterdir()) == []


@pytest.mark.skipif(os.geteuid() == 0, reason="root can read everything")
def test_unreadable_folder_aborts(cd):
    locked = cd / f"{U}/Saved Games/Locked"
    locked.mkdir()
    locked.chmod(0)
    try:
        with pytest.raises(BackupError, match="cannot read"):
            backup.create(cd, "1", "manual")
    finally:
        locked.chmod(0o755)


def test_retention_keeps_newest_and_pending_target(cd):
    t0 = time.time()
    made = [backup.create(cd, "1", "manual", keep=5, now=t0 + i) for i in range(3)]
    backup.set_pending("1", made[0].archive, cd)
    for i in range(3, 7):
        backup.create(cd, "1", "manual", keep=5, now=t0 + i)
    names = [b.name for b in backup.list_backups("1")]
    assert len(names) == 6  # 5 newest + the pending restore's target
    assert made[0].name in names
    assert made[1].name not in names
    backup.clear_pending("1")
    backup.prune("1", 5)
    assert len(backup.list_backups("1")) == 5


def test_same_second_names_and_order(cd):
    t = time.time()
    a = backup.create(cd, "1", "manual", now=t)
    b = backup.create(cd, "1", "manual", now=t + 0.5)
    assert a.name != b.name
    assert backup.list_backups("1")[0].name == b.name
    assert backup.find("1").name == b.name
    assert backup.find("1", a.name).name == a.name
    with pytest.raises(BackupError):
        backup.find("1", "1999")


def test_restore_refuses_hostile_members(cd, tmp_path):
    folder = backup.backups_dir("9")
    folder.mkdir(parents=True)
    archive = folder / "20260101-000000-manual.tar.gz"
    escape = cd / f"{U}/escape"
    escape.parent.mkdir(parents=True, exist_ok=True)
    escape.symlink_to(tmp_path)
    names = ["../evil", "/abs/evil", "pfx/drive_c/windows/evil.dll", f"{U}/escape/evil"]
    with tarfile.open(archive, "w:gz") as t:
        for n in names:
            info = tarfile.TarInfo(n)
            info.size = 4
            t.addfile(info, io.BytesIO(b"evil"))
    archive.with_name("20260101-000000-manual.json").write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "path": n,
                        "type": "file",
                        "size": 4,
                        "sha256": hashlib.sha256(b"evil").hexdigest(),
                    }
                    for n in names
                ]
            }
        )
    )
    counts = backup.restore(archive, cd, mode="full")
    assert counts["refused"] == 4
    assert not (tmp_path / "evil").exists()
    assert not (cd / "pfx/drive_c/windows/evil.dll").exists()


def test_protected_restores_what_the_operation_lost(cd):
    slot = cd / f"{U}/Saved Games/Game/slot1.sav"
    with backup.protected(cd, "1", "unpack"):
        slot.unlink()
    assert slot.read_bytes() == SAVE

    with pytest.raises(RuntimeError), backup.protected(cd, "1", "unpack"):
        slot.unlink()
        raise RuntimeError("operation failed half way")
    assert slot.read_bytes() == SAVE


def test_protected_does_not_run_operation_without_backup(cd, monkeypatch):
    monkeypatch.setattr(backup, "SPACE_MARGIN", 1 << 62)
    ran = []
    with pytest.raises(NotEnoughSpace), backup.protected(cd, "1", "unpack"):
        ran.append(True)
    assert ran == []


def test_prefix_in_use(cd):
    env = {**os.environ, "STEAM_COMPAT_DATA_PATH": str(cd)}
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"], env=env
    )
    try:
        for _ in range(50):
            if proc.pid in backup.prefix_in_use(cd):
                break
            time.sleep(0.05)
        assert proc.pid in backup.prefix_in_use(cd)
    finally:
        proc.kill()
        proc.wait()
    assert proc.pid not in backup.prefix_in_use(cd)


def test_pending_marker(cd):
    assert backup.pending("1") is None and backup.pending(None) is None
    backup.set_pending("1", cd / "a.tar.zst", cd)
    assert backup.pending("1")["compatdata"] == str(cd)
    assert backup.all_pending() == ["1"]
    backup.clear_pending("1")
    assert backup.all_pending() == []
    assert paths.data_dir().is_dir()


def test_restoring_the_oldest_backup_is_not_pruned_by_pre_restore(cd):
    t0 = time.time()
    made = [backup.create(cd, "1", "manual", keep=2, now=t0 + i) for i in range(2)]
    oldest = made[0]
    backup.create(cd, "1", "pre-restore", keep=2, now=t0 + 5, protect=(oldest.archive,))
    assert oldest.archive.exists()


@pytest.mark.parametrize("rel", ["pfx/user.reg", f"{U}/Saved Games/Game/slot1.sav"])
def test_restore_temp_symlink_cannot_overwrite_external_file(cd, tmp_path, rel):
    b = backup.create(cd, "1", "manual")
    target = cd / rel
    target.write_bytes(b"changed")
    external = tmp_path / "outside-save"
    external.write_bytes(b"must survive")
    target.with_name(target.name + ".wemod-deck-restore").symlink_to(external)
    backup.restore(b.archive, cd, mode="full")
    assert external.read_bytes() == b"must survive"
    assert not target.is_symlink()


@pytest.mark.parametrize("damage", ["registry", "missing"])
def test_restore_verifies_all_entries_before_writing(cd, damage, monkeypatch):
    monkeypatch.setattr(backup, "compression", lambda: "gzip")
    b = backup.create(cd, "1", "manual")
    members = []
    with tarfile.open(b.archive, "r:*") as tar:
        for m in tar:
            data = tar.extractfile(m).read() if m.isfile() else None
            if m.name == "pfx/user.reg":
                if damage == "missing":
                    continue
                data = b"x" * m.size
            members.append((m, data))
    with tarfile.open(b.archive, "w:gz") as tar:
        for m, data in members:
            tar.addfile(m, io.BytesIO(data) if data is not None else None)
    slot = cd / f"{U}/Saved Games/Game/slot1.sav"
    slot.write_bytes(b"current progress")
    with pytest.raises(BackupError):
        backup.restore(b.archive, cd, mode="full")
    assert slot.read_bytes() == b"current progress"
