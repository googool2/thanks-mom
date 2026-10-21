#!/usr/bin/env python3
"""Thanks Mom: tidy a project folder without losing anything.

  mom.py scan  ROOT                     classify everything -> ROOT/.mom/plan.json + short summary
  mom.py apply ROOT [--keep IDS] [--archive IDS] [--delete IDS] [--move IDS] [--archive-path PATH ...]
                                        run the plan. Undecided 'ask' items are KEPT.
  mom.py undo  ROOT [ZIP]               put back everything the last (or given) run archived or moved
  mom.py map   ROOT                     compact folder tree for PROJECT_MAP.md

Stdlib only. Nothing is removed until the archive zip is written and verified.
IDS = comma separated plan ids or ranges, e.g. --archive 3,7,10-14
"""
import argparse, datetime, difflib, hashlib, json, os, re, shutil, stat, subprocess, sys, time, zipfile
from pathlib import Path

__version__ = "1.1.1"

STATE = ".mom"
VCS = {".git", ".hg", ".svn", STATE}
PROTECTED_DIRS = {".claude", ".github", ".gitlab", ".vscode", ".idea", ".devcontainer", ".husky", "tools"}
PROTECTED = re.compile(
    r"^(\.env.*|\.git\w*|\.npmrc|\.nvmrc|\.python-version|\.editorconfig|\.prettierrc.*|\.eslintrc.*|"
    r"README.*|LICENSE.*|COPYING.*|CHANGELOG.*|CONTRIBUTING.*|CODE_OF_CONDUCT.*|SECURITY.*|"
    r"CLAUDE\.md|AGENTS\.md|GEMINI\.md|PROJECT_MAP\.md|"
    r"package\.json|package-lock\.json|yarn\.lock|pnpm-lock\.yaml|pnpm-workspace\.yaml|bun\.lockb?|"
    r"requirements.*\.txt|pyproject\.toml|poetry\.lock|uv\.lock|Pipfile(\.lock)?|setup\.(py|cfg)|"
    r"Cargo\.(toml|lock)|go\.(mod|sum)|Gemfile(\.lock)?|composer\.(json|lock)|"
    r"Dockerfile.*|docker-compose.*|compose\.ya?ml|Makefile|Procfile|.*\.config\.(js|ts|mjs|cjs)|tsconfig.*\.json)$", re.I)

LOCKS = ("package-lock.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb", "bun.lock")
CACHE_DIRS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox", ".nox", ".parcel-cache",
              ".turbo", ".next", ".nuxt", ".svelte-kit", ".angular", ".vite", "coverage", "htmlcov", ".gradle"}
ASK_DIRS = {"tmp", "temp", "old", "backup", "backups", "bak", "archive", "archived", "scratch", "playground",
            "sandbox", "junk", "trash", "misc", "output", "outputs", "test_output", "test_outputs",
            "screenshots", "logs", "debug", "deprecated", "unused"}
DELETE_FILES = re.compile(r"^(\.DS_Store|Thumbs\.db|desktop\.ini|\.eslintcache|.*\.py[co]|.*\.sw[op]|.*~)$", re.I)
ARCHIVE_FILES = re.compile(r"^(.*\.(log|tmp|temp|bak|orig|rej)|npm-debug\.log.*|yarn-error\.log.*)$", re.I)
# Stems agents leave behind. HARD = clearly throwaway, SOFT = maybe (only checked at the project root).
HARD = re.compile(r"(^|[_\-. ])(tmp|temp|scratch|old|backup|bak|untitled)([_\-. ]|\d|$)", re.I)
# "x (1).pdf", "x copy.png", "x-copy-2.js", "x - Copy (3).docx". Not "Smith (2019).pdf", not "copy.js".
COPY = re.compile(r"( \(\d{1,2}\)|[ _-]copy([ _-]?\d{1,2})?| - Copy( \(\d{1,2}\))?)$", re.I)
SOFT = re.compile(r"(^|[_\-. ])(final|new|fixed|test|try|check|quick|debug)([_\-. ]|\d|$)", re.I)
CODE = {".py", ".js", ".ts", ".mjs", ".cjs", ".jsx", ".tsx", ".sh", ".ps1", ".bat"}
TEXT = CODE | {"", ".json", ".jsonc", ".md", ".mdx", ".txt", ".rst", ".adoc", ".html", ".css", ".scss", ".yml", ".yaml",
               ".toml", ".cfg", ".ini", ".conf", ".properties", ".env", ".xml", ".plist", ".vue", ".svelte", ".astro",
               ".tex", ".bib", ".ipynb", ".r", ".rmd", ".sql", ".java", ".kt", ".kts", ".gradle", ".go", ".rs", ".php",
               ".rb", ".cs", ".csproj", ".swift", ".dart", ".lua", ".cmd", ".ejs", ".hbs", ".njk"}
