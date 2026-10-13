# hanoi-local

Towers of Hanoi solver: `hanoi.py` (CLI/file solver) and `hanoi_web.py`
(same engine plus a local web UI with an animated board). Python 3 stdlib
only — no new dependencies.

## Commands

- Tests (plain asserts, no pytest): `python3 test_hanoi.py && python3 test_hanoi_web.py`
- Web UI: `python3 hanoi_web.py [port]` (default 8733)

## GitHub

- `gh` is authenticated for this repo (fine-grained token, issues: read/write).
- `gh issue view` is broken on this repo (classic-projects GraphQL bug).
  Use `gh api repos/pootle/local-ai-hanoi/issues/<n>` for issue bodies and
  other issue REST calls.
- When asked for open issues: list number + title (+ date) and wait for the
  user to pick one. Do not fetch bodies or investigate code before the pick.
- Never comment on or close an issue before the fix is committed AND pushed.
  Every issue comment must cite the commit hash that fixes the issue.
- For the full issue workflow (list → pick → read → plan → implement →
  verify → commit/push → comment + close), load the `github-issues` skill.
