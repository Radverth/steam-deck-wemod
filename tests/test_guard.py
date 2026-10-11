"""Guard: every delete/move/replace call in wemod_deck/ is reviewed.

Phase 2 rule: nothing may change or remove a game's prefix without a
verified backup (backup.protected / backup.create first). New destructive
calls fail this test until they are added below *after checking* they
either go through that gate or never touch a prefix.
"""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent / "wemod_deck"
DESTRUCTIVE = {"rmtree", "remove", "unlink", "rmdir", "rename", "move", "replace"}

# (module, function, call) -> why it is safe
REVIEWED = {
    # Our own files, never inside a prefix.
    ("app.py", "install", "shutil.rmtree"): "staging/old app dirs",
    ("app.py", "install", "staging.rename"): "app dir swap",
    ("app.py", "install", "final.rename"): "app dir swap",
    ("app.py", "install", "package.unlink"): "downloaded nupkg",
    ("app.py", "ensure_dwritecore", "os.replace"): "DWriteCore.dll in app dir",
    ("backup.py", "create", "os.replace"): "backup archive .part",
    ("backup.py", "create", "part.unlink"): "failed backup .part",
    ("backup.py", "create", "archive.unlink"): "failed (unverified) backup",
    (
        "backup.py",
        "prune",
        "b.archive.unlink",
    ): "old backups, after a newer verified one",
    ("backup.py", "prune", "b.manifest_path.unlink"): "old backup manifests",
    ("backup.py", "clear_pending", "_pending_file(appid).unlink"): "marker file",
    ("launch.py", "install_bat", "os.replace"): "our .bat in the data dir",
    ("net.py", "download", "os.replace"): "download .part",
    ("net.py", "download", "part.unlink"): "failed download .part",
    ("status.py", "atomic_write", "os.replace"): "status/manifest temp files",
    ("status.py", "atomic_write", "os.unlink"): "status/manifest temp files",
    ("prefix.py", "ensure", "other.unlink"): "cached prefix zips in ~/.cache",
    # Inside a prefix, but gated or provably save-safe.
    ("backup.py", "_write_member", "os.replace"): "restore: writes the backed-up file",
    (
        "backup.py",
        "_write_member",
        "part.unlink",
    ): "restore: damaged member's temp file",
    ("backup.py", "_restore_registry", "os.replace"): "restore: merged user.reg",
    ("prefix.py", "unpack", "os.replace"): "runs inside backup.protected (ensure)",
    ("prefix.py", "reset_prefix", "cd.rename"): "after backup.create + pending restore",
    ("prefix.py", "reset_prefix", "shutil.rmtree"): "after backup + pending restore",
    ("login.py", "link_logins", "roaming.unlink"): "only a symlink, never its target",
    ("login.py", "link_logins", "roaming.rmdir"): "only an empty folder",
    (
        "login.py",
        "link_logins",
        "shutil.move",
    ): "login moved into central dir, not deleted",
    ("login.py", "_displace", "shutil.move"): "prefix login moved aside, not deleted",
    ("login.py", "migrate_legacy", "dest.rmdir"): "our own empty folder",
}


def destructive_calls() -> Counter:
    found: Counter = Counter()
    for py in sorted(PKG.glob("*.py")):
        tree = ast.parse(py.read_text())
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.FunctionDef):
                continue
            for node in ast.walk(fn):
                if not (
                    isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                ):
                    continue
                attr = node.func.attr
                call = ast.unparse(node.func)
                if attr not in DESTRUCTIVE or (
                    attr == "replace" and call != "os.replace"
                ):
                    continue
                found[(py.name, fn.name, call)] += 1
    return found


def test_every_destructive_call_is_reviewed():
    unreviewed = sorted(set(destructive_calls()) - set(REVIEWED))
    assert not unreviewed, (
        "New delete/move/replace calls need a review against the save-backup "
        f"rule (see this file): {unreviewed}"
    )


def test_reviewed_list_has_no_stale_entries():
    stale = sorted(set(REVIEWED) - set(destructive_calls()))
    assert not stale, f"remove these from REVIEWED: {stale}"
