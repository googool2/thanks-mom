#!/usr/bin/env python3
"""Fast checks for the naming rules that real projects tripped up. No network, runs in a second.

  python bench/test_rules.py [path/to/mom.py]
"""
import importlib.util, sys
from pathlib import Path

path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "skills" / "thanks-mom" / "scripts" / "mom.py"
spec = importlib.util.spec_from_file_location("mom", path)
mom = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mom)

# Copy-like names: only real copy suffixes, never a year in brackets or a file called "copy".
for stem, is_copy in [("report (1)", True), ("logo copy", True), ("hero-2-copy-1", True), ("x - Copy (3)", True),
                      ("Smith & Jones (2019)", False), ("copy", False), ("survey_cleaned", False)]:
    assert bool(mom.COPY.search(stem)) == is_copy, stem

# Throwaway names.
for stem, hit in [("core_old", True), ("notes.backup_2026-01-05", True), ("tmp_scan", True),
                  ("copy", False), ("template", False), ("bold", False), ("sim_v6", False)]:
    assert bool(mom.HARD.search(stem)) == hit, stem

# Versioned research scripts are not "one-off scripts".
assert not mom.SOFT.search("sim_v6_long")
assert mom.SOFT.search("test_api_quick")

# LaTeX and bibliographies are read by the reference check.
assert {".tex", ".bib", ".ipynb"} <= mom.TEXT

# ID lists and ranges round-trip.
assert mom.ids("3,7,10-12") == {3, 7, 10, 11, 12}
assert mom.spans([3, 4, 5, 9]) == "3-5,9"

print("rules ok")
