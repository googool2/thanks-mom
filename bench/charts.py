#!/usr/bin/env python3
"""Draw the README charts into assets/ (light + dark SVG each). Stdlib only.

  python bench/bench.py     # writes bench/results.json   (synthetic benchmark)
  bench/realworld.json      # totals from the real-project runs (see bench/realworld.py)
  python bench/charts.py
"""
import json
from pathlib import Path
from xml.sax.saxutils import escape

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "assets"

# Colors validated with the dataviz palette checker against GitHub's own backgrounds.
THEMES = {
    "light": dict(surface="#ffffff", ink="#0b0b0b", ink2="#52514e", muted="#898781", grid="#e1e0d9",
                  line="rgba(11,11,11,0.10)", series=["#2a78d6", "#eb6834"]),
    "dark": dict(surface="#0d1117", ink="#f0efec", ink2="#c3c2b7", muted="#898781", grid="#2c2c2a",
                 line="rgba(255,255,255,0.12)", series=["#3987e5", "#d95926"]),
}
FONT = 'system-ui, -apple-system, "Segoe UI", Helvetica, Arial, sans-serif'
W = 760


def size_fmt(b):
    for unit, n in (("GB", 2**30), ("MB", 2**20), ("KB", 2**10)):
        if b >= n:
            return f"{b / n:.1f} {unit}"
    return f"{b:.0f} B"


def count_fmt(n):
    return f"{n:,}"



def change(pct):
    d = 100 - pct
    return "0%" if abs(d) < 0.05 else (f"−{d:.1f}%" if d > 0 else f"+{-d:.1f}%")


def text(x, y, s, t, size=12, fill="ink2", anchor="start", weight=400):
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{t[fill]}" text-anchor="{anchor}" '
            f'font-weight="{weight}">{escape(s)}</text>')


def dot(x, y, color, t, r=5):
    # 2px ring in the surface color keeps overlapping dots legible
    return f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{color}" stroke="{t["surface"]}" stroke-width="2"/>'


def bar(x, y, w, h, color):
    """Horizontal bar: square at the baseline, 4px rounded data end."""
    r = min(4, w / 2)
    return (f'<path d="M{x:.1f},{y:.1f} h{w - r:.1f} q{r:.1f},0 {r:.1f},{r:.1f} v{h - 2 * r:.1f} '
            f'q0,{r:.1f} -{r:.1f},{r:.1f} h-{w - r:.1f} z" fill="{color}"/>')


def svg(t, height, title, body):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{height}" viewBox="0 0 {W} {height}" '
            f'role="img" aria-label="{escape(title)}" font-family=\'{FONT}\'>\n<title>{escape(title)}</title>\n'
            + "\n".join(body) + "\n</svg>\n")


def header(title, sub, t, legend=()):
    body = [text(0, 20, title, t, 16, "ink", weight=600)]
    y = 40
    for line in sub:
        body.append(text(0, y, line, t, 12))
        y += 17
    x = W
    for label, color in reversed(legend):  # legend, right-aligned on the title row
        x -= len(label) * 6.6 + 8
        body.append(text(x, 20, label, t, 12, "ink2"))
        x -= 14
        body.append(dot(x + 5, 16, color, t, 4))
        x -= 14
    return body, y + 6


def stats(tiles, t, title):
    """A row of stat tiles: value first, label under it. The one place big numbers belong."""
    gap, h = 12, 96
    w = (W - gap * (len(tiles) - 1)) / len(tiles)
    body = []
    for n, (value, label, sub) in enumerate(tiles):
        x = n * (w + gap)
        for s, size in ((value, 28), (label, 12), (sub, 11)):  # ~0.5em per character in system-ui
            assert len(s) * size * 0.5 <= w - 32, f"stat tile text too long for its box: {s!r}"
        body.append(f'<rect x="{x + 0.5:.1f}" y="0.5" width="{w - 1:.1f}" height="{h - 1}" rx="10" '
                    f'fill="none" stroke="{t["line"]}"/>')
        body.append(text(x + 16, 42, value, t, 28, "ink", weight=600))
        body.append(text(x + 16, 66, label, t, 12, "ink"))
        body.append(text(x + 16, 82, sub, t, 11, "muted"))
    return svg(t, h, title, body)


