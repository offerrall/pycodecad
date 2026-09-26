# Files pycodecad writes

Everything pycodecad writes, and where. Nothing else is written: no settings, logs or caches.

| What | Where | When |
| --- | --- | --- |
| The script | `part.py` | On Save; once from a small example when you open a file that does not exist, or a folder without `.py` files (not with `--read-only`) |
| A file of the folder (a helper module) | `helper.py` | On Save, while you edit it in the window |
| A copy of the script | The name you give | On Save as |
| Last run | `.pycodecad/part.py.last-run.json` next to the script | After every run: window, `check`, `render`, `export`, `context` |
| Window camera | `.pycodecad/part.py.camera.json` next to the script | About a second after the camera stops moving in the window |
| Exports | `part.stl`, `part.3mf`... next to the script (or the name an [embedding](embedding.md) app gives) | Export in the window |
| Picture | `part.png` next to the script | Export > PNG picture of the view |
| Exports, pictures | The path you give | `pycodecad export`, `pycodecad render` |
| Temporary STL | `~/.cache/pycodecad/tmp/` (or `$XDG_CACHE_HOME/pycodecad/tmp/`) | During `import_mesh(..., solid=True)`, removed after use |

## Details

- **Saves are atomic** and keep the file's permissions: the new text is written to a temporary file
  next to the script, then replaces it in one step. Readers see the old or the new file, never a
  part of it.
- **Last run**: the JSON of [`check`](cli.md#check), replaced by every run. Long texts in it are cut
  (traceback, output, warnings, objects), so it stays small. A stopped run records "Stopped".
- **Camera**: what `render --views window` uses; also the view size.
- The **`.pycodecad/` files** are skipped silently when the script's folder is not writable (`render
  --views window` then says there is no camera).
- The window's exports and picture **overwrite** files with the same name.
- **Temporary files** left behind by a stopped run are removed the next time pycodecad starts (when
  they are more than ten minutes old).
- No `__pycache__` is written for your script or its helper modules.
- In a [folder](window.md#a-part-in-several-files), the last run, the camera, the exports and the
  picture belong to the main file (the one Run runs): `.pycodecad/gear.py.last-run.json`, `gear.stl`...

What your own script writes is up to it.
