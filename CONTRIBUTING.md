# Contributing

Thanks for helping. The most useful contribution is a report of a **wrong decision**: something mom deleted, boxed up, moved or asked about that she shouldn't have. Use the "Wrong decision" issue form. Every such report becomes a rule and a test.

## Setup

Python 3.10+ and nothing to install. For the full benchmark you also need Node.js and network access.

```bash
python bench/test_rules.py        # naming rules, about a second
python bench/test_commands.py     # worktrees, report and prune on throwaway repos
python bench/bench.py             # full benchmark: real npm/pip installs, traps, undo
python bench/charts.py            # redraw the README charts
```

CI runs all of these on Linux, macOS and Windows, with the oldest and newest supported Python.

## Rules for changes

- **Never loosen a safety rule in a minor or patch release.** If a change could make mom remove or move something she didn't before, it's a major version. Say so in the CHANGELOG.
- **Every fix for a wrong decision comes with a test**, in `bench/test_rules.py` or as a trap in `bench/bench.py`.
- **No real or private data in fixtures.** Use made-up names and generated files.
- **Keep the script stdlib-only** and `SKILL.md` short, because every token of it is loaded on each run.
- Add a line to `CHANGELOG.md` under the next version.

## Pull requests

Keep them small and focused. Run the tests above before opening one, and fill in the PR checklist.
