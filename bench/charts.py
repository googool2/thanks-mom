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


def tokens_fmt(n):
    return f"{n / 1000:.1f}K" if n >= 10_000 else f"{n:,}"


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
        body.append(f'<rect x="{x + 0.5:.1f}" y="0.5" width="{w - 1:.1f}" height="{h - 1}" rx="10" '
                    f'fill="none" stroke="{t["line"]}"/>')
        body.append(text(x + 16, 42, value, t, 28, "ink", weight=600))
        body.append(text(x + 16, 66, label, t, 12, "ink"))
        body.append(text(x + 16, 82, sub, t, 11, "muted"))
    return svg(t, h, title, body)


def hbars(rows, color, fmt, t, x0=250, row_h=30, thick=16):
    """Single-series horizontal bars from one baseline, value at the tip."""
    body, top = [], 0
    top_val = max(v for _, v in rows) or 1
    span = W - x0 - 80
    for i, (label, v) in enumerate(rows):
        cy = top + i * row_h + row_h / 2
        body.append(text(0, cy + 4, label, t, 12, "ink"))
        w = max(span * v / top_val, 2)
        body.append(bar(x0, cy - thick / 2, w, thick, color))
        body.append(text(x0 + w + 8, cy + 4, fmt(v), t, 12, "ink2"))
    body.append(f'<line x1="{x0}" y1="{top}" x2="{x0}" y2="{top + row_h * len(rows)}" stroke="{t["grid"]}" stroke-width="1"/>')
    return body, row_h * len(rows)


def shifted(parts, dy):
    return [f'<g transform="translate(0,{dy:.1f})">'] + parts + ["</g>"]


def realworld_chart(rw, t):
    title = f"What mom did on {rw['projects']} real projects"
    b, a = rw["before"], rw["after"]
    body, y = header(title, [
        f"Copies of real projects, cleaned with no questions answered. {size_fmt(b['bytes'])} → {size_fmt(a['bytes'])}, "
        f"{b['files']:,} → {a['files']:,} files."], t)
    done = [(name, v["bytes"]) for name, v in rw["done_automatically"].items() if v["bytes"] and "moved" not in name]
    moved = next((v["items"] for name, v in rw["done_automatically"].items() if "moved" in name), 0)
    y += 10
    body.append(text(0, y + 4, "Done automatically: space freed", t, 13, "ink", weight=600))
    parts, h = hbars(sorted(done, key=lambda r: -r[1]), t["series"][0], size_fmt, t)
    body += shifted(parts, y + 14)
    y += 14 + h + 6
    body.append(text(0, y + 4, f"Plus {moved} loose docs moved into docs/. Every automatic decision was checked by hand.", t, 11, "muted"))
    y += 36
    asked = sorted(rw["left_to_ask"].items(), key=lambda r: -r[1])
    body.append(text(0, y + 4, f"Left for you to decide: {sum(v for _, v in asked):,} questions, grouped by kind", t, 13, "ink", weight=600))
    parts, h = hbars(asked, t["series"][1], count_fmt, t, row_h=26, thick=14)
    body += shifted(parts, y + 14)
    y += 14 + h + 8
    return svg(t, y, title, body)


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
    freed = rw["before"]["bytes"] - rw["after"]["bytes"]
    OUT.mkdir(exist_ok=True)
    for old in OUT.glob("*.svg"):
        old.unlink()
    for mode, t in THEMES.items():
        charts = {
            "stats": stats([
                (f"{rw['projects']}", "real projects tested", "on copies, then deleted"),
                (f"{rw['mechanical']['lost']}", "files lost", f"{rw['mechanical']['files_checked']:,} checked"),
                (f"{v0['wrong']:,} → {v1['wrong']}", "wrong automatic decisions", "version 1.0 → 1.1"),
                (size_fmt(freed), "freed automatically", "before any question"),
            ], t, "Thanks Mom in numbers"),
            "realworld": realworld_chart(rw, t),
            "benchmark": dumbbell(
                "Synthetic benchmark: before and after",
                ["A messy Python + Next.js project with real npm and pip installs and seven traps.",
                 f"Tests pass after cleanup · {r['files_checked'] - r['lost']}/{r['files_checked']} files accounted for · "
                 f"{r['traps'][0]}/{r['traps'][1]} traps left alone"],
                [("Project size", *r["size"], size_fmt), ("Files", *r["files"], count_fmt),
                 ("Items at the root", *r["root_items"], count_fmt),
                 ("Recursive file listing (≈ tokens)", *r["listing_tokens"], tokens_fmt)], t),
        }
        for name, content in charts.items():
            (OUT / f"{name}-{mode}.svg").write_text(content, encoding="utf-8")
    print("wrote", ", ".join(sorted(p.name for p in OUT.glob("*.svg"))))


if __name__ == "__main__":
    main()