def type_chart(rw, t):
    """Range per project type (bar = min..max across projects, dot = median), all on one 0-100% axis."""
    title = "Size reduction by project type"
    acc = t["series"][0]
    body, y = header(title, ["Automatic actions only, before answering a single question. Bar: range across projects of",
                             "that type. Dot: median. Right: median size and file reduction."], t)
    X0, X1 = 270, W - 110
    y += 12
    xs = lambda v: X0 + (X1 - X0) * v / 100
    for row in rw["by_type"]:
        sz, fl = row["size_reduction_pct"], row["file_reduction_pct"]
        cy = y + 14
        body.append(text(0, cy - 1, row["type"], t, 13, "ink"))
        body.append(text(0, cy + 15, row["what_goes"], t, 11, "ink2"))
        body.append(f'<line x1="{X0}" y1="{cy}" x2="{X1}" y2="{cy}" stroke="{t["grid"]}" stroke-width="1"/>')
        if sz["max"] - sz["min"] >= 0.5:
            body.append(f'<rect x="{xs(sz["min"]):.1f}" y="{cy - 4}" width="{xs(sz["max"]) - xs(sz["min"]):.1f}" height="8" rx="4" '
                        f'fill="{acc}" fill-opacity="0.3"/>')
        body.append(dot(xs(sz["median"]), cy, acc, t, 6))
        body.append(text(W, cy - 1, f"−{sz['median']:.0f}%" if sz["median"] >= 0.5 else "0%", t, 13, "ink", "end", 600))
        body.append(text(W, cy + 15, f"files −{fl['median']:.0f}%" if fl["median"] >= 0.5 else "files 0%", t, 11, "muted", "end"))
        y += 44
    for v in (0, 25, 50, 75, 100):
        body.append(text(xs(v), y + 12, f"−{v}%" if v else "0%", t, 11, "muted", "middle"))
    body.append(text(X0, y + 28, "size reduction", t, 11, "muted"))
    return svg(t, y + 36, title, body)


def agent_chart(ae, t):
    """Mean tokens per state of the same project, single series, value and context at the bar tip."""
    title = "Does a tidy project help an agent?"
    rows = [("messy", "Before cleanup", "old copies, backup/, loose plans"),
            ("clean", "After cleanup", "no map"),
            ("map_first", "After cleanup + map", "CLAUDE.md: read the map first"),
            ("mapped", "After cleanup + map", "CLAUDE.md: read the map when stuck")]
    sm = ae["summary"]
    body, y = header(title, [f"Claude Code ({ae['model']}) answering {ae['questions']} \"which file does X?\" questions on a ~40-module project,",
                             f"{ae['reps']} runs each. All {sum(v['runs'] for v in sm.values())} answers were correct. Bar: mean tokens per question."], t)
    X0, span, row_h = 270, W - 270 - 200, 44
    top = max(sm[k]["mean_tokens"] for k, *_ in rows)
    y += 14
    for key, label, note in rows:
        v = sm[key]
        cy = y + 14
        body.append(text(0, cy - 1, label, t, 13, "ink"))
        body.append(text(0, cy + 15, note, t, 11, "ink2"))
        w = span * v["mean_tokens"] / top
        body.append(bar(X0, cy - 8, w, 16, t["series"][0] if key == "clean" else t["muted"]))
        body.append(text(X0 + w + 8, cy - 1, f"{v['mean_tokens'] / 1000:.0f}K tokens", t, 12, "ink", weight=600))
        body.append(text(X0 + w + 8, cy + 14, f"{v['mean_turns']:.1f} steps · {v['mean_seconds']:.0f} s · worst {v['max_turns']} steps", t, 11, "muted"))
        y += row_h
    body.append(f'<line x1="{X0}" y1="{y - row_h * len(rows) + 2}" x2="{X0}" y2="{y}" stroke="{t["grid"]}" stroke-width="1"/>')
    return svg(t, y + 10, title, body)


