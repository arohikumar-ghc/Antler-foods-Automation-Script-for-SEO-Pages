"""Offline tests for the CLI argument parsing (no browser, no network)."""
import pytest

import main as cli


def _parse(argv):
    return cli._build_parser().parse_args(argv)


# --- write-back default + opt-out ------------------------------------------


def test_write_back_on_by_default():
    args = _parse(["--all-pages", "--allow-content-mismatch"])
    assert args.write_back is True
    assert args.publish is False


def test_no_write_back_opt_out():
    args = _parse(["--all-pages", "--no-write-back"])
    assert args.write_back is False


def test_explicit_write_back():
    args = _parse(["--write-back"])
    assert args.write_back is True


def test_write_back_and_no_write_back_conflict():
    with pytest.raises(SystemExit):
        _parse(["--write-back", "--no-write-back"])


# --- publishing off by default ---------------------------------------------


def test_publish_off_by_default():
    assert _parse([]).publish is False


def test_publish_opt_in():
    assert _parse(["--publish"]).publish is True


# --- single-restaurant + page controls preserved --------------------------


def test_restaurant_repeatable():
    args = _parse(["--restaurant", "Renovo", "--restaurant", "Karma"])
    assert args.restaurant == ["Renovo", "Karma"]


def test_allow_content_mismatch_flag():
    assert _parse(["--allow-content-mismatch"]).allow_content_mismatch is True


def test_max_pages_value():
    assert _parse(["--max-pages", "3"]).max_pages == 3


def test_all_pages_and_max_pages_conflict():
    with pytest.raises(SystemExit):
        _parse(["--all-pages", "--max-pages", "3"])


# --- defaults for a bare invocation ----------------------------------------


def test_bare_defaults():
    args = _parse([])
    assert args.write_back is True        # default-on
    assert args.publish is False          # default-off
    assert args.restaurant is None        # all pending
    assert args.max_pages is None         # all pages
    assert args.allow_content_mismatch is False
