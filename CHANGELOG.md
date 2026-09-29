# Changelog

## 1.2.3 - 2026-09-29

### Changed

- Documentation only: the README's Documentation list links each page on the
  documentation site, so readers on GitHub and PyPI land there. The code is the same as 1.2.2.

## 1.2.2 - 2026-09-29

### Changed

- Documentation only: the README becomes a short entrance to the documentation site
  (https://offerrall.github.io/pycodecad/), and `docs/overview.md` holds the introduction.
- New `docs/limitations.md` gathers the platform, graphics and installation notes (from Design and
  Getting started), the mesh export limits and the embedding caveats.
- Links to the examples point to the repository on GitHub; stale version numbers, a hand-kept line
  count and provisional wording are gone; the benchmark review becomes timeless reference numbers.
- `pyproject.toml` links the documentation site. The code is the same as 1.2.1.

## 1.2.1 - 2026-09-29

- Documentation only: the benchmark notes move from `benchmarks/README.md` to
  `docs/benchmarks.md`, listed with the rest of the documentation. The code is the same as 1.2.0.

## 1.2.0 - 2026-09-27

- A folder's main file is `main.py` when it has one (else, as before, the first `.py` that
  calls `show()`). Opening a file, or making another file the main one, still chooses it.

## 1.1.0 - 2026-09-27

- Embedding (`pycodecad.embed`): an app can hide top-bar tools (`Workspace.hidden`), add its own
  buttons (`Workspace.buttons`, `Button`) and hear every save (`Workspace.on_save`), e.g. to make
  Save upload the project to a server.

## 1.0.1 - 2026-09-26

- The window says when a file the part reads (a helper module, an asset) changes on disk after a
  run, for example edited by an AI assistant: "helper.py changed on disk: Run to see it".

## 1.0.0 - 2026-09-26

First release.
