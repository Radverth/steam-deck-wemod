"""Save backups: snapshot, verify, restore, retention.

A backup is ``backups/<appid>/<time>-<reason>.tar.zst`` (or ``.tar.gz``)
plus a ``.json`` manifest listing every entry with its size, mtime, SHA-256
or link target. Paths are relative to ``compatdata/<appid>/``.

Rules:
* a backup only counts once it has been read back in full and every entry
  matched the manifest; otherwise it is deleted and :class:`BackupError`
  is raised, which aborts whatever destructive operation wanted it;
* restores never write outside the prefix or outside the backed-up areas,
  never follow symlinks and never delete anything.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from . import __version__, paths
from .status import atomic_write, log

try:  # Python 3.14+
    from compression import zstd as _zstd
except ImportError:  # pragma: no cover - depends on the Python version
    _zstd = None

STEAMUSER = "pfx/drive_c/users/steamuser"
# What a backup contains (decision 3 in docs/plans/phase-2.md).
ROOTS = (STEAMUSER, "pfx/drive_c/ProgramData", "pfx/user.reg")
EXCLUDE = (f"{STEAMUSER}/Temp", f"{STEAMUSER}/AppData/Local/Temp")
# The shared-login links are ours, not the player's (only skipped as links).
EXCLUDE_LINKS = (
    f"{STEAMUSER}/AppData/Roaming/Wand",
    f"{STEAMUSER}/AppData/Roaming/WeMod",
)
REGISTRY = "pfx/user.reg"
SPACE_MARGIN = 64 * 1024 * 1024
DEFAULT_KEEP = 5


class BackupError(RuntimeError):
    pass


class NotEnoughSpace(BackupError):
    pass


@dataclass
class Backup:
    appid: str
    archive: Path
    manifest: dict = field(repr=False)

    @property
    def name(self) -> str:
        return _stem(self.archive)

    @property
    def manifest_path(self) -> Path:
        return self.archive.with_name(self.name + ".json")

    @property
    def created(self) -> str:
        return str(self.manifest.get("created", "?"))

    @property
    def total_size(self) -> int:
        return int(self.manifest.get("total_size", 0))


def _stem(archive: Path) -> str:
    name = archive.name
    for ext in (".tar.zst", ".tar.gz"):
        if name.endswith(ext):
            return name[: -len(ext)]
    return archive.stem


def backups_dir(appid: str | None = None) -> Path:
    base = paths.data_dir() / "backups"
    return base / appid if appid else base


def compression() -> str:
    """Best available: stdlib zstd, the zstd command, or gzip."""
    if _zstd is not None:
        return "zstd"
    if shutil.which("zstd"):
        return "zstd-cli"
    return "gzip"


# ------------------------------------------------------------------ collect --


def _excluded(rel: str, is_link: bool) -> bool:
    if any(rel == e or rel.startswith(e + "/") for e in EXCLUDE):
        return True
    return is_link and rel in EXCLUDE_LINKS


def _walk_error(e: OSError) -> None:
    raise BackupError(f"cannot read {e.filename}: {e.strerror}")


def collect(compatdata: Path) -> list[dict]:
    """Entries to back up, without following any symlink."""
    entries: list[dict] = []

    def add(path: Path) -> None:
        rel = path.relative_to(compatdata).as_posix()
        st = path.lstat()
        if path.is_symlink():
            if not _excluded(rel, True):
                entries.append(
                    {"path": rel, "type": "link", "target": os.readlink(path)}
                )
        elif path.is_dir():
            if not _excluded(rel, False):
                entries.append({"path": rel, "type": "dir", "mtime": int(st.st_mtime)})
        elif path.is_file() and not _excluded(rel, False):
            entries.append(
                {
                    "path": rel,
                    "type": "file",
                    "size": st.st_size,
                    "mtime": int(st.st_mtime),
                }
            )

    for root in ROOTS:
        top = compatdata / root
        if not (top.exists() or top.is_symlink()):
            continue
        add(top)
        if top.is_symlink() or not top.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(top, onerror=_walk_error):
            here = Path(dirpath)
            kept = []
            for d in sorted(dirnames):
                p = here / d
                add(p)
                rel = p.relative_to(compatdata).as_posix()
                if not p.is_symlink() and not _excluded(rel, False):
                    kept.append(d)
            dirnames[:] = kept
            for f in sorted(filenames):
                add(here / f)
    return entries


# ---------------------------------------------------------------- streaming --


@contextlib.contextmanager
def _writer(path: Path, method: str):
    if method == "zstd":
        with _zstd.open(path, "wb") as raw, tarfile.open(fileobj=raw, mode="w|") as t:
            yield t
    elif method == "zstd-cli":
        with open(path, "wb") as out:
            proc = subprocess.Popen(
                ["zstd", "-q", "-3", "-T0", "-c"], stdin=subprocess.PIPE, stdout=out
            )
            try:
                with tarfile.open(fileobj=proc.stdin, mode="w|") as t:
                    yield t
            finally:
                proc.stdin.close()
                if proc.wait() != 0:
                    raise BackupError(f"zstd failed with exit code {proc.returncode}")
    else:
        with tarfile.open(str(path), mode="w|gz") as t:
            yield t


@contextlib.contextmanager
def _reader(path: Path):
    name = path.name[: -len(".part")] if path.name.endswith(".part") else path.name
    if name.endswith(".tar.zst"):
        if _zstd is not None:
            with (
                _zstd.open(path, "rb") as raw,
                tarfile.open(fileobj=raw, mode="r|") as t,
            ):
                yield t
        elif shutil.which("zstd"):
            proc = subprocess.Popen(
                ["zstd", "-q", "-d", "-c", str(path)], stdout=subprocess.PIPE
            )
            try:
                with tarfile.open(fileobj=proc.stdout, mode="r|") as t:
                    yield t
            finally:
                proc.stdout.close()
                proc.wait()
        else:
            raise BackupError(f"{path.name} needs zstd, which is not available")
    else:
        with tarfile.open(str(path), mode="r|gz") as t:
            yield t


class _HashingReader:
    def __init__(self, f):
        self.f = f
        self.sha = hashlib.sha256()

    def read(self, n: int = -1) -> bytes:
        data = self.f.read(n)
        self.sha.update(data)
        return data


def _hash_stream(f) -> str:
    sha = hashlib.sha256()
    for chunk in iter(lambda: f.read(1 << 20), b""):
        sha.update(chunk)
    return sha.hexdigest()


# ------------------------------------------------------------------- create --


def _unique_name(folder: Path, reason: str, now: float | None) -> str:
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(now))
    name, n = f"{stamp}-{reason}", 2
    while any(folder.glob(name + ".*")):
        name, n = f"{stamp}-{n}-{reason}", n + 1
    return name


def create(
    compatdata: Path,
    appid: str,
    reason: str,
    *,
    keep: int = DEFAULT_KEEP,
    now: float | None = None,
    protect: tuple[Path, ...] = (),
) -> Backup:
    """Snapshot the saves of ``compatdata``, verify it, prune old backups
    (never the ones in ``protect``).
    Raises :class:`BackupError` (nothing is left behind) if any step fails."""
    entries = collect(compatdata)
    total = sum(e.get("size", 0) for e in entries)
    folder = backups_dir(appid)
    folder.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(folder).free
    if free < total + SPACE_MARGIN:
        raise NotEnoughSpace(
            f"not enough space for a save backup: need {total // 2**20} MB, "
            f"{free // 2**20} MB free"
        )

    method = compression()
    ext = ".tar.gz" if method == "gzip" else ".tar.zst"
    name = _unique_name(folder, reason, now)
    archive = folder / (name + ext)
    part = folder / (name + ext + ".part")
    try:
        with _writer(part, method) as tar:
            for e in entries:
                info = tarfile.TarInfo(e["path"])
                if e["type"] == "file":
                    info.size, info.mtime, info.mode = e["size"], e["mtime"], 0o644
                    with open(compatdata / e["path"], "rb") as f:
                        reader = _HashingReader(f)
                        tar.addfile(info, reader)
                    e["sha256"] = reader.sha.hexdigest()
                elif e["type"] == "dir":
                    info.type, info.mtime, info.mode = (
                        tarfile.DIRTYPE,
                        e["mtime"],
                        0o755,
                    )
                    tar.addfile(info)
                else:
                    info.type, info.linkname = tarfile.SYMTYPE, e["target"]
                    tar.addfile(info)
        manifest = {
            "format": 1,
            "appid": appid,
            "reason": reason,
            "created": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(now)),
            "created_ns": int(now * 1e9) if now is not None else time.time_ns(),
            "compatdata": str(compatdata),
            "wemod_deck": __version__,
            "compression": method,
            "total_size": total,
            "entries": entries,
        }
        verify(part, manifest)
        os.replace(part, archive)
        atomic_write(archive.with_name(name + ".json"), json.dumps(manifest, indent=1))
    except (OSError, tarfile.TarError, BackupError) as e:
        part.unlink(missing_ok=True)
        archive.unlink(missing_ok=True)
        if isinstance(e, BackupError):
            raise
        raise BackupError(f"save backup failed: {e}") from e

    backup = Backup(appid, archive, manifest)
    log.info(
        "backup %s: %d entries, %d MB (%s)",
        archive,
        len(entries),
        total // 2**20,
        method,
    )
    prune(appid, keep, protect=protect)
    return backup


def verify(archive: Path, manifest: dict) -> None:
    """Read the whole archive back and compare it with the manifest."""
    expected = {e["path"]: e for e in manifest["entries"]}
    seen: set[str] = set()
    try:
        with _reader(archive) as tar:
            for m in tar:
                e = expected.get(m.name)
                if e is None or m.name in seen:
                    raise BackupError(f"unexpected entry {m.name!r} in {archive.name}")
                seen.add(m.name)
                if e["type"] == "file":
                    f = tar.extractfile(m) if m.isfile() else None
                    if (
                        f is None
                        or m.size != e["size"]
                        or _hash_stream(f) != e["sha256"]
                    ):
                        raise BackupError(f"{m.name} does not match in {archive.name}")
                elif e["type"] == "dir" and not m.isdir():
                    raise BackupError(f"{m.name} should be a folder")
                elif e["type"] == "link" and (
                    not m.issym() or m.linkname != e["target"]
                ):
                    raise BackupError(f"{m.name} should link to {e['target']}")
    except (OSError, tarfile.TarError, EOFError) as e:
        raise BackupError(f"{archive.name} is unreadable: {e}") from e
    missing = set(expected) - seen
    if missing:
        raise BackupError(f"{len(missing)} entries missing from {archive.name}")


# ------------------------------------------------------------------ restore --


def _allowed(name: str) -> bool:
    rel = PurePosixPath(name)
    if rel.is_absolute() or ".." in rel.parts or "/".join(rel.parts) != name:
        return False
    return any(name == r or name.startswith(r + "/") for r in ROOTS)


def _inside(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root)
        return True
    except ValueError:
        return False


def restore(
    archive: Path, compatdata: Path, *, mode: str = "missing", dry_run: bool = False
) -> dict:
    """Put a backup back into ``compatdata``.

    ``missing``: only entries that don't exist now (nothing is overwritten).
    ``full``: also overwrite files that differ from the backup.
    Never deletes anything, never writes through symlinks. ``user.reg`` is
    merged section by section instead of replaced. Returns counts.
    """
    from .prefix import merge_registry

    if mode not in ("missing", "full"):
        raise ValueError(mode)
    manifest = read_manifest(archive)
    sums = {e["path"]: e.get("sha256") for e in manifest["entries"]}
    root = compatdata.resolve()
    counts = {"restored": 0, "unchanged": 0, "kept": 0, "refused": 0}
    try:
        with _reader(archive) as tar:
            for m in tar:
                name = m.name
                target = compatdata / name
                if not _allowed(name) or not _inside(root, target.parent):
                    counts["refused"] += 1
                    continue
                if m.isdir():
                    if not target.exists() and not target.is_symlink():
                        if not dry_run:
                            target.mkdir(parents=True, exist_ok=True)
                        counts["restored"] += 1
                    continue
                if m.issym():
                    if target.is_symlink() and os.readlink(target) == m.linkname:
                        counts["unchanged"] += 1
                    elif target.exists() or target.is_symlink():
                        counts["kept"] += 1  # never replace what's there
                    else:
                        if not dry_run:
                            target.parent.mkdir(parents=True, exist_ok=True)
                            os.symlink(m.linkname, target)
                        counts["restored"] += 1
                    continue
                if not m.isfile():
                    counts["refused"] += 1
                    continue
                exists = target.exists() or target.is_symlink()
                if exists and (target.is_dir() or target.is_symlink()):
                    counts["kept"] += 1
                    continue
                if name == REGISTRY and exists:
                    changed = _restore_registry(
                        tar, m, target, mode, dry_run, merge_registry
                    )
                    counts["restored" if changed else "unchanged"] += 1
                    continue
                if exists and mode == "missing":
                    counts["kept"] += 1
                    continue
                if exists:
                    with open(target, "rb") as cur:
                        if _hash_stream(cur) == sums.get(name):
                            counts["unchanged"] += 1
                            continue
                if not dry_run:
                    _write_member(tar, m, target, sums.get(name))
                counts["restored"] += 1
    except (OSError, tarfile.TarError, EOFError) as e:
        raise BackupError(f"restore from {archive.name} failed: {e}") from e
    log.info("restore %s (%s): %s", archive.name, mode, counts)
    return counts


def _write_member(tar, m, target: Path, sha: str | None) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".wemod-deck-restore")
    with tar.extractfile(m) as src, open(part, "wb") as out:
        reader = _HashingReader(src)
        shutil.copyfileobj(reader, out)
    if sha and reader.sha.hexdigest() != sha:
        part.unlink()
        raise BackupError(f"{m.name} is damaged in the backup; not restored")
    os.utime(part, (m.mtime, m.mtime))
    os.replace(part, target)


def _restore_registry(tar, m, target: Path, mode: str, dry_run: bool, merge) -> bool:
    saved = tar.extractfile(m).read().decode("utf-8", "surrogateescape")
    current = target.read_text("utf-8", "surrogateescape")
    # missing: keep current values, add what only the backup has.
    # full: backup values win, keys only present now are kept.
    merged = merge(current, saved) if mode == "missing" else merge(saved, current)
    if merged == current:
        return False
    if not dry_run:
        part = target.with_name(target.name + ".wemod-deck-restore")
        part.write_text(merged, "utf-8", "surrogateescape")
        os.replace(part, target)
    return True


# ----------------------------------------------------------- list / retain --


def read_manifest(archive: Path) -> dict:
    path = archive.with_name(_stem(archive) + ".json")
    try:
        data = json.loads(path.read_text())
        if not isinstance(data.get("entries"), list):
            raise ValueError("no entries")
        return data
    except (OSError, ValueError) as e:
        raise BackupError(f"manifest {path.name} is missing or broken: {e}") from e


def list_backups(appid: str | None = None) -> list[Backup]:
    """Backups (newest first) for one AppID or all."""
    base = backups_dir()
    folders = (
        [base / appid] if appid else sorted(p for p in base.glob("*") if p.is_dir())
    )
    out = []
    for folder in folders:
        for archive in folder.glob("*.tar.*"):
            if archive.name.endswith(".part"):
                continue
            try:
                out.append(Backup(folder.name, archive, read_manifest(archive)))
            except BackupError:
                continue
    out.sort(key=lambda b: (b.manifest.get("created_ns", 0), b.name), reverse=True)
    out.sort(key=lambda b: b.appid)  # stable: per AppID, newest first
    return out


def find(appid: str, name: str | None = None) -> Backup:
    backups = list_backups(appid)
    if name:
        backups = [b for b in backups if b.name == name or b.name.startswith(name)]
    if not backups:
        raise BackupError(f"no backup{' ' + name if name else ''} for AppID {appid}")
    return backups[0]


def prune(appid: str, keep: int, protect: tuple[Path, ...] = ()) -> list[Path]:
    """Delete all but the newest ``keep`` backups, never the one a pending
    restore points to or any in ``protect``."""
    protected = {p.get("archive") for p in [pending(appid)] if p}
    protected |= {str(p) for p in protect}
    removed = []
    for b in list_backups(appid)[max(keep, 1) :]:
        if str(b.archive) in protected:
            continue
        b.archive.unlink(missing_ok=True)
        b.manifest_path.unlink(missing_ok=True)
        removed.append(b.archive)
    if removed:
        log.info("pruned %d old backups of %s", len(removed), appid)
    return removed


# ----------------------------------------------------------- pending restore --


def _pending_file(appid: str) -> Path:
    return paths.data_dir() / "pending-restore" / appid


def set_pending(appid: str, archive: Path, compatdata: Path) -> None:
    atomic_write(
        _pending_file(appid),
        json.dumps({"archive": str(archive), "compatdata": str(compatdata)}) + "\n",
    )


def pending(appid: str | None) -> dict | None:
    if not appid:
        return None
    try:
        data = json.loads(_pending_file(appid).read_text())
        return data if isinstance(data, dict) and data.get("archive") else None
    except (OSError, ValueError):
        return None


def clear_pending(appid: str) -> None:
    _pending_file(appid).unlink(missing_ok=True)


def all_pending() -> list[str]:
    folder = paths.data_dir() / "pending-restore"
    return sorted(p.name for p in folder.glob("*")) if folder.is_dir() else []


# -------------------------------------------------------------------- gate --


@contextlib.contextmanager
def protected(
    compatdata: Path,
    appid: str,
    reason: str,
    *,
    keep: int = DEFAULT_KEEP,
    restore_after: bool = True,
):
    """Every destructive prefix operation runs inside this: verified backup
    first (raises BackupError to abort), then afterwards anything that went
    missing is put back, even if the operation failed half way."""
    backup = create(compatdata, appid, reason, keep=keep)
    try:
        yield backup
    finally:
        if restore_after and compatdata.is_dir():
            counts = restore(backup.archive, compatdata, mode="missing")
            if counts["restored"]:
                log.warning("put back %d entries after %s", counts["restored"], reason)


# --------------------------------------------------------------------- CLI --


def _mb(n: int) -> str:
    return f"{n / 2**20:.1f} MB"


def _compatdata(appid: str) -> Path | None:
    from . import steam

    root = steam.find_steam_root()
    found = steam.find_compatdata(root, appid) if root else []
    return found[0] if len(found) == 1 else None


def cli(args, cfg) -> int:
    if args.backups_command == "list":
        backups = list_backups(args.appid)
        if not backups:
            print("No backups yet.")
        for b in backups:
            print(
                f"{b.appid:>10}  {b.name:<28}  {len(b.manifest['entries']):>6} entries"
                f"  {_mb(b.total_size):>10}  ({_mb(b.archive.stat().st_size)} on disk)"
            )
        for appid in all_pending():
            if not args.appid or args.appid == appid:
                print(f"Pending restore for AppID {appid}: runs on its next launch.")
        return 0

    if not args.appid.isdigit():
        log.error("AppID must be a number")
        return 1
    cd = _compatdata(args.appid)
    if cd is None:
        log.error(
            "no single prefix found for AppID %s (launch the game once first)",
            args.appid,
        )
        return 1
    try:
        if args.backups_command == "create":
            b = create(cd, args.appid, "manual", keep=cfg.backups_keep)
            print(f"Backed up {len(b.manifest['entries'])} entries to {b.archive}")
            return 0
        # restore
        target = find(args.appid, args.name)
        pids = prefix_in_use(cd)
        if pids:
            log.error("the game is still running (process %s); quit it first", pids[0])
            return 1
        if not args.dry_run:
            undo = create(
                cd,
                args.appid,
                "pre-restore",
                keep=cfg.backups_keep,
                protect=(target.archive,),
            )
            print(f"Current state saved first: {undo.name} (restore it to undo)")
        counts = restore(target.archive, cd, mode="full", dry_run=args.dry_run)
    except BackupError as e:
        log.error("%s", e)
        return 1
    verb = "Would restore" if args.dry_run else "Restored"
    print(
        f"{verb} {counts['restored']} entries from {target.name} "
        f"({counts['unchanged']} unchanged, {counts['kept']} left as they are)."
    )
    return 0


# ------------------------------------------------------------ running game --


def prefix_in_use(compatdata: Path) -> list[int]:
    """PIDs of our user's processes started for this prefix (Steam sets
    STEAM_COMPAT_DATA_PATH for the game and everything it starts)."""
    want = {str(compatdata), os.path.realpath(compatdata)}
    pids = []
    for proc in Path("/proc").glob("[0-9]*"):
        if proc.name == str(os.getpid()):
            continue
        try:
            env = (proc / "environ").read_bytes().split(b"\0")
        except OSError:
            continue
        for item in env:
            if item.startswith(b"STEAM_COMPAT_DATA_PATH="):
                value = item.split(b"=", 1)[1].decode("utf-8", "replace").rstrip("/")
                if value in want:
                    pids.append(int(proc.name))
                break
    return pids