MANIFESTS = ("package.json", "pyproject.toml", "requirements.txt", "setup.py", "Cargo.toml", "go.mod", "pom.xml",
             "build.gradle", "build.gradle.kts", "composer.json", "Gemfile", "CMakeLists.txt", "Makefile", ".git")
MANY_MOVES = 10
TOKEN = re.compile(r"[\w-]+(?:\.[\w-]+)*")
DOCS = {".md", ".txt", ".pdf", ".docx", ".rtf"}
IMAGES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
BIG = 50 * 2**20
# App data lives here, referenced from databases, not from code text, so the reference check is blind.
# Inside these folders mom never boxes anything up on her own; at most she asks.
DATA_DIRS = {"data", "storage", "uploads", "upload", "media", "attachments", "fixtures", "db", "database", "datasets"}
ID_NAME = re.compile(r"^([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[0-9a-f]{16,})$", re.I)


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def dir_stats(d):
    """(bytes, files) under d. scandir reuses the directory listing's stat data, so it stays fast on huge node_modules."""
    size = count = 0
    stack = [str(d)]
    while stack:
        try:
            with os.scandir(stack.pop()) as it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            stack.append(e.path)
                        else:
                            size += e.stat(follow_symlinks=False).st_size
                            count += 1
                    except OSError:
                        pass
        except OSError:
            pass
    return size, count


def checkout_kind(d):
    """'git worktree' / 'git submodule' / 'nested git repo' if d is its own checkout, else None."""
    g = d / ".git"
    if g.is_dir():
        return "nested git repo"
    if g.is_file():
        return "git worktree" if "/worktrees/" in g.read_text(errors="ignore").replace("\\", "/") else "git submodule"
    return None


def regen(d):
    """(action, reason, restore) for a regenerable folder, else None."""
    if d.is_symlink():
        return None
    n, p = d.name, d.parent
    if (d / "pyvenv.cfg").exists():
        return ("delete", "Python virtualenv (package list saved first)", f"python -m venv {n} && pip install -r requirements.freeze.txt")
    if n == "node_modules":
        if (p / "package.json").exists() and any((p / lock).exists() for lock in LOCKS):
            return ("delete", "npm packages (lockfile present)", "npm ci")
        return ("ask", "node_modules WITHOUT a lockfile: reinstall may give different versions", None)
    if n in CACHE_DIRS or n.endswith(".egg-info"):
        return ("delete", "cache / generated output", "recreated automatically")
    if n in ("dist", "build") and (p / "package.json").exists() and '"build"' in (p / "package.json").read_text(errors="ignore"):
        return ("delete", "build output (package.json has a build script)", "npm run build")
    if n == "target" and (p / "Cargo.toml").exists():
        return ("delete", "cargo build output", "cargo build")
    if n == "build" and ((p / "build.gradle").exists() or (p / "build.gradle.kts").exists()):
        return ("delete", "Gradle build output", "./gradlew build")
    if n == "vendor" and (p / "composer.json").exists():
        if (p / "composer.lock").exists():
            return ("delete", "Composer packages (lockfile present)", "composer install")
        return ("skip", "", None)  # PHP deps without a lockfile: not ours to judge, don't look inside
    if n == "Pods" and (p / "Podfile.lock").exists():
        return ("delete", "CocoaPods packages (lockfile present)", "pod install")
    if n in ("dist", "build", "out", "release", "bin"):
        return ("skip", "", None)  # could be a shipped app (a PyInstaller bundle, say): unprovable, so don't look inside
    return None


def spans(nums):
    """[3,4,5,9] -> '3-5,9' (the same form --archive / --move accept)."""
    out, nums = [], sorted(nums)
    for n in nums:
        if out and n == out[-1][1] + 1:
            out[-1][1] = n
        else:
            out.append([n, n])
    return ",".join(f"{a}-{b}" if a != b else f"{a}" for a, b in out)


def is_test_path(rel):
    return any(part.lower() in ("test", "tests", "__tests__", "spec", "specs") for part in Path(rel).parts[:-1])


