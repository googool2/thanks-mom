#!/usr/bin/env python3
"""Benchmark Thanks Mom on a realistic messy agent project and write bench/RESULTS.md.

  python bench/bench.py [WORKDIR]

Builds the project with a REAL `npm install` and a REAL venv + `pip install`, so it needs network.
Then: scan -> apply (answering every 'ask' with "box it up", the riskiest answer) -> reinstall deps
-> run the project's tests -> undo -> check every original file is back byte-for-byte.
"""
import hashlib, os, random, re, shutil, subprocess, sys, time, zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
MOM = HERE.parent / "thanks-mom" / "scripts" / "mom.py"
SKILL = HERE.parent / "thanks-mom" / "SKILL.md"
TRAPS = ["src/shopbot/backup.py", "dist/widget.js", "web/static/logo.png", ".env", "data/products.csv",
         "storage/uploads/3f2b9c1e-8a4d-4f6e-9b2a-1c3d5e7f9a0b.txt", "storage/uploads/7a1d0e4c-2b3f-4c5d-8e9f-0a1b2c3d4e5f.txt"]
REGEN = {"node_modules", ".venv", "__pycache__"}
WIN = os.name == "nt"
VPY = ".venv\\Scripts\\python.exe" if WIN else ".venv/bin/python"

SCRATCH_READER = '''import sys
from pathlib import Path
{imp}

def main():
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "{default}")
    if not path.exists():
        print("file not found:", path)
        return
    {body}
    print("chars:", len(text))
    print(text[:2000])

if __name__ == "__main__":
    main()
'''

