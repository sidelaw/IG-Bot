"""Config loading guards: unknown keys and list-vs-scalar mistakes."""

from __future__ import annotations

import pytest

from igbot import config


def _write(tmp_path, text):
    p = tmp_path / "config.toml"
    p.write_text(text)
    return p


def test_unknown_key_named(tmp_path):
    p = _write(tmp_path, '[[feeds]]\nsource="reddit"\nname="f"\ntimewindow="week"\n')
    with pytest.raises(ValueError, match="timewindow"):
        config.load(p)


def test_scalar_where_list_expected(tmp_path):
    # subreddits must be a list; a bare string would otherwise be iterated
    # character-by-character far downstream.
    p = _write(tmp_path, '[[feeds]]\nsource="reddit"\nname="f"\nsubreddits="lawn"\n')
    with pytest.raises(ValueError, match="must be a list"):
        config.load(p)


def test_missing_config_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        config.load(tmp_path / "nope.toml")
