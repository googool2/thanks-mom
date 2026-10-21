# Changelog

Versions follow [Semantic Versioning](https://semver.org/):

- **Major** (2.0.0): anything that could change what gets removed or moved for the same project: a looser safety rule, a different `plan.json` / `apply` interface.
- **Minor** (1.1.0): new rules, new questions, new commands. Existing behavior stays as safe or gets safer.
- **Patch** (1.0.1): bug fixes and wording.

`python skills/thanks-mom/scripts/mom.py --version` prints the installed version.

## [1.2.0] - 2026-10-21

New:
- **Install as a Claude Code plugin:** `/plugin marketplace add googool2/thanks-mom`. The skill moved to `skills/thanks-mom/`.
- **`mom.py worktrees ROOT`** lists every git worktree with its size, unsaved changes and commits not yet in the main branch, and prints `git worktree remove` commands for the safe ones only. It is read-only.
- **`mom.py report DIR`** gives a read-only overview of every project under a folder: size, how much is rebuildable, how much is worktrees, and last change.
- **`mom.py prune ROOT [--days 30]`** deletes old safety zips. The scan reminds you when old ones pile up.
- `bench/agent_eval.py` measures, with headless Claude Code, whether a cleaned project with `PROJECT_MAP.md` helps an agent find code.

Fixed:
- The benchmark no longer reports "recursive file listing tokens". Claude Code's own search already skips gitignored folders, so that number overstated the gain.

## [1.1.1] - 2026-10-21

- The scan summary also groups duplicate questions and "something still uses it" questions into one line each, instead of one line per file.
- README rewritten. Real-project results are shown as totals only.

## [1.1.0] - 2026-10-21

Found by running 1.0.0 on copies of real-world projects (six project types) and reviewing every automatic decision by hand.
1.0.0 lost nothing (every file was accounted for and `undo` restored all of them), but 972 of its 8,446 automatic decisions were wrong.

Safer:
- **Duplicates are never boxed up on their own.** Identical files were often deliberate: experiment outputs, a second copy of a project folder, app resources, files inside a packaged app. Duplicates of 1 MB or more become a question; smaller ones are ignored.
- **Unprovable build folders are left alone.** `dist/`, `build/`, `out/`, `release/` and `bin/` without a known build script are not looked into: one was a packaged app.
- **The reference check reads more and matches names without extensions.** It now reads `.tex`, `.bib`, notebooks, Java, Kotlin, Go, PHP, Ruby, C# and more, so `\includegraphics{fig}` keeps `fig.pdf` in place.
- **Copy names are stricter.** `Smith (2019).pdf` is not a copy, and `copy.js` is not throwaway.
- **Browser profiles are one item.** A headless Chrome or Edge `--user-data-dir` becomes one question instead of thousands of actions, and LevelDB's `000003.log` is no longer treated as a log.
- **Loose docs move only in code projects**, and more than 10 at once become one question.
- **Being listed is not being used.** Mentions in `.gitignore`-style files and in `PROJECT_MAP.md` no longer count as references.

New:
- Regenerable `vendor/` (Composer, with a lockfile), Gradle `build/` and CocoaPods `Pods/`.
- The scan summary groups same-reason questions into one line with an id range.
- `apply` takes ranges (`--archive 4-30`) and `--move` to approve suggested moves.
- `bench/realworld.py` reruns this test on any folder of projects, and `bench/test_rules.py` locks the naming rules in CI.

Faster: the reference index only tracks the names it looks for (one 1,500-file project: 7.6 s to 1.8 s).

## [1.0.0] - 2026-10-21

First public release.

- `mom.py scan | apply | undo | map`, stdlib only, Python 3.10+.
- Deletes only what is provably regenerable: `node_modules` next to a lockfile, a `.venv` after its package list is saved to `requirements.freeze.txt`, caches, and `dist/` when a build script exists.
- Boxes leftovers into a verified zip in `.mom/`. `undo` restores them byte-for-byte, puts moves back and restores `.gitignore`.
- Asks before touching anything uncertain. An undecided item is kept.
- Spots near-identical one-off scripts so the agent can merge them into one tool in `tools/`.
- Writes `PROJECT_MAP.md` plus a short pointer block in `CLAUDE.md`.
- Safety rules learned on real projects:
  - App data folders (`data/`, `storage/`, `uploads/`, ...) are never boxed up automatically, and UUID- or hash-named files are never treated as duplicates.
  - `report (1).pdf` is boxed up only if it is byte-identical to `report.pdf`.
  - A move never makes a gitignored file visible to git.
  - Git worktrees, submodules and nested repos are reported, never touched.
  - Empty folders are left alone.
- Benchmark (`bench/bench.py`) with real `npm` and `pip` installs and seven traps, plus README charts (`bench/charts.py`).
