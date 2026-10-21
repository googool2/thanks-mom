#!/usr/bin/env python3
"""Does a cleaned project with PROJECT_MAP.md help a real agent find code? Measured with headless Claude Code.

  python bench/agent_eval.py WORKDIR [--reps 2] [--model sonnet]   -> bench/agent-eval.json + a table

Same synthetic project, three states, eight "which file does X?" questions:
  messy   - agent leftovers: an old backup/ copy of the code, *_old files, loose plan docs, no map
  clean   - the leftovers are gone, no map
  mapped  - clean, plus PROJECT_MAP.md and the 3-line CLAUDE.md pointer Thanks Mom writes
The agent only gets Read, Glob and Grep, and no user settings, plugins or MCP servers.
Uses your Claude Code quota (about 50 short headless runs at --reps 2).
"""
import argparse, json, os, shutil, stat, statistics, subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent

MODULES = {  # path -> (exported name, one-line body hint); the code is small but real-looking
    "apps/api/src/modules/fulfillment/rates.service.ts": ("computeShippingRate", "weight * zone.perKg + carrier.base"),
    "apps/api/src/modules/fulfillment/carriers.ts": ("CARRIERS", "dhl, ups, post"),
    "apps/api/src/modules/fulfillment/packaging.ts": ("pickBox", "smallest box that fits"),
    "apps/api/src/modules/billing/invoice.service.ts": ("createInvoice", "lines, tax, total"),
    "apps/api/src/modules/billing/tax.ts": ("vatFor", "rate by country"),
    "apps/api/src/modules/billing/refunds.ts": ("refundPayment", "partial refunds"),
    "apps/api/src/modules/identity/auth.controller.ts": ("login", "issue session token"),
    "apps/api/src/modules/identity/password.service.ts": ("requestPasswordReset", "token + enqueue email job"),
    "apps/api/src/modules/identity/sessions.ts": ("revokeSessions", "on password change"),
    "apps/api/src/modules/catalog/products.service.ts": ("listProducts", "filters, paging"),
    "apps/api/src/modules/catalog/pricing.ts": ("priceFor", "list price minus promo"),
    "apps/api/src/modules/search/reindex.task.ts": ("rebuildSearchIndex", "drop and rebuild all documents"),
    "apps/api/src/modules/search/query.ts": ("searchProducts", "fuzzy match"),
    "apps/api/src/modules/notifications/push.ts": ("sendPush", "mobile push"),
    "apps/api/src/config/database.ts": ("dbConfig", "host, pool size, ssl from env"),
    "apps/api/src/config/env.ts": ("loadEnv", "read and check env vars"),
    "apps/api/src/main.ts": ("bootstrap", "start http server"),
    "apps/web/src/features/cart/CartSummary.tsx": ("CartSummary", "renders subtotal, shipping and cart total"),
    "apps/web/src/features/cart/CartItem.tsx": ("CartItem", "one line in the cart"),
    "apps/web/src/features/checkout/ShippingStep.tsx": ("ShippingStep", "shows shipping options from the api"),
    "apps/web/src/features/checkout/PaymentStep.tsx": ("PaymentStep", "card form"),
    "apps/web/src/features/account/ResetPasswordForm.tsx": ("ResetPasswordForm", "asks for email, calls api"),
    "apps/web/src/features/product/ProductPage.tsx": ("ProductPage", "gallery and buy button"),
    "apps/web/src/lib/api.ts": ("apiClient", "fetch wrapper"),
    "packages/shared/money/round.ts": ("roundToCents", "banker's rounding of prices to cents"),
    "packages/shared/money/format.ts": ("formatPrice", "currency display"),
    "packages/shared/dates/business-days.ts": ("addBusinessDays", "skip weekends"),
    "packages/shared/validation/email.ts": ("isValidEmail", "validates email addresses"),
    "packages/shared/validation/phone.ts": ("isValidPhone", "E.164"),
    "workers/emails/password-reset.job.ts": ("sendPasswordResetEmail", "renders template and sends the reset email"),
    "workers/emails/order-confirmation.job.ts": ("sendOrderConfirmation", "order summary email incl. shipping"),
    "workers/reports/nightly-sales.job.ts": ("nightlySalesReport", "aggregates yesterday's sales into a CSV"),
    "workers/reports/weekly-stock.job.ts": ("weeklyStockReport", "stock levels"),
    "workers/sync/erp-sync.job.ts": ("syncWithErp", "push orders to ERP"),
    "infra/docker/api.Dockerfile": ("", ""),
    "infra/terraform/main.tf": ("", ""),
    "scripts/seed.ts": ("seedDatabase", "demo data"),
}
QUESTIONS = [  # question, the one correct file
    ("Which file calculates the shipping cost of an order?", "apps/api/src/modules/fulfillment/rates.service.ts"),
    ("Which file sends the password reset email?", "workers/emails/password-reset.job.ts"),
    ("Which file rounds prices to cents?", "packages/shared/money/round.ts"),
    ("Which file builds the nightly sales report?", "workers/reports/nightly-sales.job.ts"),
    ("Which file rebuilds the search index?", "apps/api/src/modules/search/reindex.task.ts"),
    ("Which UI component shows the cart total?", "apps/web/src/features/cart/CartSummary.tsx"),
    ("Which file configures the database connection?", "apps/api/src/config/database.ts"),
    ("Which file validates email addresses?", "packages/shared/validation/email.ts"),
]
MAP = """# Project map

Online shop. TypeScript monorepo: API, web app, background workers, shared packages.

```
apps/api/src/
  modules/fulfillment/   shipping rates, carriers, packaging
  modules/billing/       invoices, tax, refunds
  modules/identity/      login, sessions, password reset requests
  modules/catalog/       products and pricing
  modules/search/        search queries and the search index
  modules/notifications/ push notifications
  config/                env and database configuration
  main.ts                API entry point
apps/web/src/
  features/cart/         cart page and summary
  features/checkout/     checkout steps (shipping, payment)
  features/account/      account pages, reset password form
  features/product/      product page
  lib/                   API client
packages/shared/
  money/                 rounding and formatting of prices
  dates/                 business-day helpers
  validation/            email and phone validation
workers/
  emails/                transactional emails (password reset, order confirmation)
  reports/               scheduled reports (nightly sales, weekly stock)
  sync/                  ERP sync
infra/                   Docker and Terraform
scripts/                 one-off scripts (seed data)
```
"""
POINTER_FIRST = """## Project map & house rules
- Read PROJECT_MAP.md before searching for files.
- Reusable helpers live in tools/ (listed in PROJECT_MAP.md). Use or extend one before writing a new script.
- Throwaway scripts go in .scratch/ (gitignored), never the project root.
"""


