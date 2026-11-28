"""Tests for the campaign-review skill's script (.agents/skills/campaign-review).

The property that matters: a campaign that ran to its end cannot pass `check`
without a retrospective of the agreed shape, however its harness behaved.
"""

import json
import os
import shlex
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, ".agents", "skills", "campaign-review"))

import campaign_review as cr  # noqa: E402

SUGGESTION = """### Report the failing parent
- Evidence: run.log line 12 shows a traceback with no parent slug
- Expected effect: a crash can be reproduced
  without rerunning the sweep
- Done when: the error names the slug
- Already tracked: none found
"""


def retro(challenge="None.", calculus="Not applicable.", reviewer="fresh-session"):
    return (
        f"# Retrospective: x\n\nReviewer: {reviewer}\n\n## What happened\n\nIt ran.\n\n"
        f"## Suggestions: qldpc-challenge\n\n{challenge}\n\n## Suggestions: code-calculus\n\n{calculus}\n"
    )


def finish(root, cid):
    (cr.campaign_dir(root, cid) / "summary.json").write_text(json.dumps({"campaign_id": cid}), encoding="utf-8")


@pytest.mark.parametrize("text", [retro(), retro(SUGGESTION, "None.", "same-session")])
def test_valid_retros(text):
    assert cr.retro_problems(text) == []


@pytest.mark.parametrize(
    "text",
    [
        "",
        retro(reviewer="me"),
        retro(challenge="Not applicable."),
        retro(challenge=""),
        retro(challenge="Make it faster."),
        retro(challenge=SUGGESTION * 4),
        retro(challenge=SUGGESTION.replace("- Done when: the error names the slug", "- Done when:")),
        retro().replace("It ran.", "<!-- fill in -->"),
    ],
)
def test_invalid_retros(text):
    assert cr.retro_problems(text)


def test_life_cycle(tmp_path):
    home = cr.start(tmp_path, "one")
    assert cr.state(home)[0] == "running"
    assert cr.check(tmp_path) == 0
    finish(tmp_path, "one")
    cr.close(tmp_path, "one")
    assert cr.state(home)[0] == "owed"
    assert cr.check(tmp_path) == 1
    (home / "RETRO.md").write_text(retro(), encoding="utf-8")
    assert cr.state(home)[0] == "reviewed"
    assert cr.check(tmp_path) == 0


def test_summary_alone_means_a_review_is_owed(tmp_path):
    cr.start(tmp_path, "one")
    finish(tmp_path, "one")
    assert cr.check(tmp_path) == 1


def test_owed_review_blocks_the_next_start(tmp_path):
    cr.start(tmp_path, "one")
    cr.start(tmp_path, "parallel")  # a running campaign blocks nothing
    finish(tmp_path, "one")
    with pytest.raises(cr.ReviewError, match="one"):
        cr.start(tmp_path, "two")
    home = cr.start(tmp_path, "two", allow_owed="reviewer unavailable")
    assert cr.read_marker(home)["started_while_owed"]["campaigns"] == ["one"]


def test_restart_keeps_the_old_retro(tmp_path):
    home = cr.start(tmp_path, "one")
    (home / "RETRO.md").write_text(retro(), encoding="utf-8")
    cr.start(tmp_path, "one")
    assert not (home / "RETRO.md").exists()
    assert len(list(home.glob("RETRO-*.md"))) == 1
    assert cr.state(home)[0] == "running"


def test_close_needs_a_summary_unless_the_run_failed(tmp_path):
    home = cr.start(tmp_path, "one")
    with pytest.raises(cr.ReviewError, match="failed"):
        cr.close(tmp_path, "one")
    (home / "summary.json").write_text('{"campaign_id": "other"}', encoding="utf-8")
    with pytest.raises(cr.ReviewError, match="other"):
        cr.close(tmp_path, "one")
    (home / "summary.json").unlink()
    cr.close(tmp_path, "one", status="failed")
    assert cr.state(home)[0] == "owed"


def test_ids_cannot_leave_the_campaigns_folder(tmp_path):
    with pytest.raises(cr.ReviewError):
        cr.start(tmp_path, "../escape")


@pytest.mark.parametrize("via_file", [False, True])
def test_reviewer_command(tmp_path, via_file):
    home = cr.start(tmp_path, "one")
    finish(tmp_path, "one")
    agent = tmp_path / "agent.py"
    agent.write_text(
        "import pathlib, sys\n"
        "brief = pathlib.Path(sys.argv[2]).read_text() if len(sys.argv) > 2 else sys.stdin.read()\n"
        "assert 'id: one' in brief\n"
        f"pathlib.Path(sys.argv[1]).write_text({retro()!r})\n",
        encoding="utf-8",
    )
    command = shlex.join([sys.executable, str(agent), str(home / "RETRO.md")])
    if via_file:
        command += " {prompt_file}"
    assert cr.main(["--root", str(tmp_path), "close", "one", "--reviewer-cmd", command]) == 0


def test_reviewer_that_writes_nothing_fails(tmp_path):
    cr.start(tmp_path, "one")
    finish(tmp_path, "one")
    command = shlex.join([sys.executable, "-c", "pass"])
    assert cr.main(["--root", str(tmp_path), "close", "one", "--reviewer-cmd", command]) == 1


def test_committed_campaigns_owe_no_review():
    assert cr.owed(_ROOT) == []