FILES = {
    "README.md": "# ShopBot\nA tiny shop assistant. Python core in `src/`, web UI in `web/`.\nSee static/logo.png\n",
    ".env": "OPENAI_API_KEY=not-a-real-key\nDB_URL=sqlite:///shop.db\n",
    ".gitignore": "node_modules/\n",
    "requirements.txt": "requests\n",
    "package.json": '{\n  "name": "shopbot-web",\n  "version": "1.0.0",\n  "private": true,\n  "scripts": {"start": "node web/server.js"},\n  "dependencies": {"express": "^5.1.0", "dayjs": "^1.11.13", "next": "^15.5.0", "react": "^19.1.0", "react-dom": "^19.1.0", "typescript": "^5.9.0"}\n}\n',
    "src/shopbot/__init__.py": "from .core import price_with_tax, slugify\n",
    "src/shopbot/core.py": "import re\nimport requests  # used by fetch_rates\n\n\ndef price_with_tax(p, rate=0.09):\n    return round(p * (1 + rate), 2)\n\n\ndef slugify(s):\n    return re.sub(r'[^a-z0-9]+', '-', s.lower()).strip('-')\n\n\ndef fetch_rates(url):\n    return requests.get(url, timeout=5).json()\n",
    "src/shopbot/core_old.py": "def price_with_tax(p):\n    return p * 1.08  # old rate, replaced by core.py\n",
    # traps: look like junk, but the app needs them
    "src/shopbot/backup.py": "def backup_rows(rows):\n    return [dict(r) for r in rows]\n",
    "dist/widget.js": "module.exports = { widget: () => 'shop widget v1' };\n",
    # app upload storage: the DB points at these by name, so identical copies are NOT duplicates to remove
    "storage/uploads/3f2b9c1e-8a4d-4f6e-9b2a-1c3d5e7f9a0b.txt": "invoice 1042\n" * 400,
    "storage/uploads/7a1d0e4c-2b3f-4c5d-8e9f-0a1b2c3d4e5f.txt": "invoice 1042\n" * 400,
    "src/shopbot/cli.py": "import sys\nfrom shopbot.core import price_with_tax\n\nif __name__ == '__main__':\n    print(price_with_tax(float(sys.argv[1])))\n",
    "tests/test_core.py": "import unittest\nimport requests\nfrom shopbot.core import price_with_tax, slugify\nfrom shopbot.backup import backup_rows\n\n\nclass T(unittest.TestCase):\n    def test_backup(self):\n        self.assertEqual(backup_rows([{'a': 1}]), [{'a': 1}])\n\n    def test_tax(self):\n        self.assertEqual(price_with_tax(100), 109.0)\n\n    def test_slug(self):\n        self.assertEqual(slugify('Red Shoes!'), 'red-shoes')\n\n    def test_deps(self):\n        self.assertTrue(requests.__version__)\n\n\nif __name__ == '__main__':\n    unittest.main()\n",
    "web/app.js": "const express = require('express');\nconst dayjs = require('dayjs');\nconst app = express();\napp.use(express.static(__dirname + '/static'));\napp.get('/api/time', (req, res) => res.json({ now: dayjs().format() }));\nmodule.exports = app;\n",
    "web/server.js": "require('./app').listen(3000, () => console.log('on :3000'));\n",
    "web/static/index.html": "<!doctype html><title>ShopBot</title><img src='logo.png'><script src='main.js'></script>\n",
    "web/static/main.js": "fetch('/api/time').then(r => r.json()).then(console.log);\n",
    # --- the agent left all this behind
    "read_pdf_tmp.py": SCRATCH_READER.format(imp="import pypdf", default="invoice.pdf", body='text = "\\n".join(p.extract_text() or "" for p in pypdf.PdfReader(path).pages)'),
    "read_docx_tmp.py": SCRATCH_READER.format(imp="import docx", default="spec.docx", body='text = "\\n".join(p.text for p in docx.Document(path).paragraphs)'),
    "read_xlsx.py": SCRATCH_READER.format(imp="import openpyxl", default="prices.xlsx", body='text = "\\n".join(str(r) for r in openpyxl.load_workbook(path).active.iter_rows(values_only=True))'),
    "read_csv_quick.py": SCRATCH_READER.format(imp="import csv", default="data/products.csv", body='text = "\\n".join(",".join(r) for r in csv.reader(path.open()))'),
    "debug_api.py": "import requests\nr = requests.get('http://localhost:3000/api/time')\nprint(r.status_code, r.text)\n",
    "test_api_quick.py": "import requests\nprint(requests.get('http://localhost:3000/api/time').json())\n",
    "check_db.py": "import sqlite3\nprint(sqlite3.connect('shop.db').execute('select count(*) from sqlite_master').fetchone())\n",
    "fix_imports_v2.py": "import pathlib\nfor p in pathlib.Path('src').rglob('*.py'):\n    p.write_text(p.read_text().replace('from core', 'from shopbot.core'))\n",
    "IMPLEMENTATION_PLAN.md": "# Plan\n1. core\n2. web\n3. tests\n" * 20,
    "PLAN_v2_FINAL.md": "# Plan v2 (final)\n- refactor core\n- add tax\n" * 20,
    "FIX_SUMMARY.md": "# What I fixed\n- tax rounding\n- slugify unicode\n" * 15,
    "NOTES.txt": "remember: rate is 9%\n" * 30,
    "REFACTOR_NOTES_old.md": "# Old notes\nobsolete\n" * 20,
    "tmp/scratch_output.json": '{"ok": true}\n' * 500,
    "tmp/test.html": "<p>tmp</p>\n" * 200,
    "output/report_2026-10-01.html": "<table>" + "<tr><td>row</td></tr>" * 3000 + "</table>\n",
    "output/report_2026-10-02.html": "<table>" + "<tr><td>row 2</td></tr>" * 3000 + "</table>\n",
}