def rmtree(p):
    """shutil.rmtree that also removes git's read-only object files on Windows."""
    def force(func, path, *_):
        os.chmod(path, stat.S_IWRITE)
        func(path)
    shutil.rmtree(p, **({"onexc": force} if sys.version_info >= (3, 12) else {"onerror": force}))


POINTER = """## Project map & house rules
- If a quick search doesn't find what you need, read PROJECT_MAP.md: it says what every folder is for.
- Reusable helpers live in tools/ (listed in PROJECT_MAP.md). Use or extend one before writing a new script.
- Throwaway scripts go in .scratch/ (gitignored), never the project root.
"""
STATES = ("messy", "clean", "mapped", "map_first")


def source(name, hint):
    return (f"// {hint}\nimport {{ log }} from '../log';\n\nexport function {name}(input: any) {{\n"
            f"  log('{name}');\n  // {hint}\n  return input;\n}}\n") if name else "# infra\n"


def build(root, state):
    if root.exists():
        rmtree(root)
    for rel, (name, hint) in MODULES.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(source(name, hint), encoding="utf-8")
    (root / "package.json").write_text('{"name": "shop", "private": true, "workspaces": ["apps/*", "packages/*", "workers"]}\n')
    (root / "README.md").write_text("# Shop\nOnline shop monorepo.\n")
    (root / ".gitignore").write_text("node_modules/\ndist/\n.mom/\n.scratch/\n")
    if state == "messy":  # what weeks of agent sessions leave behind
        for rel, (name, hint) in list(MODULES.items()):
            if name:  # an old full copy of the code, slightly different
                (root / "backup" / rel).parent.mkdir(parents=True, exist_ok=True)
                (root / "backup" / rel).write_text(source(name, hint + " (old version)"), encoding="utf-8")
        for rel in ("apps/api/src/modules/fulfillment/rates.service_old.ts", "packages/shared/money/round_old.ts",
                    "workers/emails/password-reset.job_v2.ts", "apps/web/src/features/cart/CartSummary_copy.tsx"):
            name, hint = MODULES[rel.replace("_old", "").replace("_v2", "").replace("_copy", "")]
            (root / rel).write_text(source(name, hint + " (draft)"), encoding="utf-8")
        for n, topic in enumerate(["shipping cost refactor", "password reset email", "cents rounding", "nightly sales report",
                                   "search index rebuild", "cart total bug", "database pool", "email validation"]):
            (root / f"PLAN_{n}_{topic.split()[0].upper()}_FINAL.md").write_text(f"# Plan: {topic}\nWe changed the {topic} code.\n")
        for n in range(6):
            (root / f"check_{n}.py").write_text("print('ok')\n")
    if state in ("mapped", "map_first"):  # map_first: the 1.0-1.2 pointer, which made the agent read the map every time
        (root / "PROJECT_MAP.md").write_text(MAP, encoding="utf-8")
        (root / "CLAUDE.md").write_text(POINTER_FIRST if state == "map_first" else POINTER, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=root)
    subprocess.run(["git", "add", "-A"], cwd=root)
    subprocess.run(["git", "-c", "user.email=e@example.com", "-c", "user.name=e", "commit", "-qm", "state"], cwd=root)


