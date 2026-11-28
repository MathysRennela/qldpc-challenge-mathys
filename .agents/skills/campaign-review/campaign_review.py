#!/usr/bin/env python3
"""Make sure every search campaign ends with a retrospective, in any agent harness.

Standard library only, so any harness (or a person) can run it with python3.

    campaign_review.py start <id>     mark a campaign as owing a review
    campaign_review.py close <id>     record that the run ended, print the reviewer brief
    campaign_review.py brief <id>     print the reviewer brief again
    campaign_review.py check [<id>]   fail if a finished campaign has no valid RETRO.md

Only campaigns marked by ``start`` are tracked; older campaigns are left alone.
This script judges the shape of a retrospective, never whether it is right.
"""

import argparse
import datetime
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent
DEFAULT_ROOT = SKILL_DIR.parents[2]
MARKER = "review.json"
RETRO = "RETRO.md"
SUMMARY = "summary.json"
ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{1,63}")
END_STATUSES = ("completed", "paused", "abandoned", "failed")
MAX_SUGGESTIONS = 3
REVIEWERS = ("fresh-session", "same-session")
FIELDS = ("Evidence", "Expected effect", "Done when", "Already tracked")
# section title -> the bodies allowed instead of suggestions
SUGGESTION_SECTIONS = {
    "Suggestions: qldpc-challenge": ("None.",),
    "Suggestions: code-calculus": ("None.", "Not applicable."),
}


class ReviewError(Exception):
    """A request this script refuses, with the reason as its message."""


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def campaigns_dir(root):
    return Path(root) / "research" / "campaigns"


def campaign_dir(root, campaign_id):
    if not ID_PATTERN.fullmatch(campaign_id):
        raise ReviewError(f"{campaign_id!r} is not a campaign id: use lowercase letters, digits and hyphens")
    return campaigns_dir(root) / campaign_id


def read_marker(home):
    path = home / MARKER
    try:
        marker = json.loads(path.read_text(encoding="utf-8"))
        marker["started"], marker["ended"]
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise ReviewError(f"{path}: unreadable marker ({e!r}); was the campaign started with `start`?") from None
    return marker


def write_marker(home, marker):
    (home / MARKER).write_text(json.dumps(marker, indent=2) + "\n", encoding="utf-8")


def retro_problems(text):
    """Return what is wrong with a RETRO.md, as a list of sentences (empty when valid)."""
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    problems = []
    reviewer = re.search(r"^Reviewer:[ \t]*(\S+)[ \t]*$", text, flags=re.M)
    if not reviewer or reviewer.group(1) not in REVIEWERS:
        problems.append(f"needs a line 'Reviewer: {' | '.join(REVIEWERS)}' naming one of the two")
    parts = re.split(r"^## +(.+?)[ \t]*$", text, flags=re.M)
    sections = {title: body.strip() for title, body in zip(parts[1::2], parts[2::2])}
    if not sections.get("What happened"):
        problems.append("needs a non-empty section '## What happened'")
    for title, empty_bodies in SUGGESTION_SECTIONS.items():
        body = sections.get(title)
        if body is None:
            problems.append(f"needs a section '## {title}'")
            continue
        if body in empty_bodies:
            continue
        chunks = re.split(r"^### +(.+?)[ \t]*$", body, flags=re.M)
        names, bodies = chunks[1::2], chunks[2::2]
        if not names or chunks[0].strip():
            allowed = " or ".join(repr(b) for b in empty_bodies)
            problems.append(f"'{title}' must be {allowed}, or only '### <title>' suggestions")
            continue
        if len(names) > MAX_SUGGESTIONS:
            problems.append(f"'{title}' has {len(names)} suggestions; the limit is {MAX_SUGGESTIONS}")
        for name, suggestion in zip(names, bodies):
            for field in FIELDS:
                found = re.search(rf"^- {field}:(.*(?:\n[ \t]+.*)*)", suggestion, flags=re.M)
                if not found or not found.group(1).strip():
                    problems.append(f"suggestion '{name}' needs a filled '- {field}:' line")
    return problems


def state(home):
    """Return (state, problems): 'running', 'owed' or 'reviewed'."""
    marker = read_marker(home)
    retro = home / RETRO
    if retro.is_file():
        problems = retro_problems(retro.read_text(encoding="utf-8"))
        return ("owed", problems) if problems else ("reviewed", [])
    summary = home / SUMMARY
    started = datetime.datetime.fromisoformat(marker["started"]).timestamp()
    # A summary written since the start means the run ended, whether or not
    # anyone ran `close`. One second of slack covers coarse file timestamps.
    ended = marker["ended"] or (summary.is_file() and summary.stat().st_mtime >= started - 1)
    return ("owed", [f"no {RETRO}"]) if ended else ("running", [])


def tracked(root):
    return sorted(p.parent for p in campaigns_dir(root).glob(f"*/{MARKER}"))


def owed(root, *, besides=None):
    out = []
    for home in tracked(root):
        if home.name != besides:
            status, problems = state(home)
            if status == "owed":
                out.append((home.name, problems))
    return out


