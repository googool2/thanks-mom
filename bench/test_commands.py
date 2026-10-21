#!/usr/bin/env python3
"""Checks for `worktrees`, `report` and `prune` on throwaway folders. Needs git, no network.

  python bench/test_commands.py
"""
import os, subprocess, sys, tempfile, time
from pathlib import Path

MOM = Path(__file__).resolve().parent.parent / "skills" / "thanks-mom" / "scripts" / "mom.py"


def run(cwd, *args):
    subprocess.run(args, cwd=cwd, check=True, capture_output=True)


def mom(*args):
    r = subprocess.run([sys.executable, str(MOM), *args], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    repo = tmp / "app"
    repo.mkdir()
    run(repo, "git", "init", "-q", "-b", "main")
    run(repo, "git", "config", "user.email", "t@example.com")
    run(repo, "git", "config", "user.name", "t")
    (repo / "package.json").write_text("{}")
    run(repo, "git", "add", ".")
    run(repo, "git", "commit", "-q", "-m", "init")
    for name in ("merged", "dirty", "ahead"):
        run(repo, "git", "worktree", "add", "-q", "-b", name, str(tmp / "wt" / name))
    (tmp / "wt" / "dirty" / "notes.txt").write_text("unsaved")
    (tmp / "wt" / "ahead" / "feature.txt").write_text("x")
    run(tmp / "wt" / "ahead", "git", "add", ".")
    run(tmp / "wt" / "ahead", "git", "commit", "-q", "-m", "feature")

    out = mom("worktrees", str(repo))
    line = {n: next(ln for ln in out.splitlines() if f"[{n}," in ln) for n in ("merged", "dirty", "ahead")}
    assert "safe to remove" in line["merged"], out
    assert "uncommitted" in line["dirty"], out
    assert "not in main" in line["ahead"], out
    assert out.count("git worktree remove") == 1, out  # only the safe one gets a command

    # report: a project with rebuildable deps is listed with them, a plain folder is skipped
    (repo / "node_modules" / "x").mkdir(parents=True)
    (repo / "node_modules" / "x" / "index.js").write_text("y" * 5000)
    (repo / "package-lock.json").write_text("{}")
    (tmp / "photos").mkdir()
    out = mom("report", str(tmp))
    assert "app" in out and "photos" not in out, out
    assert "4.9 KB" in out.splitlines()[2], out  # node_modules counted as rebuildable

    # prune: only archives older than --days go
    state = repo / ".mom"
    state.mkdir()
    old, new = state / "archive-20200101-000000.zip", state / "archive-20990101-000000.zip"
    old.write_bytes(b"x")
    new.write_bytes(b"x")
    os.utime(old, (time.time() - 40 * 86400,) * 2)
    mom("prune", str(repo), "--days", "30")
    assert not old.exists() and new.exists()

print("commands ok")