# ---------------------------------------------------------------- scan
def scan(root):
    now = time.time()
    files, items, protected_files = {}, [], set()

    def add(path, kind, action, reason, size, mtime, **extra):
        items.append(dict(id=len(items) + 1, path=path, kind=kind, action=action, reason=reason,
                          size=size, age_days=int((now - mtime) / 86400), **extra))

    total = count_all = 0
    for dp, dns, fns in os.walk(root):
        d = Path(dp)
        rel_d = d.relative_to(root).as_posix()
        guarded = any(part in PROTECTED_DIRS for part in Path(rel_d).parts)
        # Empty folders are left alone on purpose: they free 0 bytes and are often an app's output target.
        for name in sorted(dns):
            sub = d / name
            rel = (sub.relative_to(root)).as_posix()
            if name in VCS:
                dns.remove(name)
                continue
            co = checkout_kind(sub)
            r = None if co or name in PROTECTED_DIRS else regen(sub)
            if not co and not r and (sub / "Local State").is_file():  # a Chrome/Edge --user-data-dir left by headless rendering
                r = ("ask", "headless browser profile (cache from rendering pages; recreated on the next run)", None)
            hit = co or r or ((name.lower() in ASK_DIRS or HARD.search(name)) and not guarded and name not in PROTECTED_DIRS)
            if not hit:
                continue
            dns.remove(name)  # one decision for the whole folder; don't descend
            size, count = dir_stats(sub)
            total += size
            count_all += count
            mtime = sub.stat().st_mtime
            if co:  # another checkout: never ours to clean, but worth knowing about
                hint = " Remove with `git worktree remove` after checking it has no unsaved work." if co == "git worktree" else ""
                add(rel, "dir", "info", f"{co}, a separate checkout; mom won't touch it.{hint}", size, mtime, files=count)
            elif guarded or (r and r[0] == "skip"):
                pass  # e.g. node_modules inside .claude/, vendor/ without a lockfile: counted, never touched
            elif r:
                add(rel, "dir", r[0], r[1], size, mtime, files=count, restore=r[2])
            elif count == 0:
                pass  # empty: nothing to gain
            else:
                add(rel, "dir", "ask", f"looks like a leftover folder ({count} files)", size, mtime, files=count)
        for name in fns:
            f = d / name
            rel = f.relative_to(root).as_posix()
            try:
                st = f.lstat()
            except OSError:
                continue
            total += st.st_size
            if guarded or PROTECTED.match(name):
                protected_files.add(rel)
            files[rel] = st

    # --- per-file rules
    is_project = any((Path(root) / m).exists() for m in MANIFESTS)
    cand = {}  # rel -> (action, reason, extra)
    for rel, st in files.items():
        if rel in protected_files:
            continue
        p = Path(rel)
        name, stem, ext, top = p.name, p.stem, p.suffix.lower(), len(p.parts) == 1
        in_data = any(part.lower() in DATA_DIRS for part in p.parts[:-1])
        if DELETE_FILES.match(name):
            cand[rel] = ("delete", "OS / editor junk", {})
        elif in_data:
            if ARCHIVE_FILES.match(name) or HARD.search(stem) or st.st_size > BIG:
                cand[rel] = ("ask", "inside a data folder", {})
        elif ARCHIVE_FILES.match(name) and not stem.isdigit():  # 000003.log is a LevelDB file, not a log
            cand[rel] = ("archive", "log / temp / backup file", {})
        elif COPY.search(stem):
            # "report (1).pdf" is often a different file the browser renamed. Box it only if it IS the original.
            base = Path(root) / p.parent / (COPY.sub("", stem) + p.suffix)
            same = base.is_file() and base.stat().st_size == st.st_size and base.read_bytes() == (Path(root) / rel).read_bytes()
            cand[rel] = ("archive", f"identical copy of {base.name}", {}) if same else \
                ("ask", "named like a copy, but no identical original next to it", {})
        elif HARD.search(stem):
            cand[rel] = ("archive", "throwaway name (tmp/old/backup)", {})
        elif top and ext in CODE and SOFT.search(stem) and not is_test_path(rel):
            cand[rel] = ("ask", "one-off script at the root?", {})
        elif top and ext in DOCS and is_project:  # in a folder of papers, the papers ARE the project
            cand[rel] = ("move", "loose doc at the root", {"to": f"docs/{name}"})
        elif top and ext in IMAGES:
            cand[rel] = ("ask", "loose image at the root (screenshot?)", {})
        elif st.st_size > BIG:
            cand[rel] = ("ask", "big file", {})

    # --- reference check: is anything that stays still pointing at a candidate?
    corpus = {}
    for rel, st in files.items():
        name = Path(rel).name
        if name == "PROJECT_MAP.md" or re.fullmatch(r"\..*ignore", name):
            continue  # listing a file there means "ignore it" or "here it is", not "this uses it"
        if Path(rel).suffix.lower() in TEXT and st.st_size < 512 * 1024 and cand.get(rel, ("keep",))[0] == "keep":
            try:
                corpus[rel] = (Path(root) / rel).read_text(encoding="utf-8", errors="ignore")
            except OSError:
                pass

    def needles(rel):
        p = Path(rel)
        # By full name, and by stem too: imports, URLs and LaTeX (`\includegraphics{fig}`) often drop the extension.
        # Logs are skipped for the stem: "server" from server.log would match half the code.
        names = [p.name] if ARCHIVE_FILES.match(p.name) else [p.name, p.stem]
        return list(dict.fromkeys(n for n in names if len(n) >= 3))

    # One pass over the corpus. Each dotted token (a.b.c) and each contiguous run of its parts (b, b.c, ...) is
    # checked against the names we look for (candidates, plus files big enough to be duplicates) -> up to 2 files
    # that mention it. Lookups are then O(1) instead of a regex over every file per candidate.
    wanted = {n for rel in [*cand, *(r for r, st in files.items() if st.st_size >= 2**20)]
              for n in needles(rel) if TOKEN.fullmatch(n)}
    seen = {}
    for src, text in corpus.items():
        for tok in set(TOKEN.findall(text)):
            parts = tok.split(".")[:8]
            for i in range(len(parts)):
                for j in range(i + 1, len(parts) + 1):
                    key = ".".join(parts[i:j]) if j - i > 1 else parts[i]
                    if key in wanted:
                        hits = seen.setdefault(key, [])
                        if len(hits) < 2 and src not in hits:
                            hits.append(src)

    def referenced_by(rel):
        for needle in needles(rel):
            if TOKEN.fullmatch(needle):
                hit = next((src for src in seen.get(needle, ()) if src != rel), None)
            else:  # odd names (spaces, brackets): plain substring search, rare
                hit = next((src for src, text in corpus.items() if src != rel and needle in text), None)
            if hit:
                return hit
        return None

    # A move must never un-ignore a file (e.g. `/Sales.docx` ignored at the root but not in docs/):
    # the next `git add .` would publish it.
    moves = [(r, c[2]["to"]) for r, c in cand.items() if c[0] == "move"]
    if moves and (Path(root) / ".git").exists():
        def ignored(paths):
            try:
                r = subprocess.run(["git", "-c", "core.quotepath=off", "check-ignore", "--no-index", "--stdin"], cwd=root,
                                   input="\n".join(paths), capture_output=True, text=True, encoding="utf-8")
                return set(r.stdout.splitlines())
            except OSError:
                return set(paths)  # no git binary: treat everything as ignored, so nothing moves
        was, will = ignored([s for s, _ in moves]), ignored([d for _, d in moves])
        for s, d in moves:
            if s in was and d not in will:
                del cand[s]

    for rel, (action, reason, extra) in sorted(cand.items()):
        st = files[rel]
        if action in ("archive", "move", "ask"):
            by = referenced_by(rel)
            if by and action == "move":
                continue  # something links to it where it is; leave it
            if by and Path(rel).suffix.lower() in IMAGES:
                continue  # used image
            if by:
                action, reason = "ask", f"{reason}, but referenced by {by}"
        if action == "move" and (Path(root) / extra["to"]).exists():
            continue
        add(rel, "file", action, reason, st.st_size, st.st_mtime, **extra)

    # Many moves at once are one decision for the user, not a silent reshuffle.
    moving = [i for i in items if i["action"] == "move"]
    if len(moving) > MANY_MOVES:
        for i in moving:
            i["action"], i["reason"] = "ask", f"{len(moving)} loose docs at the root: move them into docs/?"

    # --- exact duplicates among files that stay
    # Never boxed up on their own: identical files are often deliberate (per-seed results, a second
    # self-contained project folder). Only big ones are worth a question.
    taken = {i["path"] for i in items}
    by_size = {}
    for rel, st in files.items():
        p = Path(rel)
        if rel not in taken and rel not in protected_files and st.st_size >= 2**20 and not ID_NAME.match(p.stem) \
                and not any(part.lower() in DATA_DIRS for part in p.parts[:-1]):
            by_size.setdefault(st.st_size, []).append(rel)
    for group in by_size.values():
        if len(group) < 2:
            continue
        by_hash = {}
        for rel in group:
            h = hashlib.sha256((Path(root) / rel).read_bytes()).hexdigest()
            by_hash.setdefault(h, []).append(rel)
        for same in by_hash.values():
            if len(same) < 2:
                continue
            same.sort(key=lambda r: (bool(HARD.search(Path(r).stem)), r.count("/"), len(r), r))
            for extra_copy in same[1:]:
                if not referenced_by(extra_copy):
                    st = files[extra_copy]
                    add(extra_copy, "file", "ask", "identical copy of another file: box up this extra copy?", st.st_size, st.st_mtime,
                        same_as=same[0])

    # --- similar one-off scripts (candidates to merge into one reusable tool)
    # ponytail: O(n^2) difflib, capped at 300 loose scripts; fine for hand-made clutter.
    # Only where agents drop one-offs: the root and scripts/. Real source folders are left out on purpose.
    loose = [r for r, st in files.items() if Path(r).suffix.lower() in CODE and st.st_size < 30_000
             and r not in protected_files and (r.count("/") == 0 or r.split("/")[0] in ("scripts", "script"))][:300]
    text = {r: [ln.strip() for ln in (Path(root) / r).read_text(errors="ignore").splitlines() if ln.strip()] for r in loose}
    parent = {r: r for r in loose}

    def find(r):
        while parent[r] != r:
            r = parent[r]
        return r
    for i, a in enumerate(loose):
        for b in loose[i + 1:]:
            sm = difflib.SequenceMatcher(None, text[a], text[b], autojunk=False)
            if sm.real_quick_ratio() >= 0.5 and sm.quick_ratio() >= 0.5 and sm.ratio() >= 0.5:
                parent[find(a)] = find(b)
    groups = {}
    for r in loose:
        groups.setdefault(find(r), []).append(r)
    groups = [sorted(g) for g in groups.values() if len(g) >= 2]
    by_path = {i["path"]: i for i in items}
    similar = []
    for n, g in enumerate(groups, 1):
        for r in g:
            if r not in by_path:
                st = files[r]
                add(r, "file", "keep", f"similar scripts S{n}", st.st_size, st.st_mtime)
                by_path[r] = items[-1]
            by_path[r]["similar"] = f"S{n}"
        similar.append({"id": f"S{n}", "files": [by_path[r]["id"] for r in g], "paths": g})

    plan = {"root": str(root), "created": datetime.datetime.now().isoformat(timespec="seconds"),
            "total_size": total, "total_files": len(files) + count_all, "items": items, "similar": similar}
    (Path(root) / STATE).mkdir(exist_ok=True)
    (Path(root) / STATE / "plan.json").write_text(json.dumps(plan, indent=1), encoding="utf-8")
    summary(plan)
    return plan


