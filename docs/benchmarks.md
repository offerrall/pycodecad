# Benchmarks

## Static execution and rendering

`benchmarks/pipeline.py` measures a Run and the window's drawing. Run it from the
repository root with the development environment installed:

```bash
venv/bin/python benchmarks/pipeline.py /path/to/part.py --output /tmp/part.json
venv/bin/python benchmarks/pipeline.py --instances 1000 --samples 20 --output /tmp/instances.json
```

The default synthetic scene is ten instances of one cylinder, shown once. Use
`--no-viewer` without a display. The optional `--frames` argument makes a small
synthetic animation; real scripts run unchanged. `--timeout` limits the child
execution (180 seconds by default).

The benchmark reads the model in place and redirects pycodecad's last-run report
to a temporary directory. Like a normal Run, the model executes Python code and
can have its own side effects. Run one benchmark at a time.

The JSON records:

- The initial build123d import, separately from subsequent Run time.
- Execution in the normal forked child, including time inside `show()`,
  tessellation and `frame()`. These are nested timings: do not add them together.
- Time until `Run.wait()` returns, report writing, and the remainder for fork,
  result transfer and child exit. The remainder is not pure serialization time.
- Unique mesh and triangle counts, mesh bytes and peak process RSS on Linux.
- Window creation, the first image, repeated draws of an unchanged scene and
  sampled scenes. `bbox`, upload and draw timings are nested too.
- Python version, GPU, viewport and package source hashes. `source_unchanged`
  checks whether another process edited the package during measurement.

The viewer is the actual `Viewer` in a hidden GLFW window, without vsync.
Each draw waits for the GPU, so its timing includes completion rather than only
command submission. Window creation is separate from the first image; the
regular application's event scheduling is not part of this measurement.

## Reference measurements

Linux, Python 3.12.14, AMD Radeon Graphics (Rembrandt), 800×600. These are local
measurements, not timing assertions or performance guarantees.

| Static case | Result |
| --- | --- |
| First image, 1,000 cylinder instances | 98 ms, 1,000 bounding-box calculations |
| CLI mesh preparation/upload, 1,000 cylinder instances | 1 shared mesh, 0.018 MiB, 2.5–2.8 ms |
| Report with more than 1,000 objects | Only the reported details are calculated; the full object count is kept |

A feeder model with 61 objects sharing 14 meshes executes in about 400 ms, of which
about 80 ms inside `show()`; writing its report takes about 20 ms, the rest of the
Run about 25 ms, and the first image about 40 ms. The initial build123d import
takes another 1.7 seconds. Redrawing the unchanged scene repeats no mesh uploads
and no bounding-box calculations.

What keeps these numbers low:

- CLI rendering uses the same mesh/placement representation as the window: each
  different shape is uploaded once and instances are placements, instead of a
  transformed copy (`obj.world()`) uploaded per instance. The CLI
  preparation/upload row measures that representation before drawing; it excludes
  execution, PNG encoding and context creation. A regression test compares
  translated and rotated instances against the transformed geometry in three views.
- `show()` does not use build123d's `copy.copy()`, which deep-copies the geometry.
  A small internal helper copies placements, labels, colors and assembly wrappers
  while sharing the BRep. Movement and STEP assembly metadata are checked by the
  export tests.
