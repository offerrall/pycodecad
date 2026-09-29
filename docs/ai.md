# Working with an AI assistant

pycodecad is built so an AI assistant can work on a part the same way you do: it edits the file, runs
it from a terminal and looks at the result. You keep the window open and decide when to reload.

## 1. Give it the context

Click **Copy AI context** in the window (or run `pycodecad context part.py`) and paste the text into
your assistant. It contains:

- the script's path and the files in its folder, with sizes (two levels deep, up to 60 files;
  hidden files, `venv`, `.venv`, `node_modules` and `__pycache__` skipped),
- the current state: each object with its size, center and volume, the error with its file and
  line, warnings and what the script printed,
- the exposed parameters and the values of the last run,
- how pycodecad runs scripts, the commands below, the pycodecad API (with a link to these docs) and
  a short build123d guide.

`pycodecad context` runs the script fresh to get the state; the window's button uses the window's
last run. On Windows the generated commands are for PowerShell, including quoted executable paths.

## 2. It edits and checks

The assistant edits the file directly and checks its work without a window:

```bash
pycodecad check part.py                                   # JSON: ok, error, where, objects...
pycodecad render part.py out.png --views iso,front,top,right   # then it looks at out.png
pycodecad render part.py out.png --views window           # exactly what you see in the window
pycodecad render part.py out.png --set width=80           # other values for expose()
```

With `--views iso,front,top,right` the assistant sees the part from four labeled views in one
picture ([Command line](cli.md#render) shows one).

Every run, in the window or from the command line, also leaves its result in
`.pycodecad/part.py.last-run.json` next to the script (the JSON of `check`), so the assistant can
read the latest error, including one from your last Run in the window. See [Files](files.md).

## 3. You reload

The window never reloads by itself. When the assistant saves the file, the top bar says **Changed
on disk**: press **Reload**, then **Run**. If you had unsaved edits, the notice warns that Reload
replaces them. See [The window](window.md#saving-and-changes-on-disk).

## Tips

- Keep one part per folder with its helper modules and assets, and use relative paths: the
  assistant sees the folder listing and the commands work from that folder
  ([Scripts](scripts.md#folders-helper-modules-and-assets)).
- Ask for parameters with `expose()` for measures you will change often
  ([Parameters](parameters.md)).
- Move the view in the window to what you want to discuss before the assistant runs
  `render --views window`.
