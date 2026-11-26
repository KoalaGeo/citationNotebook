"""Tests for the command line (``citations.cli``)."""

from citations import cli


def test_options_before_or_after_the_command(tmp_path):
    """Common options work before or after the command, and ``harvest`` alone means every source."""
    parser = cli.build_parser()
    a = parser.parse_args(["--db", str(tmp_path / "a.sqlite"), "status"])
    b = parser.parse_args(["status", "--db", str(tmp_path / "a.sqlite")])
    assert a.db == b.db == tmp_path / "a.sqlite"
    assert parser.parse_args(["harvest", "scholexplorer", "crossref"]).sources == ["scholexplorer", "crossref"]
    assert not parser.parse_args(["harvest"]).sources   # empty = every source


def test_status_on_an_empty_store(tmp_path, capsys):
    """``status`` on a new, empty store succeeds."""
    assert cli.main(["--db", str(tmp_path / "s.sqlite"), "status"]) == 0


def test_publish_without_any_harvest_is_blocked(tmp_path):
    """``publish`` with nothing harvested exits 2 and writes no results."""
    code = cli.main(["--db", str(tmp_path / "s.sqlite"), "--results", str(tmp_path / "Results"), "publish"])
    assert code == 2
    assert not (tmp_path / "Results" / "v4").exists()


def test_unknown_source_is_rejected():
    """``harvest`` with a source that does not exist is a usage error."""
    import pytest
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["harvest", "scopus"])


def test_accept_drop_option():
    """``all``, ``harvest`` and ``publish`` accept ``--accept-drop`` with several sources; it defaults to none."""
    parser = cli.build_parser()
    for command in (["all"], ["harvest", "scholexplorer"], ["publish"]):
        args = parser.parse_args(command + ["--accept-drop", "scholexplorer", "datacite"])
        assert args.accept_drop == ["scholexplorer", "datacite"]
    assert parser.parse_args(["harvest", "scholexplorer"]).accept_drop == []


def test_harvest_without_an_inventory_is_an_error_not_a_traceback(tmp_path, caplog):
    """Harvesting before any inventory exits 1 with a message that names the inventory."""
    assert cli.main(["--db", str(tmp_path / "s.sqlite"), "harvest", "scholexplorer"]) == 1
    assert "inventory" in caplog.text