def summary(plan):
    items = plan["items"]
    print(f"Thanks Mom {__version__} scanned {plan['total_files']:,} files ({human(plan['total_size'])}).")
    for action, label in (("delete", "regenerable / junk"), ("archive", "boxed up in a zip, recoverable"),
                          ("move", "tidied into folders"), ("ask", "mom needs to ask you")):
        sel = [i for i in items if i["action"] == action]
        if sel:
            print(f"  {action:<8}{len(sel):>4} items {human(sum(i['size'] for i in sel)):>10}   {label}")
    for i in sorted((i for i in items if i["action"] in ("delete", "archive")), key=lambda i: -i["size"])[:5]:
        print(f"    #{i['id']:<4}{i['action']:<8}{human(i['size']):>10}  {i['path']}  ({i['reason']})")
    asks = [i for i in items if i["action"] == "ask"]
    if asks:
        print("ASK (kept unless you decide otherwise):")
        by_reason = {}
        for i in asks:
            # group on the kind of question, not on the specific file that references it
            by_reason.setdefault(re.sub(r", but referenced by .*$", ", but something references it", i["reason"]), []).append(i)
        shown = 0
        for reason, group in by_reason.items():
            if shown >= 40:
                print(f"    ... more in .mom/plan.json")
                break
            if len(group) >= 4:  # one question, not twenty
                print(f"    {len(group)} items {human(sum(i['size'] for i in group)):>10}  {reason}  "
                      f"(ids {spans([i['id'] for i in group])}; e.g. {', '.join(i['path'] for i in group[:3])})")
                shown += 1
                continue
            for i in group:
                extra = f" (same as {i['same_as']})" if "same_as" in i else ""
                print(f"    #{i['id']:<4}{human(i['size']):>10}  {i['path']}  - {i['reason']}{extra}, untouched {i['age_days']}d")
                shown += 1
    info = sorted((i for i in items if i["action"] == "info"), key=lambda i: -i["size"])
    if info:
        print(f"FYI, not touched ({len(info)} other checkouts, {human(sum(i['size'] for i in info))}):")
        for i in info[:15]:
            print(f"    {human(i['size']):>10}  {i['path']}  - {i['reason'].split(';')[0]}, untouched {i['age_days']}d")
        if len(info) > 15:
            print(f"    ... {len(info) - 15} more in .mom/plan.json")
    for s in plan["similar"]:
        pairs = [f"#{n} {p}" for n, p in zip(s["files"], s["paths"])]
        print(f"  similar scripts {s['id']} (merge into one tool?): {', '.join(pairs[:8])}{' ...' if len(pairs) > 8 else ''}")
    print("Plan: .mom/plan.json   Next: mom.py apply ROOT [--keep IDS] [--archive IDS] [--delete IDS] [--move IDS]")


