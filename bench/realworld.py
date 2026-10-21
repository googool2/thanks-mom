#!/usr/bin/env python3
"""Run Thanks Mom on COPIES of real projects and check, mechanically, that nothing is lost.

  python bench/realworld.py WORKDIR OUT.json PROJECT_DIR [PROJECT_DIR ...]

Per project: copy (skipping .claude/worktrees) -> scan -> apply with no answers (every 'ask' is kept)
-> account for every original file -> undo -> check every file is back -> delete the copy.
OUT.json holds file names, so keep it private; only aggregate numbers belong in the repo.
"""
import hashlib, json, os, shutil, stat, subprocess, sys, time, zipfile
from pathlib import Path

MOM = Path(__file__).resolve().parent.parent / "skills" / "thanks-mom" / "scripts" / "mom.py"


def copy(src, dst):
    if os.name == "nt":  # robocopy is far faster than copytree on node_modules-sized trees
        r = subprocess.run(["robocopy", str(src), str(dst), "/E", "/MT:16", "/R:1", "/W:1", "/NFL", "/NDL", "/NP", "/NJH", "/NJS",
                            "/XD", str(Path(src) / ".claude" / "worktrees")], capture_output=True, text=True)
        if r.returncode >= 8:
            raise RuntimeError(f"robocopy failed ({r.returncode}): {r.stdout[-500:]}")
    else:
        shutil.copytree(src, dst, symlinks=True, ignore=lambda d, n: ["worktrees"] if Path(d).name == ".claude" else [])


def walk(root):
    """{rel: (size, mtime_ns)} for every file, skipping .git and our own .mom/."""
    out = {}
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in (".git", ".mom")]
        for f in fns:
            p = os.path.join(dp, f)
            try:
                st = os.lstat(p)
            except OSError:
                continue
            out[os.path.relpath(p, root).replace("\\", "/")] = (st.st_size, st.st_mtime_ns)
    return out


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def under(rel, paths):
    return any(rel == p or rel.startswith(p + "/") for p in paths)


def git(root, *args):
    r = subprocess.run(["git", "-c", "core.quotepath=off", *args], cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.stdout


def mom(*args):
    t = time.perf_counter()
    r = subprocess.run([sys.executable, str(MOM), *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r, time.perf_counter() - t


def rmtree(p):
    def force(func, path, *_):
        os.chmod(path, stat.S_IWRITE)
        func(path)
    shutil.rmtree(p, **({"onexc": force} if sys.version_info >= (3, 12) else {"onerror": force}))


def run_one(src, work):
    rec = {"source": str(src), "ok": False}
    dst = work / src.name
    if dst.exists():
        rmtree(dst)
    t = time.perf_counter()
    copy(src, dst)
    rec["copy_s"] = round(time.perf_counter() - t, 1)
    is_git = (dst / ".git").exists()
    try:
        r, rec["scan_s"] = mom("scan", str(dst))
        if r.returncode:
            rec["error"] = "scan: " + r.stderr[-800:]
            return rec
        plan = json.loads((dst / ".mom" / "plan.json").read_text(encoding="utf-8"))
        rec["plan"] = plan["items"]
        rec["similar"] = plan["similar"]
        rec["scan_summary"] = r.stdout
        before = walk(dst)
        rec["before"] = {"files": len(before), "size": sum(s for s, _ in before.values()),
                         "root_items": len([x for x in os.listdir(dst) if x != ".mom"])}
        touched = [i["path"] for i in plan["items"] if i["action"] in ("archive", "move")]
        hashes = {rel: sha(dst / rel) for rel in before if under(rel, touched) or rel == ".gitignore"}
        status0 = git(dst, "status", "--porcelain") if is_git else None

        r, rec["apply_s"] = mom("apply", str(dst))  # no answers: every 'ask' stays
        if r.returncode:
            rec["error"] = "apply: " + (r.stdout + r.stderr)[-800:]
            return rec
        rec["apply_out"] = r.stdout
        after = walk(dst)
        rec["after"] = {"files": len(after), "size": sum(s for s, _ in after.values()),
                        "root_items": len([x for x in os.listdir(dst) if x != ".mom"])}
        man_path = next((dst / ".mom").glob("archive-*.json"))
        man = json.loads(man_path.read_text(encoding="utf-8"))
        zpath = man_path.with_suffix(".zip")
        zipped = {}
        if zpath.exists():
            with zipfile.ZipFile(zpath) as z:
                zipped = {n: hashlib.sha256(z.read(n)).hexdigest() for n in z.namelist()}
        rec["zip_size"] = zpath.stat().st_size if zpath.exists() else 0
        moved = dict(man["moved"])
        deleted = [d["path"] for d in man["deleted"]]
        # 1. every original file is accounted for
        lost = []
        for rel, (size, _) in before.items():
            if rel in moved:
                ok = (dst / moved[rel]).exists() and sha(dst / moved[rel]) == hashes[rel]
            elif rel in zipped:
                ok = zipped[rel] == hashes[rel]
            elif under(rel, deleted):
                ok = True  # regenerable or OS junk, removed by design
            elif rel == ".gitignore":
                ok = (dst / rel).exists()  # appended to; checked byte-for-byte after undo
            else:
                ok = rel in after and after[rel][0] == size
            if not ok:
                lost.append(rel)
        rec["lost_after_apply"] = lost
        # 2. no gitignored file became visible
        exposed = []
        if is_git and moved:
            def ign(paths):
                out = subprocess.run(["git", "-c", "core.quotepath=off", "check-ignore", "--no-index", "--stdin"], cwd=dst,
                                     input="\n".join(paths), capture_output=True, text=True, encoding="utf-8").stdout
                return set(out.splitlines())
            was, now = ign(list(moved)), ign(list(moved.values()))
            exposed = [s for s, d in moved.items() if s in was and d not in now]
        rec["exposed"] = exposed
        # 3. undo puts everything back
        r, _ = mom("undo", str(dst))
        if r.returncode:
            rec["error"] = "undo: " + (r.stdout + r.stderr)[-800:]
            return rec
        back = walk(dst)
        not_back = []
        for rel, (size, _) in before.items():
            if under(rel, deleted):
                continue
            if rel not in back or back[rel][0] != size or (rel in hashes and sha(dst / rel) != hashes[rel]):
                not_back.append(rel)
        rec["not_restored"] = not_back
        rec["restored_files"] = len([r for r in before if not under(r, deleted)]) - len(not_back)
        if is_git:
            status2 = git(dst, "status", "--porcelain")
            rec["git_status_identical"] = sorted(status0.splitlines()) == sorted(status2.splitlines())
        rec["ok"] = not lost and not exposed and not not_back and rec.get("git_status_identical", True)
        return rec
    finally:
        rmtree(dst)


def main():
    work, out = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    work.mkdir(parents=True, exist_ok=True)
    results = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
    for src in map(Path, sys.argv[3:]):
        if src.name in results and results[src.name].get("ok") is not None and "--redo" not in sys.argv:
            continue
        print(f"== {src.name}", flush=True)
        try:
            rec = run_one(src.resolve(), work)
        except Exception as e:  # keep going; one broken project shouldn't stop the run
            rec = {"source": str(src), "ok": False, "error": repr(e)}
        results[src.name] = rec
        out.write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"   ok={rec['ok']} lost={len(rec.get('lost_after_apply', []))} not_restored={len(rec.get('not_restored', []))} "
              f"exposed={len(rec.get('exposed', []))} git_same={rec.get('git_status_identical')} "
              f"scan={rec.get('scan_s', 0):.1f}s {rec.get('error', '')[:200]}", flush=True)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
