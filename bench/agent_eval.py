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
import argparse, json, shutil, statistics, subprocess, sys, time
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
POINTER = """## Project map & house rules
- Read PROJECT_MAP.md before searching for files.
- Reusable helpers live in tools/ (listed in PROJECT_MAP.md). Use or extend one before writing a new script.
- Throwaway scripts go in .scratch/ (gitignored), never the project root.
"""


def source(name, hint):
    return (f"// {hint}\nimport {{ log }} from '../log';\n\nexport function {name}(input: any) {{\n"
            f"  log('{name}');\n  // {hint}\n  return input;\n}}\n") if name else "# infra\n"


def build(root, state):
    if root.exists():
        shutil.rmtree(root)
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
    if state == "mapped":
        (root / "PROJECT_MAP.md").write_text(MAP, encoding="utf-8")
        (root / "CLAUDE.md").write_text(POINTER, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=root)
    subprocess.run(["git", "add", "-A"], cwd=root)
    subprocess.run(["git", "-c", "user.email=e@example.com", "-c", "user.name=e", "commit", "-qm", "state"], cwd=root)


def ask(root, question, model):
    claude = shutil.which("claude")
    prompt = f"{question} Reply with only the file path relative to the project root, nothing else."
    t = time.perf_counter()
    r = subprocess.run([claude, "-p", prompt, "--output-format", "json", "--model", model, "--setting-sources", "project",
                        "--strict-mcp-config", "--no-session-persistence", "--allowedTools", "Read", "Glob", "Grep",
                        "--disallowedTools", "Bash", "Edit", "Write", "NotebookEdit", "WebFetch", "WebSearch", "Task", "Agent"],
                       cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
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
    a = ap.parse_args()
    work = Path(a.workdir).resolve()
    runs = []
    for state in ("messy", "clean", "mapped"):
        root = work / state
        build(root, state)
        for rep in range(a.reps):
            for q, want in QUESTIONS:
                res = ask(root, q, a.model)
                res.update(state=state, question=q, rep=rep,
                           correct=want in res.get("answer", "").replace("\\", "/") and "backup/" not in res.get("answer", ""))
                runs.append(res)
                print(f"{state:7} {rep} {'OK ' if res['correct'] else 'BAD'} turns={res.get('turns')} tokens={res.get('tokens')} "
                      f"{res.get('answer', res.get('error', ''))[:70]}", flush=True)
        shutil.rmtree(root)
    summary = {}
    for state in ("messy", "clean", "mapped"):
        rs = [r for r in runs if r["state"] == state and "error" not in r]
        summary[state] = {"runs": len(rs), "correct_pct": round(100 * sum(r["correct"] for r in rs) / max(len(rs), 1), 1),
                          "median_turns": statistics.median(r["turns"] for r in rs),
                          "median_tokens": statistics.median(r["tokens"] for r in rs),
                          "median_seconds": statistics.median(r["seconds"] for r in rs),
                          "total_cost_usd": round(sum(r["cost_usd"] or 0 for r in rs), 3)}
    result = {"model": a.model, "reps": a.reps, "questions": len(QUESTIONS), "summary": summary, "runs": runs}
    (HERE / "agent-eval.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
