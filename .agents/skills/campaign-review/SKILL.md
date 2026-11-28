---
name: campaign-review
description: Run a search campaign under research/campaigns/ and finish it with a retrospective that suggests improvements to qldpc-challenge and, when used, the code calculus. Use when launching, resuming, ending or reviewing a campaign.
---

# Campaign review

Every campaign ends with `RETRO.md`: what happened, and what would make the
next run better. The script beside this file keeps track of which campaigns
still owe one. Run every command from the repository root.

This adds a closing step to a campaign. The campaign contract
(`research/campaigns/README.md`) and the rules in `AGENTS.md` and
`research/AUTORESEARCH.md` apply unchanged.

## 1. Start

```sh
python3 .agents/skills/campaign-review/campaign_review.py start <id>
```

`<id>` is the folder name under `research/campaigns/`. Do this before the run,
then write `campaign.json` with its direction card as the campaign README
describes. If the script reports a review still owed, write that review first.
`--allow-owed '<reason>'` skips it and records why.

## 2. Run

Keep what a reviewer will need inside the campaign folder: the runner script,
logs and result files. End the run by writing `summary.json` with
`write_summary` from `research/kit/campaign.py`, including negative results and
errors.

## 3. Close

```sh
python3 .agents/skills/campaign-review/campaign_review.py close <id>
```

Add `--status abandoned` or `--status paused` when that is what happened. If the
run broke before it could write a summary, use `--status failed`; a failed run
is reviewed too. Add `--calculus-root <path>` (or set `CODE_CALCULUS_ROOT`) when
a code-calculus checkout is available.

## 4. Review

`close` prints the reviewer brief. Give it to a reviewer with a fresh context:

- If your harness can start a subagent, pass it the printed brief and nothing
  else. Do not add your own account of how the run went.
- Otherwise, ask the user to open a new session with the brief.
- If neither is possible, review it yourself and write `Reviewer: same-session`.

For unattended runs, `close` can launch the reviewer itself:

```sh
python3 .agents/skills/campaign-review/campaign_review.py close <id> --reviewer-cmd "claude -p"
```

The command receives the brief on standard input, or as a file where the command
contains `{prompt_file}`. It needs permission to write `RETRO.md`; how to grant
that depends on the agent.

## 5. Check and report

```sh
python3 .agents/skills/campaign-review/campaign_review.py check <id>
```

Fix what it reports, then show the user the suggestions. Filing an issue or
opening a pull request is the user's decision.
