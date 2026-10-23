## What and why

<!-- One or two sentences. Link the issue if there is one. -->

## Checklist

- [ ] `python bench/test_rules.py` and `python bench/test_commands.py` pass
- [ ] `python bench/bench.py` passes (if behavior changed)
- [ ] A test or trap covers the change (required for wrong-decision fixes)
- [ ] No safety rule got looser. If one did, it's a major version and the CHANGELOG says so
- [ ] CHANGELOG entry added
- [ ] No real or private data in fixtures or examples
