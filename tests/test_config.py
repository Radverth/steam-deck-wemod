from __future__ import annotations

import pytest

from wemod_deck import config, paths
from wemod_deck.config import Config, ConfigError, parse_toml_subset

SAMPLE = """\
# wemod-deck config
app = "wemod"   # inline comment
enabled = true
log_level = "debug"

[apps."1234560"]
enabled = false

[apps.42]
enabled = true
"""


def write(text: str):
    path = paths.config_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_missing_file_gives_defaults():
    cfg, warnings = config.load(paths.config_file())
    assert cfg == Config()
    assert cfg.app == "wand"
    assert cfg.enabled_for("1") is True
    assert warnings == []


def test_full_sample():
    cfg, warnings = config.load(write(SAMPLE))
    assert warnings == []
    assert cfg.app == "wemod"
    assert cfg.log_level == "debug"
    assert cfg.enabled_for("1234560") is False
    assert cfg.enabled_for("42") is True
    assert cfg.enabled_for("999") is True
    assert cfg.enabled_for(None) is True


def test_global_disable_with_per_app_enable():
    cfg, _ = config.load(write('enabled = false\n[apps."7"]\nenabled = true\n'))
    assert cfg.enabled_for("7") is True
    assert cfg.enabled_for("8") is False


@pytest.mark.parametrize(
    "text, warning",
    [
        ("app = ", "using defaults"),
        ('app = "steam"', "app must be one of"),
        ('enabled = "yes"', "wrong type"),
        ("colour = 1", "unknown setting"),
        ('[apps."abc"]\nenabled = false', "AppIDs are numbers"),
        ('[apps."1"]\nenabled = 1', "wrong type"),
        ('[apps."1"]\nfoo = true', "unknown setting"),
        ('log_level = "loud"', "log_level must be"),
    ],
)
def test_bad_content_warns_and_keeps_defaults(text, warning):
    cfg, warnings = config.load(write(text))
    assert any(warning in w for w in warnings), warnings
    assert cfg.app == "wand"
    assert cfg.enabled_for("1") is True


def test_unreadable_path_warns(tmp_path):
    cfg, warnings = config.load(tmp_path)  # a directory
    assert cfg == Config()
    assert warnings


def test_subset_parser_matches_tomllib():
    tomllib = pytest.importorskip("tomllib")
    assert parse_toml_subset(SAMPLE) == tomllib.loads(SAMPLE)


def test_subset_parser_strings_and_comments():
    assert parse_toml_subset('a = "x # not a comment" # real\n') == {
        "a": "x # not a comment"
    }


@pytest.mark.parametrize("text", ["[apps", "x", "a = [1]", "a = 1\na = 2", "[[t]]"])
def test_subset_parser_rejects(text):
    with pytest.raises(ConfigError):
        parse_toml_subset(text)


def test_subset_parser_used_without_tomllib(monkeypatch):
    monkeypatch.setattr(config, "_toml", None)
    cfg, warnings = config.load(write(SAMPLE))
    assert warnings == []
    assert cfg.enabled_for("1234560") is False


@pytest.mark.parametrize("text", ["apps = 1\napps.x = 2", "[a]\nb = 1\n[a.b]\nc = 1"])
def test_subset_parser_type_clashes_are_config_errors(text):
    with pytest.raises(ConfigError):
        parse_toml_subset(text)


def test_non_utf8_file_warns():
    path = paths.config_file()
    path.parent.mkdir(parents=True)
    path.write_bytes(b'app = "\xff\xfe"\n')
    cfg, warnings = config.load(path)
    assert cfg == Config() and warnings


@pytest.mark.parametrize(
    "text, keep, warned",
    [
        ("backups_keep = 3", 3, False),
        ("backups_keep = 0", 5, True),
        ("backups_keep = true", 5, True),
        ('backups_keep = "3"', 5, True),
    ],
)
def test_backups_keep(text, keep, warned):
    cfg, warnings = config.load(write(text))
    assert cfg.backups_keep == keep
    assert bool(warnings) is warned
