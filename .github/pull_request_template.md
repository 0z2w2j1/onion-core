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
ruff check .
mypy onion_core --strict
pytest
python -m build
twine check dist/*
```

## Notes

Known limitations, follow-up work, or migration notes.
