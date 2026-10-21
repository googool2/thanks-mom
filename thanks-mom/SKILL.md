---
name: thanks-mom
description: Tidies a messy project folder without breaking anything. Deletes regenerable bloat (node_modules, .venv, caches), boxes agent leftovers (tmp scripts, *_old files, logs, duplicates, screenshots) into a recoverable zip, asks the user about anything uncertain, merges repeated one-off scripts into one reusable tool, and writes PROJECT_MAP.md so agents can find files after a context reset. Use when the user says "thanks mom", "clean up / tidy / organize this project", "shrink this folder", "this repo is a mess", or asks for a project map.
---

# Thanks Mom

Mom cleans your room but never throws out anything you might still need. Every step can be undone.

`MOM` below means `python <this skill's folder>/scripts/mom.py` (try `python3` if `python` is missing). Stdlib only, no installs.

## Rules
- Never delete files by hand. Every removal goes through `MOM apply`, which zips and verifies before it removes anything.
- Never touch `.git`, `.env*`, lockfiles, manifests, README/LICENSE, CLAUDE.md, `.claude/`, `.github/`, `tools/`. mom.py already protects them, so don't work around it.
- Unsure about something? Ask. An item with no decision stays.
- Save tokens: don't `cat .mom/plan.json` (the scan summary is enough), and don't open files to classify them. Names, sizes and mom.py's reference check are the signal.

## Steps
1. **Baseline.** In a git repo run `git status --short`. If there are uncommitted changes, ask the user to commit first (offer to do it). Find the test or build command (package.json `scripts.test`, pytest, Makefile...), run it once and note pass or fail. If there are no tests, say so; step 6 is then skipped.
2. **Scan.** `MOM scan .` and read the summary.
3. **Mom asks.** Ask about every `ASK` item with AskUserQuestion. Put up to 4 questions in one call, and fold same-kind items into one question ("these 5 scripts at the root?"). Options: **Keep it** / **Box it up** (archive, can come back) / **Throw it out** (delete). The summary already groups same-reason items into one line with an id range (`ids 4-30`): ask once per line, not per file. Also mention any delete or archive item over ~100 MB so nothing big disappears quietly.
   - Write the questions in English, even if the conversation is in another language, unless the user asks otherwise. People share this skill.
   - Tone: calm and considerate, like a sensible parent, not a cute one. No pet names, no baby talk, no jokes. Give the facts first (what it is, size, days since last change, whether anything references it), then one plain question: "`output/`: 129 KB, unchanged for 40 days, nothing references it. Still need it?"
   - Also look at the root yourself. Versioned notebooks (`*_v1.ipynb`), old copies (`*.updated.xlsx`), report or export folders: grep for references first, then ask. If the user wants something the scan didn't flag boxed up, use `--archive-path PATH`.
4. **Merge repeated one-off scripts.** Do this only when the summary shows `similar scripts S#`:
   - Read at most 2 files of the group. They're near-copies, so more is wasted tokens.
   - Write one parameterised tool, `tools/<verb>_<noun>.py` (argparse, path as argument), that covers the whole group. Keep it under ~80 lines, and run it once on a real input to prove it works.
   - Add the group's ids to `--archive` in step 5.
   - Skip the group if the files only look alike but do different jobs.
5. **Apply.** `MOM apply . --archive <ids> --delete <ids> --keep <ids> --move <ids> [--archive-path PATH ...]`, using the answers from steps 3 and 4. Ids accept ranges (`4-30`). `--move` approves suggested moves that were asked about (more than 10 loose docs at once become one question).
6. **Reorganise code (optional).** Only when git was clean and step 1 had a passing test command. Move source into a standard layout ([references/layouts.md](references/layouts.md)), update imports and paths (grep for every old path, including package.json, Dockerfile and CI), then re-run the tests. If they fail, revert with git and report. For quick vibe-coded projects, skip this step: the cleanup already did the work.
7. **Verify.** Re-run the step 1 command and compare. If deleted deps are needed for that, restore them first (`npm ci`, or a venv from `requirements.freeze.txt`). If anything got worse, run `MOM undo .` and tell the user.
8. **Map.** Run `MOM map .` and write `PROJECT_MAP.md`: the tree with a one-line purpose per folder, 60 lines max. List files only at the root and for key entry points. Add "where to find X" lines (entry point, tests, config) and one line per tool in `tools/` (`tools/read_doc.py PATH`: text of pdf/docx/xlsx/csv). Then make sure CLAUDE.md (create it if missing) has this block and nothing more from you:
   ```
   ## Project map & house rules
   - Read PROJECT_MAP.md before searching for files.
   - Reusable helpers live in tools/ (listed in PROJECT_MAP.md). Use or extend one before writing a new script.
   - Throwaway scripts go in .scratch/ (gitignored), never the project root.
   ```
   Use a pointer, not `@PROJECT_MAP.md`. That costs ~60 tokens per session instead of the whole map, and it survives context compaction because CLAUDE.md is reloaded.
9. **Report** in one short table: size, file count and root items, before and after; what was deleted, boxed up and moved; where the zip is. End with: undo = `MOM undo .`, deps come back with the commands mom.py printed, and `.mom/` can be deleted once the user is happy.