def start(root, campaign_id, *, allow_owed=None):
    home = campaign_dir(root, campaign_id)
    waiting = owed(root, besides=campaign_id)
    if waiting and not allow_owed:
        names = ", ".join(name for name, _ in waiting)
        raise ReviewError(
            f"review still owed for: {names}. Run `brief <id>` and write the review, or pass --allow-owed '<reason>'"
        )
    home.mkdir(parents=True, exist_ok=True)
    now = _now()
    retro = home / RETRO
    if retro.exists():
        retro.rename(home / f"RETRO-{now.strftime('%Y%m%dT%H%M%S%fZ')}.md")
    marker = {"campaign_id": campaign_id, "started": now.isoformat(), "ended": None, "end_status": None}
    if waiting:
        marker["started_while_owed"] = {"campaigns": [n for n, _ in waiting], "reason": allow_owed}
    write_marker(home, marker)
    return home


def close(root, campaign_id, *, status="completed"):
    home = campaign_dir(root, campaign_id)
    marker = read_marker(home)
    if status != "failed":
        path = home / SUMMARY
        try:
            summary = json.loads(path.read_text(encoding="utf-8"))
            found = summary["campaign_id"]
        except (OSError, ValueError, KeyError, TypeError) as e:
            raise ReviewError(
                f"{path}: no usable summary ({e!r}). Write it with research/kit/campaign.py "
                "write_summary, or close with --status failed if the run broke"
            ) from None
        if found != campaign_id:
            raise ReviewError(f"{path}: campaign_id is {found!r}, not {campaign_id!r}")
    marker.update(ended=_now().isoformat(), end_status=status)
    write_marker(home, marker)
    return home


def brief(root, campaign_id, *, calculus_root=None):
    home = campaign_dir(root, campaign_id)
    marker = read_marker(home)
    root = Path(root).resolve()
    files = sorted(
        p.relative_to(home).as_posix() for p in home.rglob("*") if p.is_file() and "__pycache__" not in p.parts
    )
    calculus = (
        f"A code-calculus checkout is at: {Path(calculus_root).resolve()}"
        if calculus_root
        else "No code-calculus checkout was given."
    )
    return "\n".join(
        [
            (SKILL_DIR / "REVIEW.md").read_text(encoding="utf-8").rstrip(),
            "",
            "## This campaign",
            "",
            f"- id: {campaign_id}",
            f"- repository root: {root}",
            f"- folder: {home.resolve()}",
            f"- review tracking started: {marker['started']}",
            f"- closed: {marker['ended'] or 'not recorded'} (status: {marker['end_status'] or 'not recorded'})",
            f"- {calculus}",
            f"- write the review to: {(home / RETRO).resolve()}",
            "- check the format with: "
            + shlex.join(["python3", str(SKILL_DIR / "campaign_review.py"), "--root", str(root), "check", campaign_id]),
            "- files in the folder:",
            *[f"  - {name}" for name in files],
            "",
        ]
    )


def run_reviewer(command, text, root):
    """Run a command-line agent on the brief: on stdin, or as a file named by {prompt_file}."""
    argv = shlex.split(command)
    if not argv:
        raise ReviewError("--reviewer-cmd is empty")
    with tempfile.TemporaryDirectory() as tmp:
        prompt = Path(tmp) / "brief.md"
        prompt.write_text(text, encoding="utf-8")
        uses_file = any("{prompt_file}" in a for a in argv)
        argv = [a.replace("{prompt_file}", str(prompt)) for a in argv]
        try:
            done = subprocess.run(argv, cwd=root, input=None if uses_file else text, text=True, check=False)
        except OSError as e:
            raise ReviewError(f"could not run the reviewer: {e}") from None
    if done.returncode:
        raise ReviewError(f"the reviewer exited with status {done.returncode}")


def check(root, campaign_id=None):
    """Print each tracked campaign's state; return 1 if a review is owed."""
    homes = [campaign_dir(root, campaign_id)] if campaign_id else tracked(root)
    failed = False
    for home in homes:
        status, problems = state(home)
        failed = failed or status == "owed"
        print(f"{home.name}: {status}")
        for problem in problems:
            print(f"  - {problem}")
    if not homes:
        print("no campaigns are tracked")
    return 1 if failed else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=DEFAULT_ROOT, help="repository root (default: the one holding this skill)")
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("start")
    p.add_argument("id")
    p.add_argument("--allow-owed", metavar="REASON", help="start although another campaign is unreviewed")
    p = sub.add_parser("close")
    p.add_argument("id")
    p.add_argument("--status", choices=END_STATUSES, default="completed")
    p.add_argument("--reviewer-cmd", help="command-line agent to run on the brief, e.g. for unattended runs")
    p.add_argument("--calculus-root", default=os.environ.get("CODE_CALCULUS_ROOT"))
    p = sub.add_parser("brief")
    p.add_argument("id")
    p.add_argument("--calculus-root", default=os.environ.get("CODE_CALCULUS_ROOT"))
    p = sub.add_parser("check")
    p.add_argument("id", nargs="?")
    args = ap.parse_args(argv)
    try:
        if args.command == "start":
            home = start(args.root, args.id, allow_owed=args.allow_owed)
            print(f"started: {home}")
        elif args.command == "close":
            close(args.root, args.id, status=args.status)
            text = brief(args.root, args.id, calculus_root=args.calculus_root)
            if not args.reviewer_cmd:
                print(text)
                return 0
            run_reviewer(args.reviewer_cmd, text, args.root)
            return check(args.root, args.id)
        elif args.command == "brief":
            print(brief(args.root, args.id, calculus_root=args.calculus_root))
        else:
            return check(args.root, args.id)
    except ReviewError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