def dumbbell(title, sub, rows, t):
    """Each row: before (gray, = 100%) and after (accent) on one 0-100% axis, so different units share a scale."""
    X0, X1 = 260, W - 82
    before_c, after_c = t["muted"], t["series"][0]
    body, y = header(title, sub, t, [("Before", before_c), ("After", after_c)])
    y += 8
    for label, before, after, fmt in rows:
        cy = y + 14
        pct = 100 * after / before
        xa, xb = X0 + (X1 - X0) * pct / 100, X1
        body.append(text(0, cy - 1, label, t, 13, "ink"))
        body.append(text(0, cy + 15, f"{fmt(before)} → {fmt(after)}", t, 11, "ink2"))
        body.append(f'<line x1="{X0}" y1="{cy}" x2="{X1}" y2="{cy}" stroke="{t["grid"]}" stroke-width="1"/>')
        body.append(f'<line x1="{xa:.1f}" y1="{cy}" x2="{xb:.1f}" y2="{cy}" stroke="{after_c}" stroke-width="2" stroke-opacity="0.35"/>')
        body.append(dot(xb, cy, before_c, t))
        body.append(dot(xa, cy, after_c, t))
        body.append(text(W, cy + 4, change(pct), t, 13, "ink", "end", 600))
        y += 40
    for p in (0, 25, 50, 75, 100):
        body.append(text(X0 + (X1 - X0) * p / 100, y + 14, f"{p}%", t, 11, "muted", "middle"))
    body.append(text(X0, y + 30, "after, as % of before", t, 11, "muted"))
    return svg(t, y + 40, title, body)


def main():
    r = json.loads((HERE / "results.json").read_text(encoding="utf-8"))
    rw = json.loads((HERE / "realworld.json").read_text(encoding="utf-8"))
    v0, v1 = rw["verdicts"]["1.0.0"], rw["verdicts"]["1.1.0"]
    best = max(rw["by_type"], key=lambda r: r["size_reduction_pct"]["max"])
    wrong0 = 100 * v0["wrong"] / v0["auto"]
    ae = json.loads((HERE / "agent-eval.json").read_text(encoding="utf-8"))["summary"]
    agent_cut = 100 * (1 - ae["clean"]["mean_tokens"] / ae["messy"]["mean_tokens"])
    OUT.mkdir(exist_ok=True)
    for old in OUT.glob("*.svg"):
        old.unlink()
    for mode, t in THEMES.items():
        charts = {
            "stats": stats([
                (f"−{best['size_reduction_pct']['max']:.0f}%", "smaller, at best", best["type"].lower()),
                (f"−{agent_cut:.0f}%", "agent tokens to find code", "after cleanup, measured"),
                (f"{rw['mechanical']['lost']}", "files lost", f"{rw['mechanical']['files_checked']:,} checked"),
                (f"{wrong0:.1f}% → {100 * v1['wrong'] / max(v1['auto'], 1):.0f}%", "wrong automatic decisions", "v1.0 → v1.1, reviewed by hand"),
            ], t, "Thanks Mom in numbers"),
            "by-type": type_chart(rw, t),
            "agent": agent_chart(json.loads((HERE / "agent-eval.json").read_text(encoding="utf-8")), t),
            "benchmark": dumbbell(
                "Synthetic benchmark: before and after",
                ["A messy Python + Next.js project with real npm and pip installs and seven traps.",
                 f"Tests pass after cleanup · {r['files_checked'] - r['lost']}/{r['files_checked']} files accounted for · "
                 f"{r['traps'][0]}/{r['traps'][1]} traps left alone"],
                [("Project size", *r["size"], size_fmt), ("Files", *r["files"], count_fmt),
                 ("Items at the root", *r["root_items"], count_fmt)], t),
        }
        for name, content in charts.items():
            (OUT / f"{name}-{mode}.svg").write_text(content, encoding="utf-8")
    print("wrote", ", ".join(sorted(p.name for p in OUT.glob("*.svg"))))


if __name__ == "__main__":
    main()