# ---------------------------------------------------------------- apply / undo
def inside(root, rel):
    p = (root / rel).resolve()
    if p == root.resolve() or not p.is_relative_to(root.resolve()):
        sys.exit(f"refusing to touch path outside the project: {rel}")
    return p


def _force(func, path, *_):
    os.chmod(path, stat.S_IWRITE)
    func(path)


def remove(p):
    if p.is_dir() and not p.is_symlink():
        shutil.rmtree(p, **({"onexc": _force} if sys.version_info >= (3, 12) else {"onerror": _force}))
    else:
        try:
            p.unlink()
        except PermissionError:
            os.chmod(p, stat.S_IWRITE)
            p.unlink()


def freeze_venv(venv):
    """Write requirements.freeze.txt next to the venv from its installed packages (works for pip and uv venvs)."""
    lines = []
    cfg = (venv / "pyvenv.cfg").read_text(errors="ignore")
    ver = re.search(r"^version(?:_info)?\s*=\s*(\S+)", cfg, re.M)
    for di in sorted(venv.glob("**/site-packages/*.dist-info")):
        meta = (di / "METADATA").read_text(errors="ignore") if (di / "METADATA").exists() else ""
        name = re.search(r"^Name:\s*(\S+)", meta, re.M)
        version = re.search(r"^Version:\s*(\S+)", meta, re.M)
        if not name or name.group(1).lower() == "pip":
            continue
        line = f"{name.group(1)}=={version.group(1) if version else ''}"
        if (di / "direct_url.json").exists():
            du = json.loads((di / "direct_url.json").read_text())
            vcs = du.get("vcs_info")
            if du.get("dir_info", {}).get("editable"):
                line = "-e " + du["url"]
            elif vcs:
                line = f"{name.group(1)} @ {vcs['vcs']}+{du['url']}@{vcs.get('commit_id', '')}"
            else:
                line = f"{name.group(1)} @ {du['url']}"
        lines.append(line)
    lines = list(dict.fromkeys(lines))  # Linux venvs reach the same site-packages via lib/ and lib64/
    out = venv.parent / "requirements.freeze.txt"
    out.write_text(f"# made by Thanks Mom from {venv.name} (python {ver.group(1) if ver else '?'})\n" + "\n".join(lines) + "\n")
    return out


