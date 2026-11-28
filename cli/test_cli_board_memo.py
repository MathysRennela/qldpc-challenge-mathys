"""The CLI shares one board memo across checkouts (issue #7381).

The verifier's per-entry memo defaults to a directory inside the checkout, so
a fresh worktree paid the whole structural pass (about 44 s) before any
submission logic. The CLI points it at one per-user directory instead, and
only when nothing else has chosen: a caller's QLDPC_BOARD_CACHE wins, an empty
value keeps the memo off (the test suite's default), and CI is left alone.
"""

import os

import qldpc


def test_an_unset_environment_gets_the_shared_directory(monkeypatch, tmp_path):
    monkeypatch.delenv(qldpc.BOARD_MEMO_ENV, raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    path = qldpc._default_board_memo()
    assert path == os.path.join(str(tmp_path / "xdg"), "qldpc", "boardcache")
    assert os.environ[qldpc.BOARD_MEMO_ENV] == path
    # idempotent: a second call sees the value it set and leaves it
    assert qldpc._default_board_memo() is None and os.environ[qldpc.BOARD_MEMO_ENV] == path


def test_without_xdg_the_directory_is_under_the_home_cache(monkeypatch):
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    monkeypatch.setenv("HOME", "/tmp/qldpc-home")
    assert qldpc._shared_board_memo_dir() == os.path.join(os.path.expanduser("~"), ".cache", "qldpc", "boardcache")
    assert qldpc._shared_board_memo_dir().startswith("/tmp/qldpc-home")


def test_a_callers_choice_is_kept_including_off(monkeypatch, tmp_path):
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setenv(qldpc.BOARD_MEMO_ENV, str(tmp_path / "mine"))
    assert qldpc._default_board_memo() is None and os.environ[qldpc.BOARD_MEMO_ENV] == str(tmp_path / "mine")
    monkeypatch.setenv(qldpc.BOARD_MEMO_ENV, "")
    assert qldpc._default_board_memo() is None and os.environ[qldpc.BOARD_MEMO_ENV] == ""


def test_ci_is_left_alone(monkeypatch):
    monkeypatch.delenv(qldpc.BOARD_MEMO_ENV, raising=False)
    monkeypatch.setenv("CI", "true")
    assert qldpc._default_board_memo() is None and qldpc.BOARD_MEMO_ENV not in os.environ


def test_the_verifier_reads_the_directory_the_cli_set(monkeypatch, tmp_path):
    import qldpc_verify as Q

    monkeypatch.delenv(qldpc.BOARD_MEMO_ENV, raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    path = qldpc._default_board_memo()
    assert Q.board_cache_dir() == path


def test_main_sets_the_default_before_parsing(monkeypatch, tmp_path, capsys):
    import pytest

    monkeypatch.delenv(qldpc.BOARD_MEMO_ENV, raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    with pytest.raises(SystemExit):
        qldpc.main(["--help"])
    assert os.environ[qldpc.BOARD_MEMO_ENV].endswith(os.path.join("qldpc", "boardcache"))


# -- one process, one board (issue #7563) -------------------------------------


def _fake_board(tmp_path, monkeypatch):
    import build

    codes = tmp_path / "codes"
    codes.mkdir()
    (codes / "7-1-3.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(qldpc, "_ROOT", str(tmp_path))
    calls = []

    def load_entries():
        calls.append(len(os.listdir(codes)))
        return [{"slug": "7-1-3", "n": 7, "k": 1, "d": 3, "w": 4}]

    monkeypatch.setattr(build, "load_entries", load_entries)
    qldpc.forget_board()
    return codes, calls


def test_an_unchanged_board_is_loaded_once_per_process(tmp_path, monkeypatch):
    codes, calls = _fake_board(tmp_path, monkeypatch)
    first = qldpc._load_board_entries(quiet=True)
    assert first == [{"slug": "7-1-3", "n": 7, "k": 1, "d": 3, "w": 4}] and calls == [1]
    for _ in range(3):
        assert qldpc._load_board_entries(quiet=True) == first
    assert calls == [1]
    # a caller's edit of the list it got does not reach the memo
    first.append("junk")
    assert qldpc._load_board_entries(quiet=True) == first[:-1] and calls == [1]


def test_a_changed_board_is_loaded_again_and_a_seen_state_is_remembered(tmp_path, monkeypatch):
    codes, calls = _fake_board(tmp_path, monkeypatch)
    qldpc._load_board_entries(quiet=True)
    (codes / "9-1-3.json").write_text("{}", encoding="utf-8")  # a write-mode batch filed an entry
    qldpc._load_board_entries(quiet=True)
    assert calls == [1, 2]
    (codes / "9-1-3.json").write_text('{"n": 9}', encoding="utf-8")  # an edit in place changes the size
    qldpc._load_board_entries(quiet=True)
    assert calls == [1, 2, 2]
    os.remove(codes / "9-1-3.json")  # back to the first state, as after open_pr returns to the base branch
    qldpc._load_board_entries(quiet=True)
    assert calls == [1, 2, 2]
    (codes / "notes.txt").write_text("not an entry", encoding="utf-8")  # only *.json is the board
    qldpc._load_board_entries(quiet=True)
    assert calls == [1, 2, 2]


def test_the_memo_is_bounded_and_forget_board_empties_it(tmp_path, monkeypatch):
    codes, calls = _fake_board(tmp_path, monkeypatch)
    for i in range(qldpc._BOARD_MEMO_KEEP + 2):
        (codes / f"{10 + i}-1-3.json").write_text("{}", encoding="utf-8")
        qldpc._load_board_entries(quiet=True)
    assert len(qldpc._BOARD_ENTRIES_MEMO) == qldpc._BOARD_MEMO_KEEP
    qldpc.forget_board()
    assert qldpc._BOARD_ENTRIES_MEMO == {}
    qldpc._load_board_entries(quiet=True)
    assert len(calls) == qldpc._BOARD_MEMO_KEEP + 3


def test_an_unreadable_codes_dir_is_never_memoized(tmp_path, monkeypatch):
    _codes, calls = _fake_board(tmp_path, monkeypatch)
    monkeypatch.setattr(qldpc, "_ROOT", str(tmp_path / "missing"))
    assert qldpc._board_state() is None
    qldpc._load_board_entries(quiet=True)
    qldpc._load_board_entries(quiet=True)
    assert calls == [1, 1] and qldpc._BOARD_ENTRIES_MEMO == {}
