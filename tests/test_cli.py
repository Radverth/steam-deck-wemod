from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from wemod_deck import cli

REPO = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize(
    "argv, expected",
    [
        (["a", "b"], (False, ["a", "b"])),
        (["--", "a"], (False, ["a"])),
        (["--legacy-args", "--", "-x"], (True, ["-x"])),
        (["--legacy-args", "a", "--", "b"], (True, ["a", "--", "b"])),
        (["--", "--", "a"], (False, ["--", "a"])),
    ],
)
def test_split_launch_args(argv, expected):
    assert cli.split_launch_args(argv) == expected


def test_version_runs_as_module(isolated_home):
    r = subprocess.run(
        [sys.executable, "-m", "wemod_deck", "--version"],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0
    assert r.stdout.startswith("wemod-deck ")


def test_status_without_launches(capsys):
    assert cli.main(["status"]) == 0
    assert "no launches" in capsys.readouterr().out
