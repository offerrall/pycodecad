# Changelog

## 1.2.1

- Documentation only: the benchmark notes move from `benchmarks/README.md` to
  `docs/benchmarks.md`, listed with the rest of the documentation. The code is the same as 1.2.0.

## 1.2.0

- A folder's main file is `main.py` when it has one (else, as before, the first `.py` that
  calls `show()`). Opening a file, or making another file the main one, still chooses it.

## 1.1.0

- Embedding (`pycodecad.embed`): an app can hide top-bar tools (`Workspace.hidden`), add its own
  buttons (`Workspace.buttons`, `Button`) and hear every save (`Workspace.on_save`), e.g. to make
  Save upload the project to a server.

## 1.0.1

- The window says when a file the part reads (a helper module, an asset) changes on disk after a
  run, for example edited by an AI assistant: "helper.py changed on disk: Run to see it".

## 1.0.0

First release.
