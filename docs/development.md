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
2. Publish a GitHub release tagged `v` plus that version:
   `gh release create vX.Y.Z --title vX.Y.Z --generate-notes` (or from the GitHub page).

`.github/workflows/publish.yml` checks that the tag matches the version, runs the tests and pyright,
builds the package and, only if all that passed, uploads it to PyPI with Trusted Publishing.

### When the release fails

A tag and a GitHub release can be deleted and made again; a version that reached PyPI cannot be
uploaded again, even after deleting it there. So first find the failed step:

```bash
gh run list --workflow publish.yml --limit 3     # the failed run
gh run view <run-id> --log-failed                # why it failed
```

- **Failed before the upload** (tag check, tests, pyright, build): nothing was published. Fix it,
  commit and push, then make the release again with the same version:

  ```bash
  gh release delete vX.Y.Z --cleanup-tag --yes   # deletes the release and its tag, here and on GitHub
  git tag -d vX.Y.Z 2>/dev/null                  # the local tag too, if there is one
  gh release create vX.Y.Z --title vX.Y.Z --target main --generate-notes
  ```

- **Failed in the upload** (the `publish` job): usually Trusted Publishing is not set up. On PyPI,
  add a publisher (before the first release, a "pending publisher"): project `pycodecad`, owner `offerrall`,
  repository `pycodecad`, workflow `publish.yml`, environment `pypi`. Then rerun the failed job
  (`gh run rerun <run-id> --failed`): it uploads the same files.

- **The version is already on PyPI** but something is wrong with it: do not reuse the number.
  Fix it and release the next patch version, with its CHANGELOG entry.
