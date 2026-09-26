"""The modeling API: show(), clear(), frame(), import_mesh() and expose().

While pycodecad runs a script, `scene` is the list that show() fills, `frames` the scenes frame()
saved and `values` the parameter values of exposed functions. Outside pycodecad (plain
`python script.py`) scene is None: show()/clear()/frame() do nothing and expose() calls the
function with its defaults, so scripts still run.
"""
from __future__ import annotations

from dataclasses import replace

from .cad import Mesh, Shown, copy_shape, flatten, import_mesh, parse_color, placed

__all__ = ["show", "clear", "frame", "import_mesh", "expose"]

scene: list[Shown] | None = None
frames: list[list[Shown]] = []
FPS = 30                         # frames per second of the animation
values: dict[str, object] = {}   # "function.param" or "param" -> value, set by the runner
used: set[str] = set()           # keys of `values` some expose() took
exposed: list = []               # params.Exposed, in call order
strict = True                    # False (the window): values the parameter no longer accepts are skipped


def show(*objs: object, name: str | None = None, color: object = None) -> None:
    """Add build123d shapes, builders or meshes (or lists of them) to the scene.

    name: label of the object (numbered when several objects are passed).
    color: "#RRGGBB", a basic name like "red", or an RGB triple (0..1 or 0..255).
    """
    if scene is None:
        return
    if name is not None and not isinstance(name, str):
        raise TypeError(f"show() name must be a string, not {type(name).__name__}")
    shapes = flatten(list(objs))
    for number, shape in enumerate(shapes, start=1):
        index = len(scene)
        if name is None:
            label = f"{type(shape).__name__} {index + 1}"
        else:
            label = name if len(shapes) == 1 else f"{name}_{number}"
        mesh, matrix, volume = placed(shape)
        source = shape if isinstance(shape, Mesh) else copy_shape(shape)  # later moves: not this placement
        scene.append(Shown(label, parse_color(color, index), mesh, volume, source, matrix))


def clear() -> None:
    """Remove everything shown so far."""
    if scene is not None:
        scene.clear()


def frame() -> None:
    """Save the scene as it is now as the next frame of an animation (1/30 s each). The window plays
    the frames; without any frame() the scene is a still one. The scene stays: clear() it yourself."""
    if scene is not None:
        frames.append([Shown(obj.name, obj.color, obj.mesh, obj.volume, None, obj.matrix) for obj in scene])


def expose(fn):
    """Call fn with the values of its parameters: from the window's controls (or `--set` on
    the command line), otherwise its defaults. Returns what fn returns.

    Only simple parameters: int, float, bool or str with a default, annotated with pytypehint
    Min, Max, Step, Slider, Label and Description. Anything else raises TypeError.
    """
    from . import params

    signature, found = params.compile_function(fn)
    name = fn.__name__
    if scene is not None and any(e.function == name for e in exposed):
        raise ValueError(f"expose({name}) was already called in this run")
    chosen = {}
    try:
        for param in found:
            keys = [key for key in (f"{name}.{param.name}", param.name) if key in values]
            if keys:  # "function.param" wins over "param"; both count as taken
                used.update(keys)
                if strict:
                    chosen[param.name] = params.convert(param, values[keys[0]])
                elif (value := accepted(signature, param, values[keys[0]])) is not None:
                    chosen[param.name] = value  # else the edited script no longer accepts it: default
        kwargs = signature.build(chosen)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"expose({name}): {params.name_parameter(fn, str(exc))}") from None
    if scene is not None:  # plain python: nothing to show the parameters to
        ran = []
        for param in found:
            try:
                ran.append(replace(param, value=kwargs[param.name]))
            except ValueError as exc:  # e.g. --set beyond what the window's controls handle
                raise ValueError(f"expose({name}): parameter {param.name!r}: {exc}") from None
        exposed.append(params.Exposed(function=name, params=tuple(ran)))
    return fn(**kwargs)


def accepted(signature, param, value: object) -> object | None:
    """The value for param, or None when param does not accept it (any more)."""
    if type(value) is not {"int": int, "float": float, "bool": bool, "str": str}[param.kind]:
        return None  # the window sends values of the kind the parameter had: another kind is stale
    try:
        signature.build({param.name: value})
    except (TypeError, ValueError):
        return None
    return value
