# Standard layouts

Pick the closest one. Move only what has a clear home; anything else stays put.

## Agent / AI project (most common target)
```
CLAUDE.md          short rules + pointer to PROJECT_MAP.md
PROJECT_MAP.md     folder map (written by Thanks Mom)
README.md
src/ or app/       the actual code
tests/
tools/             reusable scripts agents call (one per job, take args)
prompts/           prompt templates
docs/              plans, specs, decisions  (docs/plans/, docs/notes/ if many)
data/              small inputs; big or raw data in data/raw/ (gitignored)
.claude/           skills, commands, settings
.scratch/          throwaway work (gitignored)
```

## Python
```
pyproject.toml | requirements.txt
src/<package>/     __init__.py, modules
tests/             test_*.py
scripts/           entry-point scripts, if not using [project.scripts]
```

## Node / web
```
package.json + lockfile
src/               (components/, lib/, routes/ ...)
public/ or static/ files served as-is
tests/ or __tests__/
```

## Full stack in one repo
```
frontend/   (own package.json)
backend/    (own pyproject / package.json)
shared/     only if both sides import it
docs/  tools/  .scratch/
```

## Moving code safely
1. `git mv` one group at a time.
2. grep the old path everywhere: imports, package.json scripts, Dockerfile, CI, docs, `.env.example`.
3. Run tests after each group, not at the end.
4. Entry points that a host or CI calls by path (`main.py`, `server.js`, `manage.py`): leave them where they are unless you update every caller.
