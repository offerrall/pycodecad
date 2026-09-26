# Development

```bash
git clone https://github.com/offerrall/pycodecad
cd pycodecad
python -m venv venv
venv/bin/pip install -e . pytest
venv/bin/python -m pytest -q
```

Rendering tests need an off-screen OpenGL context and window tests a display; without them they are
skipped. `pyright` in the repository root must report 0 errors and 0 warnings.

## Releasing

1. Set the version in `src/pycodecad/__init__.py` and add its entry to `CHANGELOG.md`.
2. Publish a GitHub release tagged `v` plus that version (for example `v1.0.0`).

`.github/workflows/publish.yml` checks that the tag matches the version, runs the tests and pyright,
builds the package and uploads it to PyPI with Trusted Publishing. Nothing is published if a step fails.
