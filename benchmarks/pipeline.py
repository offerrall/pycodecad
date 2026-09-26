"""Measure Run, result delivery and the real Viewer, one Linux process at a time.

    venv/bin/python benchmarks/pipeline.py /path/to/part.py --output /tmp/part.json
    venv/bin/python benchmarks/pipeline.py --instances 100 --frames 30

The model is read in place. Last-run metadata goes to a temporary directory.
Viewer measurements use a hidden window, no vsync, and wait for the GPU.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import resource
import statistics
import sys
import tempfile
import time
from contextlib import ExitStack
from pathlib import Path
from typing import Any
from unittest.mock import patch


def measured(function, metrics, name):
    def call(*args, **kwargs):
        start = time.perf_counter()
        try:
            return function(*args, **kwargs)
        finally:
            metrics[name + "_s"] = metrics.get(name + "_s", 0.0) + time.perf_counter() - start
            metrics[name + "_calls"] = metrics.get(name + "_calls", 0) + 1
    return call


def synthetic(instances, frames):
    return f"""from build123d import Cylinder, Pos
from pycodecad import show, clear, frame
part = Cylinder(4, 10)
for f in range({frames}):
    clear()
    for i in range({instances}):
        show(Pos((i % 10) * 12, (i // 10) * 12, f * 0.1) * part)
    if {frames} > 1:
        frame()
"""


def run_model(code, filename, timeout):
    from pycodecad import api, cad, runner

    start = time.perf_counter()
    runner.preload()
    metrics: dict[str, Any] = {"preload_s": time.perf_counter() - start}
    execute = runner.execute

    def instrumented(*args, **kwargs):
        child = {}
        with ExitStack() as stack:
            for module, name in ((api, "show"), (api, "frame"), (cad, "tessellate")):
                stack.enter_context(patch.object(module, name, measured(getattr(module, name), child, name)))
            result = execute(*args, **kwargs)
        child["peak_rss_mib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
        setattr(result, "_benchmark", child)
        return result

    write = runner.write_last_run
    with tempfile.TemporaryDirectory(prefix="pycodecad-benchmark-") as folder:
        def last_run(original, result):
            write(str(Path(folder) / Path(original).name), result)

        with patch.object(runner, "execute", instrumented), \
                patch.object(runner, "write_last_run", measured(last_run, metrics, "last_run")):
            start = time.perf_counter()
            run = runner.Run(code, filename)
            try:
                result = run.wait(timeout)
            except BaseException:
                run.kill()
                run.wait(10)
                raise
            metrics["run_to_ready_s"] = time.perf_counter() - start
    if result.error:
        raise RuntimeError(result.error)
    metrics["execute_s"] = result.duration
    metrics["fork_transfer_exit_s"] = metrics["run_to_ready_s"] - result.duration - metrics.get("last_run_s", 0)
    metrics["child"] = getattr(result, "_benchmark", {})
    return result, metrics


def distribution(values):
    ordered = sorted(values)
    return {"median_ms": statistics.median(ordered) * 1000,
            "p95_ms": ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))] * 1000,
            "max_ms": max(ordered) * 1000}


def view_result(result, samples):
    from slimgui import imgui
    from pycodecad.cad import Shown
    from pycodecad.embed import Viewer, create_window
    from pycodecad.renderer import Renderer

    start = time.perf_counter()
    host = create_window("pycodecad benchmark", size=(900, 700), visible=False)
    window_seconds = time.perf_counter() - start
    viewer = Viewer()
    totals = {}
    draw = Renderer.draw

    def gpu_draw(self, *args, **kwargs):
        texture = draw(self, *args, **kwargs)
        self.ctx.finish()
        return texture

    def draw_frame(objects):
        start = time.perf_counter()
        host.timeout = 0.0
        if not host.frame():
            raise RuntimeError("Benchmark window closed")
        imgui.set_next_window_pos((0, 0))
        imgui.set_next_window_size((900, 700))
        imgui.begin("Preview")
        viewer.draw(objects, (800.0, 600.0))
        imgui.end()
        host.finish()
        host.ctx.finish()
        return time.perf_counter() - start

    try:
        with ExitStack() as stack:
            for cls, name, label in ((Shown, "bbox", "bbox"), (Renderer, "set_meshes", "set_meshes"),
                                     (Renderer, "_upload", "upload")):
                stack.enter_context(patch.object(cls, name, measured(getattr(cls, name), totals, label)))
            stack.enter_context(patch.object(Renderer, "draw", measured(gpu_draw, totals, "gpu_draw")))
            scenes = result.frames or [result.shown]
            first = draw_frame(scenes[0])
            first_metrics = dict(totals)
            totals.clear()
            warm = [draw_frame(scenes[0]) for _ in range(5)]
            steady_metrics = dict(totals)
            totals.clear()
            # Sample across the whole animation, including changes of object count and laser state.
            times = [draw_frame(scenes[(i * len(scenes) // samples) % len(scenes)])
                     for i in range(1, samples + 1)]
            return {"window_s": window_seconds, "gpu": host.ctx.info["GL_RENDERER"],
                    "viewport": list(viewer.size), "first_frame_s": first, "first": first_metrics,
                    "steady": distribution(warm), "steady_work": steady_metrics,
                    "sample_count": samples, "sampled_frames": distribution(times),
                    "sampled_work": dict(totals)}
    finally:
        host.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("script", type=Path, nargs="?")
    parser.add_argument("--instances", type=int, default=10, help="synthetic scene size, without a script")
    parser.add_argument("--frames", type=int, default=1, help="synthetic frame count")
    parser.add_argument("--samples", type=int, default=60, help="viewer frames sampled across the animation")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--no-viewer", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if min(args.instances, args.frames, args.samples) < 1 or args.timeout <= 0:
        parser.error("counts and timeout must be positive")
    if sys.platform != "linux":
        parser.error("this benchmark measures Linux fork and RSS")
    from pycodecad import runner

    filename = str(args.script.resolve()) if args.script else "/tmp/pycodecad-benchmark-scene.py"
    code = args.script.read_text() if args.script else synthetic(args.instances, args.frames)
    source_folder = Path(runner.__file__).parent
    signatures = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in source_folder.glob("*.py")}
    result, timings = run_model(code, filename, args.timeout)
    print(f"Run ready: {timings['run_to_ready_s']:.3f} s; {len(result.frames)} frames", file=sys.stderr, flush=True)
    meshes = {id(obj.mesh): obj.mesh for scene in [result.shown, *result.frames] for obj in scene}
    data = {"python": platform.python_version(), "script": filename, "source_sha256": signatures,
            "model_sha256": hashlib.sha256(code.encode()).hexdigest(),
            "objects": len(result.shown), "frames": len(result.frames), "unique_meshes": len(meshes),
            "unique_triangles": sum(len(m.positions) // 3 for m in meshes.values()),
            "unique_mesh_mib": sum(a.nbytes for m in meshes.values() for a in (m.positions, m.normals, m.edges)) / 2**20,
            "pipeline": timings}
    if not args.no_viewer:
        data["viewer"] = view_result(result, args.samples)
    data["parent_peak_rss_mib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    data["source_unchanged"] = all(hashlib.sha256((source_folder / n).read_bytes()).hexdigest() == h
                                   for n, h in signatures.items())
    text = json.dumps(data, indent=2)
    if args.output:
        args.output.write_text(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