def ids(s):
    """'3,7,10-14' -> {3, 7, 10, 11, 12, 13, 14}"""
    out = set()
    for part in filter(None, (x.strip() for x in (s or "").split(","))):
        a, _, b = part.partition("-")
        out.update(range(int(a), int(b or a) + 1))
    return out


def apply(root, keep, archive, delete, archive_paths=(), move=()):
    plan_file = root / STATE / "plan.json"
    if not plan_file.exists():
        sys.exit("no plan yet: run `mom.py scan ROOT` first")
    plan = json.loads(plan_file.read_text(encoding="utf-8"))
    items = {i["id"]: i for i in plan["items"]}
    for rel in archive_paths:  # things the scan didn't flag but the user chose to box up
        rel = Path(rel).as_posix().strip("/")
        p = inside(root, rel)
        if not p.exists():
            sys.exit(f"not found: {rel}")
        if PROTECTED.match(p.name) or any(x in PROTECTED_DIRS or x in VCS for x in Path(rel).parts):
            sys.exit(f"protected, won't archive: {rel}")
        n = max(items, default=0) + 1
        items[n] = dict(id=n, path=rel, kind="dir" if p.is_dir() else "file", action="archive", reason="user's call", size=0)
    for chosen, action in ((keep, "keep"), (archive, "archive"), (delete, "delete"), (move, "move")):
        for n in chosen:
            if n not in items:
                sys.exit(f"no item #{n} in the plan")
            if items[n]["action"] == "info":
                sys.exit(f"#{n} is another git checkout; remove it with git, not mom")
            if action == "move" and "to" not in items[n]:
                sys.exit(f"#{n} has no destination to move to")
            items[n]["action"] = action
    todo = [i for i in items.values() if i["action"] in ("delete", "archive", "move")]
    todo = [i for i in todo if (root / i["path"]).exists() and not PROTECTED.match(Path(i["path"]).name)]
    before = work_stats(root)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    zpath = root / STATE / f"archive-{stamp}.zip"
    manifest = {"created": stamp, "archived": [], "moved": [], "deleted": []}
    try:
        # 1. box up everything being archived, then verify the zip before removing anything
        boxed = [i for i in todo if i["action"] == "archive"]
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for i in boxed:
                p = inside(root, i["path"])
                for f in ([p] if p.is_file() else sorted(x for x in p.rglob("*") if x.is_file())):
                    z.write(f, f.relative_to(root).as_posix())
        with zipfile.ZipFile(zpath) as z:
            if z.testzip() is not None:
                sys.exit("archive zip failed verification; nothing was removed")
        for i in boxed:
            remove(inside(root, i["path"]))
            manifest["archived"].append(i["path"])
        # 2. tidy moves
        for i in (i for i in todo if i["action"] == "move"):
            src, dst = inside(root, i["path"]), inside(root, i["to"])
            if dst.exists():
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(src, dst)
            manifest["moved"].append([i["path"], i["to"]])
        # 3. regenerable / junk
        for i in (i for i in todo if i["action"] == "delete"):
            p = inside(root, i["path"])
            note, ignore = i.get("restore"), None
            if i["reason"] == "empty folder":
                try:
                    p.rmdir()  # only if still empty (a move may have just filled it)
                except OSError:
                    continue
            else:
                if (p / "pyvenv.cfg").exists():
                    note = f"{note}  (list: {freeze_venv(p).relative_to(root).as_posix()})"
                if note:
                    ignore = p.name + "/"
                elif DELETE_FILES.match(p.name):
                    ignore = "*" + p.suffix if p.suffix.lower() in (".pyc", ".pyo", ".swp", ".swo") else p.name
                remove(p)
            manifest["deleted"].append({"path": i["path"], "restore": note, "ignore": ignore})
        # 4. keep future clutter out of git
        gitignore(root, manifest)
    finally:
        (root / STATE / f"archive-{stamp}.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
        if not manifest["archived"] and zpath.exists():
            zpath.unlink()
    after = work_stats(root)
    print(f"Done. archived {len(manifest['archived'])}, moved {len(manifest['moved'])}, deleted {len(manifest['deleted'])}")
    print(f"  project (without .mom/): {human(before[0])} -> {human(after[0])}, files {before[1]:,} -> {after[1]:,}")
    if manifest["archived"]:
        print(f"  safety zip: .mom/{zpath.name} ({human(zpath.stat().st_size)})  -> undo: mom.py undo ROOT")
    for d in manifest["deleted"]:
        if d["restore"] and d["restore"] != "recreated automatically":
            print(f"  to get {d['path']} back: {d['restore']}")


def work_stats(root):
    """(size, files) of the project without our own .mom/ folder."""
    a, b = dir_stats(root), dir_stats(root / STATE)
    return a[0] - b[0], a[1] - b[1]


def gitignore(root, manifest):
    gi = root / ".gitignore"
    if not gi.exists() and not (root / ".git").exists():
        return
    old = gi.read_bytes().decode("utf-8", "surrogateescape") if gi.exists() else None
    want = [".mom/", ".scratch/"] + [d["ignore"] for d in manifest["deleted"] if d["ignore"]]
    if any(p.endswith(".log") for p in manifest["archived"]):
        want.append("*.log")
    have = {ln.strip().rstrip("/") for ln in (old or "").splitlines()}
    new = [w for w in dict.fromkeys(want) if w.rstrip("/") not in have]
    if new:
        manifest["gitignore_before"] = old  # exact bytes, so undo is byte-identical
        nl = "\r\n" if old and "\r\n" in old else "\n"
        sep = nl if old and not old.endswith("\n") else ""
        gi.write_bytes(((old or "") + sep + nl.join(["# added by Thanks Mom", *new]) + nl).encode("utf-8", "surrogateescape"))


def undo(root, zname=None):
    zips = sorted((root / STATE).glob("archive-*.json"))
    if zname:
        zips = [root / STATE / Path(zname).with_suffix(".json").name]
    if not zips:
        sys.exit("nothing to undo")
    mpath = zips[-1]
    manifest = json.loads(mpath.read_text(encoding="utf-8"))
    for src, dst in reversed(manifest["moved"]):
        s, d = inside(root, src), inside(root, dst)
        if d.exists() and not s.exists():
            s.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(d, s)
            try:
                d.parent.rmdir()  # drop the folder the move created, if now empty
            except OSError:
                pass
    zpath = mpath.with_suffix(".zip")
    restored = conflicts = 0
    if zpath.exists():
        with zipfile.ZipFile(zpath) as z:
            for info in z.infolist():
                target = inside(root, info.filename)
                if target.exists():
                    conflicts += 1
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(info) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out)
                t = time.mktime(info.date_time + (0, 0, -1))
                os.utime(target, (t, t))
                restored += 1
        zpath.rename(zpath.parent / (zpath.name + ".undone"))
    if "gitignore_before" in manifest:
        gi = root / ".gitignore"
        if manifest["gitignore_before"] is None:
            gi.unlink(missing_ok=True)
        else:
            gi.write_bytes(manifest["gitignore_before"].encode("utf-8", "surrogateescape"))
    mpath.rename(mpath.parent / (mpath.name + ".undone"))
    print(f"Undo: moved back {len(manifest['moved'])}, restored {restored} files"
          + (f", skipped {conflicts} that already exist" if conflicts else ""))
    for d in manifest["deleted"]:
        if d["restore"] and d["restore"] != "recreated automatically":
            print(f"  {d['path']} was regenerable: {d['restore']}")