def ask(root, question, model):
    claude = shutil.which("claude")
    prompt = f"{question} Reply with only the file path relative to the project root, nothing else."
    t = time.perf_counter()
    # Run as a plain CLI session: variables inherited from a parent Claude Code session would hijack auth and settings.
    env = {k: v for k, v in os.environ.items() if not (k.startswith("CLAUDE") or k == "ANTHROPIC_BASE_URL")}
    r = subprocess.run([claude, "-p", prompt, "--output-format", "json", "--model", model, "--setting-sources", "project",
                        "--strict-mcp-config", "--no-session-persistence", "--allowedTools", "Read", "Glob", "Grep",
                        "--disallowedTools", "Bash", "Edit", "Write", "NotebookEdit", "WebFetch", "WebSearch", "Task", "Agent"],
                       cwd=root, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
    try:
        out = json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"error": (r.stdout + r.stderr)[-400:]}
    u = out.get("usage", {})
    return {"answer": (out.get("result") or "").strip(), "turns": out.get("num_turns"), "cost_usd": out.get("total_cost_usd"),
            "seconds": round(time.perf_counter() - t, 1),
            "tokens": sum(u.get(k, 0) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens"))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workdir")
    ap.add_argument("--reps", type=int, default=2)
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--states", default=",".join(STATES), help="comma-separated subset; results merge into agent-eval.json")
    a = ap.parse_args()
    work = Path(a.workdir).resolve()
    partial = HERE / "agent-eval.partial.json"
    runs = json.loads(partial.read_text(encoding="utf-8")) if partial.exists() else []
    states = a.states.split(",")
    final = HERE / "agent-eval.json"
    if final.exists() and not partial.exists():  # keep earlier states, rerun only the requested ones
        runs = [r for r in json.loads(final.read_text(encoding="utf-8"))["runs"] if r["state"] not in states]
    done = {(r["state"], r["rep"], r["question"]) for r in runs if "error" not in r}
    for state in states:
        root = work / state
        build(root, state)
        for rep in range(a.reps):
            for q, want in QUESTIONS:
                if (state, rep, q) in done:
                    continue
                res = ask(root, q, a.model)
                res.update(state=state, question=q, rep=rep,
                           correct=want in res.get("answer", "").replace("\\", "/") and "backup/" not in res.get("answer", ""))
                runs.append(res)
                partial.write_text(json.dumps(runs, indent=1), encoding="utf-8")
                print(f"{state:7} {rep} {'OK ' if res['correct'] else 'BAD'} turns={res.get('turns')} tokens={res.get('tokens')} "
                      f"{res.get('answer', res.get('error', ''))[:70]}", flush=True)
        rmtree(root)
    summary = {}
    for state in STATES:
        rs = [r for r in runs if r["state"] == state and "error" not in r]
        if not rs:
            continue
        summary[state] = {"runs": len(rs), "correct_pct": round(100 * sum(r["correct"] for r in rs) / max(len(rs), 1), 1),
                          "median_turns": statistics.median(r["turns"] for r in rs),
                          "median_tokens": statistics.median(r["tokens"] for r in rs),
                          "median_seconds": statistics.median(r["seconds"] for r in rs),
                          "mean_tokens": round(statistics.mean(r["tokens"] for r in rs)),
                          "mean_turns": round(statistics.mean(r["turns"] for r in rs), 2),
                          "max_turns": max(r["turns"] for r in rs),
                          "mean_seconds": round(statistics.mean(r["seconds"] for r in rs), 1),
                          "total_cost_usd": round(sum(r["cost_usd"] or 0 for r in rs), 3)}
    result = {"model": a.model, "reps": a.reps, "questions": len(QUESTIONS), "summary": summary, "runs": runs}
    (HERE / "agent-eval.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    partial.unlink(missing_ok=True)
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
