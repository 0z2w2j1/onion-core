# Release Process

This checklist is for maintainers preparing an Onion Core release.

## Before Release

1. Confirm the release scope and target version.
2. Update `pyproject.toml`.
3. Update `CHANGELOG.md`.
4. Confirm new public APIs are documented.
5. Confirm beta or breaking changes have migration notes.
6. Run the local verification commands:

```bash
ruff check .
mypy onion_core --strict
pytest
python -m build
twine check dist/*
```

7. Confirm `mkdocs build --strict` passes when documentation dependencies are
   installed.

## TestPyPI Dry Run

Use TestPyPI for release candidates or packaging changes:

```bash
python -m build
twine upload --repository testpypi dist/*
```

Then install in a clean environment:

```bash
pip install --index-url https://test.pypi.org/simple/ onion-core
python -c "import onion_core; print(onion_core.__version__)"
```

## GitHub Release

1. Create a signed or normal tag:

```bash
git tag v1.1.0
git push origin v1.1.0
```

2. Create a GitHub Release for the tag.
3. Paste the changelog section into the release notes.
4. Mark pre-releases clearly when the version contains `a`, `b`, or `rc`.

## PyPI Publish

The preferred path is GitHub Actions trusted publishing. Configure PyPI trusted
publishing for this repository before enabling automatic release publication.

If publishing manually:

```bash
python -m build
twine check dist/*
twine upload dist/*
```

## After Release

1. Verify the PyPI page renders the README correctly.
2. Install the release in a clean environment.
3. Run the quick-start example against the published package.
4. Confirm documentation links point to the released behavior.
5. Open follow-up issues for deferred work.

## Release Quality Bar

A release should not ship when:

- tests fail
- `ruff` or `mypy --strict` fails
- package build fails
- docs for new public APIs are missing
- known security or cache isolation issues are unresolved
- a breaking change lacks migration guidance
