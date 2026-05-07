## Summary

- 

## Type

- [ ] Bug fix
- [ ] Feature
- [ ] Documentation
- [ ] Tests
- [ ] Refactor

## Governance Scope Check

- [ ] This fits Onion Core's lightweight LLM call governance scope.
- [ ] Public API changes are documented.
- [ ] Middleware ordering or metadata changes are covered by tests.

## Verification

Commands run:

```bash
python -m ruff check onion_core tests
python -m mypy onion_core
python -m pytest -q
```

## Notes

Known limitations, follow-up work, or migration notes.
