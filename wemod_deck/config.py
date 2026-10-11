"""User config: ``~/.config/wemod-deck/config.toml``.

Global keys plus per-AppID overrides::

    app = "wand"          # "wand" (default) or "wemod"
    enabled = true

    [apps."1234560"]
    enabled = false       # this game runs plain GE-Proton

A missing file means defaults. A broken file also means defaults, plus
warnings: the config must never stop a game from launching.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

try:  # Python 3.11+
    import tomllib as _toml
except ModuleNotFoundError:  # pragma: no cover - exercised via parse_toml_subset
    _toml = None

APPS = ("wand", "wemod")
LOG_LEVELS = ("debug", "info", "warning", "error")
_GLOBAL_KEYS = {"app": str, "enabled": bool, "log_level": str, "backups_keep": int}
_APP_KEYS = {"enabled": bool}


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Config:
    app: str = "wand"
    enabled: bool = True
    log_level: str = "info"
    backups_keep: int = 5  # save backups kept per game
    apps: dict[str, dict] = field(default_factory=dict)

    def enabled_for(self, appid: str | None) -> bool:
        if appid and appid in self.apps and "enabled" in self.apps[appid]:
            return bool(self.apps[appid]["enabled"])
        return self.enabled


def parse_toml_subset(text: str) -> dict:
    """Parse the small TOML subset our config uses, for Pythons without
    ``tomllib``: comments, ``[table]`` / ``[a."b"]`` headers and
    ``key = value`` with strings, booleans and integers."""
    root: dict = {}
    table = root
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = _strip_comment(raw).strip()
        if not line:
            continue
        if line.startswith("["):
            if not line.endswith("]") or line.startswith("[["):
                raise ConfigError(f"line {lineno}: bad table header")
            table = _table(root, _split_key(line[1:-1], lineno), lineno)
            continue
        key, sep, value = line.partition("=")
        if not sep:
            raise ConfigError(f"line {lineno}: expected key = value")
        keys = _split_key(key, lineno)
        target = _table(table, keys[:-1], lineno)
        if keys[-1] in target:
            raise ConfigError(f"line {lineno}: duplicate key {keys[-1]}")
        target[keys[-1]] = _parse_value(value.strip(), lineno)
    return root


def _table(root: dict, keys: list[str], lineno: int) -> dict:
    table = root
    for part in keys:
        table = table.setdefault(part, {})
        if not isinstance(table, dict):
            raise ConfigError(f"line {lineno}: {part} is not a table")
    return table


def _strip_comment(line: str) -> str:
    in_str = False
    for i, ch in enumerate(line):
        if ch == '"' and (i == 0 or line[i - 1] != "\\"):
            in_str = not in_str
        elif ch == "#" and not in_str:
            return line[:i]
    return line


def _split_key(key: str, lineno: int) -> list[str]:
    parts, buf, in_str = [], "", False
    for ch in key.strip():
        if ch == '"':
            in_str = not in_str
        elif ch == "." and not in_str:
            parts.append(buf.strip())
            buf = ""
        else:
            buf += ch
    parts.append(buf.strip())
    if in_str or not all(parts):
        raise ConfigError(f"line {lineno}: bad key {key.strip()!r}")
    return parts


def _parse_value(value: str, lineno: int):
    if value in ("true", "false"):
        return value == "true"
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    try:
        return int(value)
    except ValueError:
        raise ConfigError(f"line {lineno}: unsupported value {value!r}") from None


def parse(text: str) -> dict:
    if _toml is not None:
        try:
            return _toml.loads(text)
        except _toml.TOMLDecodeError as e:
            raise ConfigError(str(e)) from None
    return parse_toml_subset(text)


def load(path: Path) -> tuple[Config, list[str]]:
    """Return the config and a list of warnings. Never raises for bad
    content; unreadable or invalid parts fall back to defaults."""
    warnings: list[str] = []
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return Config(), warnings
    except (OSError, UnicodeDecodeError) as e:
        return Config(), [f"cannot read {path}: {e}"]
    try:
        data = parse(text)
    except ConfigError as e:
        return Config(), [f"{path}: {e}; using defaults"]

    values: dict = {}
    for key, value in data.items():
        if key == "apps":
            continue
        if key not in _GLOBAL_KEYS:
            warnings.append(f"unknown setting {key!r} ignored")
        elif type(value) is not _GLOBAL_KEYS[key]:  # bool is not an int here
            warnings.append(f"{key} has the wrong type; using the default")
        else:
            values[key] = value
    if values.get("app", "wand") not in APPS:
        warnings.append(f"app must be one of {', '.join(APPS)}; using wand")
        values.pop("app")
    if values.get("log_level", "info") not in LOG_LEVELS:
        warnings.append(f"log_level must be one of {', '.join(LOG_LEVELS)}")
        values.pop("log_level")
    if not 1 <= values.get("backups_keep", 5) <= 100:
        warnings.append("backups_keep must be between 1 and 100; using 5")
        values.pop("backups_keep")

    apps: dict[str, dict] = {}
    raw_apps = data.get("apps", {})
    if not isinstance(raw_apps, dict):
        warnings.append("[apps] must be a table; ignored")
        raw_apps = {}
    for appid, settings in raw_apps.items():
        appid = str(appid)
        if not appid.isdigit() or not isinstance(settings, dict):
            warnings.append(f"[apps.{appid}] ignored: AppIDs are numbers")
            continue
        clean = {}
        for key, value in settings.items():
            if key not in _APP_KEYS:
                warnings.append(f"[apps.{appid}] unknown setting {key!r} ignored")
            elif not isinstance(value, _APP_KEYS[key]):
                warnings.append(f"[apps.{appid}] {key} has the wrong type; ignored")
            else:
                clean[key] = value
        apps[appid] = clean

    return Config(apps=apps, **values), warnings
