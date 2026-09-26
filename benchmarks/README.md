# Static execution and rendering

Run from the repository root with the development environment installed:

```sh
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

## Review on 2026-09-26

Linux, Python 3.12.14, AMD Radeon Graphics (Rembrandt), 800×600. These are local
measurements, not timing assertions or performance guarantees.

| Static case | Before | After |
| --- | --- | --- |
| First image, 1,000 cylinder instances | 154 ms, 2,000 bounding-box calculations | 98 ms, 1,000 calculations |
| CLI mesh preparation/upload, 1,000 cylinder instances | 1,000 meshes, 18 MiB, 76–170 ms | 1 shared mesh, 0.018 MiB, 2.5–2.8 ms |
| Report with more than 1,000 objects | Calculates all details, then truncates | Calculates only the reported details; keeps the full object count |

The owner's static feeder model had 61 objects sharing 14 meshes. The initial
measurement took 421 ms to execute, 21 ms to write its report and 25 ms for the
remaining Run overhead, followed by a 38 ms first image. Initial build123d import
took another 1.7 seconds. Later wall times varied with desktop activity; the
bounding-box calls fell from 122 to 61 and there were no repeated mesh uploads
or bounding-box calculations while redrawing the unchanged scene.

CLI rendering now preserves the same mesh/placement representation used by the
window. The former path first materialized `obj.world()` for every instance and
uploaded each copy. The CLI preparation/upload comparison measures those two
representations before drawing; it excludes execution, PNG encoding and context
creation. The regression test compares translated and rotated instances against
the corresponding transformed geometry in three views.

The subsequent shape-copy change removes the deep geometry copy hidden inside
build123d's `copy.copy()`. A small internal helper copies placements, labels,
colors and assembly wrappers while sharing the BRep. With the feeder model,
two alternating measurements of each implementation gave 437–441 ms execution
with the former copy and 394–401 ms with the new one; time inside `show()` fell
from 124–127 ms to about 80 ms. Both produced 61 objects sharing 14 meshes.
Movement and STEP assembly metadata are checked by the export tests.