# ---------------------------------------------------------------- map
def project_map(root, depth=3):
    out = []

    def walk(d, lvl):
        try:
            entries = sorted(d.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
        except OSError:
            return
        dirs = [e for e in entries if e.is_dir() and e.name not in VCS]
        files = [e for e in entries if e.is_file()]
        pad = "  " * lvl
        for e in dirs:
            if regen(e) or e.name.startswith("."):
                out.append(f"{pad}{e.name}/  (not listed)")
                continue
            size, count = dir_stats(e)
            out.append(f"{pad}{e.name}/  {count} files, {human(size)}")
            if lvl + 1 < depth:
                walk(e, lvl + 1)
        if lvl == 0 or len(files) <= 8:
            out.extend(f"{pad}{f.name}" for f in files[:25])
            if len(files) > 25:
                out.append(f"{pad}... +{len(files) - 25} files")
        elif files:
            exts = {}
            for f in files:
                exts[f.suffix or f.name] = exts.get(f.suffix or f.name, 0) + 1
            out.append(f"{pad}+{len(files)} files ({', '.join(f'{n} {e}' for e, n in sorted(exts.items(), key=lambda x: -x[1])[:4])})")
    walk(root, 0)
    print(f"{root.name}/\n" + "\n".join("  " + ln for ln in out))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"Thanks Mom {__version__}")
    ap.add_argument("cmd", choices=["scan", "apply", "undo", "map"])
    ap.add_argument("root", nargs="?", default=".")
    ap.add_argument("zip", nargs="?")
    ap.add_argument("--keep", default="")
    ap.add_argument("--archive", default="")
    ap.add_argument("--delete", default="")
    ap.add_argument("--move", default="", help="approve suggested moves, e.g. --move 4-30")
    ap.add_argument("--archive-path", action="append", default=[], metavar="PATH",
                    help="box up a path the scan didn't flag (repeatable)")
    a = ap.parse_args()
    root = Path(a.root).resolve()
    if not root.is_dir():
        sys.exit(f"not a folder: {root}")
    if a.cmd == "scan":
        scan(root)
    elif a.cmd == "apply":
        apply(root, ids(a.keep), ids(a.archive), ids(a.delete), a.archive_path, ids(a.move))
    elif a.cmd == "undo":
        undo(root, a.zip)
    else:
        project_map(root)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