def make_fixture(root):
    if root.exists():
        shutil.rmtree(root, onerror=lambda f, p, e: (os.chmod(p, 0o700), f(p)))
    for rel, text in FILES.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    rnd = random.Random(42)
    rows = "\n".join(f"{i},Product {i},{rnd.randint(1, 900)}.{rnd.randint(0, 99):02d}" for i in range(8000))
    (root / "data").mkdir()
    (root / "data/products.csv").write_text("id,name,price\n" + rows + "\n")
    shutil.copy(root / "data/products.csv", root / "data/products_backup.csv")
    png = b"\x89PNG\r\n\x1a\n" + rnd.randbytes(300_000)
    (root / "web/static/logo.png").write_bytes(png)
    (root / "docs_assets").mkdir()
    (root / "docs_assets/diagram.png").write_bytes(png[:150_000] + b"diagram")
    shutil.copy(root / "docs_assets/diagram.png", root / "web/static/diagram.png")
    (root / "screenshot_2026-10-01.png").write_bytes(b"\x89PNG\r\n\x1a\n" + rnd.randbytes(420_000))
    (root / "error_screenshot.png").write_bytes(b"\x89PNG\r\n\x1a\n" + rnd.randbytes(380_000))
    log = "".join(f"2026-10-{d:02d} 12:00:{s:02d} INFO agent step {s} ok tokens={rnd.randint(100, 9000)}\n"
                  for d in range(1, 21) for s in range(60) for _ in range(30))
    (root / "server.log").write_text(log)
    (root / "npm-debug.log").write_text("npm ERR! code ERESOLVE\n" * 400)
    (root / ".DS_Store").write_bytes(rnd.randbytes(6148))
    (root / "Thumbs.db").write_bytes(rnd.randbytes(20_000))
    (root / "assets").mkdir()  # empty
    run("npm install --no-audit --no-fund --loglevel=error", root)
    run(f"\"{sys.executable}\" -m venv .venv", root)
    run(f"{VPY} -m pip install -q --disable-pip-version-check -r requirements.txt", root)
    checks(root)  # also creates __pycache__ like a real run would


def run(cmd, cwd, env=None):
    r = subprocess.run(cmd, cwd=cwd, shell=True, capture_output=True, text=True, env=env, encoding="utf-8", errors="replace")
    if r.returncode:
        print(r.stdout[-2000:], r.stderr[-2000:])
    return r


def checks(root):
    env = dict(os.environ, PYTHONPATH=str(root / "src"))
    env.pop("PYTHONDONTWRITEBYTECODE", None)  # behave like a normal dev machine
    py = run(f"{VPY} -m unittest discover -s tests -q", root, env).returncode == 0
    js = run("node -e \"const a=require('./web/app.js'); if(typeof a!=='function' || !require('./dist/widget.js').widget()) process.exit(1)\"", root).returncode == 0
    return py and js


