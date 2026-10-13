---
name: github-issues
description: Use when the user asks to see, list, triage, fix, comment on, or close GitHub issues for the pootle/local-ai-hanoi repo. Covers the full workflow from listing open issues through commenting and closing with the fixing commit hash.
---

# GitHub issues workflow (pootle/local-ai-hanoi)

Hard rules (duplicated in AGENTS.md):

- When asked for open issues, list number + title (+ date) only, then stop
  and wait for the user to pick. Do not fetch bodies or investigate code
  before the pick.
- Never comment on or close an issue before the fix is committed AND pushed.
- Every issue comment cites the commit hash (short form) that fixes it.
- `gh issue view` is broken on this repo (classic-projects GraphQL bug).
  Read and comment via `gh api` (REST). Closing via REST PUT 404s too —
  use `gh issue close <n>`.

## 1. List

```
gh issue list --state open --limit 50
```

Present as `#<number>  <title>` lines (newest first). Stop and wait.

## 2. Read the picked issue

```
gh api repos/pootle/local-ai-hanoi/issues/<n>
```

Then explore the code and present a plan for approval before implementing.

## 3. Implement

- Follow existing codebase conventions; stdlib only, no new dependencies.
- When behavior changes, add or extend tests; a regression test must fail
  without the fix.

## 4. Verify

```
python3 test_hanoi.py && python3 test_hanoi_web.py
```

Plus any UI-level check the change requires.

## 5. Commit and push (only on the user's instruction)

- One commit per issue; reference it in the subject, e.g.
  `Fix replaying stale moves after a manual move (#1)`.
- Show the proposed commit message(s) first; push when told.

## 6. Comment and close (only after push, on the user's go-ahead)

Draft the comment for the user to review first. Shape:

```
Fixed in <short-hash> — <one-line description of the fix>.
<optional second line: tests added / behaviour notes>
```

Post the comment via the REST API, then close with the CLI:

```
gh api -X POST repos/pootle/local-ai-hanoi/issues/<n>/comments -f body="<comment>"
gh issue close <n>
```