def hashes(root):
    out = {}
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in REGEN and d != ".mom"]
        for f in fns:
            p = Path(dp) / f
            out[p.relative_to(root).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def stats(root, skip_mom=True):
    size = n = 0
    for dp, dns, fns in os.walk(root):
        if skip_mom:
            dns[:] = [d for d in dns if d != ".mom"]
        for f in fns:
            size += os.lstat(os.path.join(dp, f)).st_size
            n += 1
    return size, n


def mom(*args):
    t = time.perf_counter()
    r = subprocess.run([sys.executable, str(MOM), *args], capture_output=True, text=True, encoding="utf-8")
    if r.returncode:
        sys.exit(r.stdout + r.stderr)
    return r.stdout, time.perf_counter() - t


def listing(root):
    """What an agent gets from a naive recursive listing (`find .`, Glob **/*)."""
    return "\n".join(str(p.relative_to(root)) for p in root.rglob("*") if ".mom" not in p.parts)


def mb(n):
    return f"{n / 2**20:.1f} MB"


def tok(s):
    return round(len(s) / 4)


CATEGORY = [("npm packages", "node_modules (npm, lockfile present)"), ("Python virtualenv", ".venv (package list saved first)"),
            ("cache", "caches (`__pycache__`)"), ("log /", "logs / temp files"), ("exact duplicate", "exact duplicates"),
            ("throwaway", "throwaway names (`*_old`, `*_backup`)"), ("OS /", "OS junk (`.DS_Store`, `Thumbs.db`)"),
            ("empty", "empty folders"), ("loose doc", "loose docs -> `docs/`"), ("leftover folder", "leftover folders (`tmp/`, `output/`)"),
            ("one-off", "one-off scripts at root"), ("loose image", "screenshots at root"), ("similar", "similar scripts (kept, flagged)")]


def category(reason):
    return next((name for key, name in CATEGORY if key in reason), reason)


def main():
    work = Path(sys.argv[1] if len(sys.argv) > 1 else HERE / "_work").resolve() / "shopbot"
    print("building messy project (real npm + pip installs)...")
    make_fixture(work)
    h0 = hashes(work)
    ok0 = checks(work)
    size0, n0 = stats(work)
    root0 = len(os.listdir(work))
    map0, _ = mom("map", str(work))
    list0 = listing(work)

    out_scan, t_scan = mom("scan", str(work))
    import json
    plan = json.loads((work / ".mom/plan.json").read_text(encoding="utf-8"))
    # user answers "box it up" to everything, except where mom says something still uses it
    asks = [i["id"] for i in plan["items"] if i["action"] == "ask" and "referenced by" not in i["reason"]]
    out_apply, t_apply = mom("apply", str(work), "--archive", ",".join(map(str, asks)))
    plan_items = {i["path"]: i for i in plan["items"]}
    for i in plan["items"]:
        if i["id"] in asks:
            i["action"] = "archive (asked)"

    traps_ok = sum(1 for t in TRAPS if (work / t).exists() and hashlib.sha256((work / t).read_bytes()).hexdigest() == h0[t])
    size1, n1 = stats(work)
    root1 = len(os.listdir(work))
    map1, _ = mom("map", str(work))
    list1 = listing(work)
    mom_size = stats(work / ".mom", False)[0]

    # nothing lost: every original file is identical where it stayed, at its new path if moved, or inside the zip
    manifest = json.loads(next((work / ".mom").glob("archive-*.json")).read_text(encoding="utf-8"))
    moved = dict(manifest["moved"])
    zf = zipfile.ZipFile(next((work / ".mom").glob("archive-*.zip")))
    zipped = {n: hashlib.sha256(zf.read(n)).hexdigest() for n in zf.namelist()}
    zf.close()
    deleted_junk = {d["path"] for d in manifest["deleted"]}
    accounted = lost = 0
    for rel, h in h0.items():
        p = work / moved.get(rel, rel)
        if p.exists() and hashlib.sha256(p.read_bytes()).hexdigest() == h or zipped.get(rel) == h:
            accounted += 1
        elif rel in deleted_junk or any(rel.startswith(d + "/") for d in deleted_junk):
            accounted += 1  # OS junk / empty dirs by design
        elif rel == ".gitignore" and hashlib.sha256((manifest.get("gitignore_before") or "").encode("utf-8", "surrogateescape")).hexdigest() == h:
            accounted += 1  # only appended to; original saved in the manifest and restored by undo
        else:
            lost += 1
            print("LOST:", rel)

    run("npm ci --no-audit --no-fund --loglevel=error", work)
    run(f"\"{sys.executable}\" -m venv .venv", work)
    run(f"{VPY} -m pip install -q --disable-pip-version-check -r requirements.freeze.txt", work)
    ok1 = checks(work)

    out_undo, _ = mom("undo", str(work))
    h2 = hashes(work)
    back = sum(1 for rel, h in h0.items() if h2.get(rel) == h)
    junk = [r for r in h0 if r in deleted_junk]
    protected_touched = sum(1 for rel in h0 if re.match(r"(README|\.env|package|requirements|\.gitignore)", Path(rel).name)
                            and (rel in moved or rel in zipped or rel in deleted_junk))

    cats = {}
    for i in plan["items"]:
        c = category(i["reason"])
        a = cats.setdefault(c, [0, 0, set()])
        a[0] += 1
        a[1] += i["size"]
        a[2].add(i["action"])

    skill_tokens = tok(SKILL.read_text(encoding="utf-8")) if SKILL.exists() else 0
    lines = [
        "# Thanks Mom: benchmark results", "",
        "Test project: **ShopBot**, a small Python + Node app with the mess a few days of agent sessions leave behind",
        "(scratch readers, `*_old` files, plan docs, logs, screenshots, duplicate data, `tmp/`, `output/`).",
        "Dependencies are real: `npm install` of express, dayjs, next, react, react-dom, typescript (a typical vibe-coded web stack) and a real `.venv` with `pip install requests`.",
        "Every 'ask' was answered with **box it up** (the most aggressive answer), except items mom flagged as still referenced.",
        f"It also has {len(TRAPS)} traps that look like junk but aren't: a module named `backup.py`, a hand-made `dist/`, `.env`, a used image, the real data file, and two identical uploads in `storage/` that a database points to.",
        f"Generated by `python bench/bench.py` on {time.strftime('%Y-%m-%d')}, {sys.platform}, Python {sys.version.split()[0]}.", "",
        "## Before / after", "",
        "| | Before | After | Change |", "|---|---:|---:|---:|",
        f"| Project size | {mb(size0)} | {mb(size1)} | **-{100 * (1 - size1 / size0):.1f}%** |",
        f"| Files | {n0:,} | {n1:,} | -{100 * (1 - n1 / n0):.1f}% |",
        f"| Items at the root | {root0} | {root1} | {root1 - root0:+d} |",
        f"| Recursive file listing an agent might pull (≈ tokens) | {tok(list0):,} | {tok(list1):,} | -{100 * (1 - tok(list1) / tok(list0)):.1f}% |",
        f"| `mom.py map` output for PROJECT_MAP.md (≈ tokens) | {tok(map0):,} | {tok(map1):,} | -{100 * (1 - tok(map1) / tok(map0)):.1f}% |",
        "", f"Safety zip in `.mom/` (delete it when you're happy): {mb(mom_size)}.", "",
        "## Nothing lost", "",
        "| Check | Result |", "|---|---|",
        f"| Project tests (Python unittest + Node `require`) before | {'pass' if ok0 else 'FAIL'} |",
        f"| Same tests after cleanup + `npm ci` + `pip install -r requirements.freeze.txt` | {'**pass**' if ok1 else '**FAIL**'} |",
        f"| Original files accounted for after cleanup (in place, moved, or in the zip) | **{accounted}/{len(h0)}**, {lost} lost |",
        f"| Files back byte-for-byte after `mom.py undo` | **{back}/{len(h0)}** ({len(junk)} were OS junk, deleted by design) |",
        f"| Traps left untouched (`backup.py` module, hand-made `dist/`, used image, `.env`, data, identical uploads in `storage/`) | **{traps_ok}/{len(TRAPS)}** |",
        f"| Protected files touched (`.env`, README, manifests, lockfiles) | {protected_touched} |", "",
        "## Where the space went", "",
        "| What | Items | Size | Action |", "|---|---:|---:|---|",
    ]
    for c, (n, s, acts) in sorted(cats.items(), key=lambda kv: -kv[1][1]):
        lines.append(f"| {c} | {n} | {mb(s) if s >= 2**20 else f'{s / 1024:.0f} KB'} | {', '.join(sorted(acts))} |")
    lines += ["", "## Cost and speed", "",
              "| | |", "|---|---:|",
              f"| `SKILL.md` loaded when the skill runs (≈ tokens) | {skill_tokens:,} |",
              f"| `scan` summary the agent reads (≈ tokens) | {tok(out_scan):,} |",
              f"| `scan` time | {t_scan:.1f} s |", f"| `apply` time | {t_apply:.1f} s |", "",
              "Token counts are chars/4 estimates.", "",
              "<details><summary>Raw scan output</summary>", "", "```", out_scan.strip(), "```", "", "</details>", ""]
    (HERE / "RESULTS.md").write_text("\n".join(lines), encoding="utf-8")
    # numbers for bench/charts.py
    (HERE / "results.json").write_text(json.dumps({
        "size": [size0, size1], "files": [n0, n1], "root_items": [root0, root1],
        "listing_tokens": [tok(list0), tok(list1)], "map_tokens": [tok(map0), tok(map1)],
        "tests_before": ok0, "tests_after": ok1, "lost": lost, "files_checked": len(h0),
        "restored": back, "traps": [traps_ok, len(TRAPS)],
        "categories": [{"name": c, "items": n, "size": s, "actions": sorted(a)} for c, (n, s, a) in cats.items()],
    }, indent=1), encoding="utf-8")
    print("\n".join(lines))
    print(out_apply, out_undo)
    sys.exit(0 if ok0 and ok1 and lost == 0 and traps_ok == len(TRAPS) and back == len(h0) - len(junk) else 1)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
