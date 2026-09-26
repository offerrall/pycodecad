"""Parameters of exposed functions.

`expose(fn)` in a script turns the parameters of `fn` into controls in the window. Only simple
parameters, so a control can always be drawn for them: int, float, bool or str, each with a
default, annotated only with pytypehint Min, Max, Step, Slider, Label and Description. Anything
else is an error that names the parameter.

Values reach a run as a dict keyed "function.param" (or just "param"): typed values from the
window, strings from `--set` on the command line (converted here to the parameter's type).
"""
from __future__ import annotations

import inspect
import typing
from dataclasses import asdict
from typing import Literal

from pytypehint import Bool, Float, Int, Signature, Str, immutable, signature_of

Kind = Literal["int", "float", "bool", "str"]
KINDS: dict[type, Kind] = {Int: "int", Float: "float", Bool: "bool", Str: "str"}
TYPES = {"int": int, "float": float, "bool": bool, "str": str}
OPTIONS = {"int": ("min", "max", "step"), "float": ("min", "max", "step"), "str": ("min", "max"), "bool": ()}
LIMIT = 10**9  # numbers within ±LIMIT: what the window's int and float controls handle
TRUE, FALSE = ("true", "1", "yes", "on"), ("false", "0", "no", "off")


@immutable
class Param:
    """One parameter as the window draws it: only states a control can show can be built."""
    name: str
    kind: Kind
    default: int | float | bool | str
    value: int | float | bool | str   # the value the run used
    min: int | float | None = None    # for str: length
    max: int | float | None = None
    step: int | float | None = None
    slider: bool = False
    label: str | None = None
    description: str | None = None

    def __post_init__(self):
        if self.kind not in TYPES:
            return  # the field validation names the bad kind
        if not self.name.isidentifier():
            raise ValueError(f"name must be an identifier, not {self.name!r}")
        for which in ("default", "value"):
            if type(getattr(self, which)) is not TYPES[self.kind]:
                raise ValueError(f"needs a {which} of type {self.kind}")
        bound = float if self.kind == "float" else int  # str: min/max are lengths
        for option in ("min", "max", "step"):
            given = getattr(self, option)
            if given is not None and option not in OPTIONS[self.kind]:
                raise ValueError(f"{option} is not supported for {self.kind}")
            if given is not None and type(given) is not bound:
                raise ValueError(f"{option} must be of type {bound.__name__}")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError(f"min {self.min} is greater than max {self.max}")
        if self.slider and (self.min is None or self.max is None):
            raise ValueError("slider requires min and max")
        if self.kind in ("int", "float") and any(
                isinstance(v, (int, float)) and not -LIMIT <= v <= LIMIT  # checked numbers above
                for v in (self.default, self.value, self.min, self.max, self.step and self.step * 10)):
            raise ValueError("numbers must be within ±1e9 (step within ±1e8)")
        if self.step is not None and self.step < 1e-6:
            raise ValueError("Step must be at least 1e-6")
        if self.kind != "bool":
            for which in ("default", "value"):
                size = getattr(self, which)
                size = len(size) if self.kind == "str" else size
                if self.min is not None and size < self.min or self.max is not None and size > self.max:
                    raise ValueError(f"{which} {getattr(self, which)!r} is outside [{self.min}, {self.max}]")


@immutable
class Exposed:
    function: str
    params: tuple[Param, ...]

    def __post_init__(self):
        if not self.function.isidentifier():
            raise ValueError(f"function must be an identifier, not {self.function!r}")
        names = [p.name for p in self.params]
        if len(set(names)) != len(names):
            raise ValueError(f"{self.function}: parameter names repeat: {names}")


def compile_function(fn) -> tuple[Signature, list[Param]]:
    """The pytypehint signature of fn and its parameters (value = default).

    Raises TypeError naming the first parameter that is not simple.
    """
    if not inspect.isfunction(fn) or not fn.__name__.isidentifier() or inspect.iscoroutinefunction(fn):
        raise TypeError(f"expose() takes a function defined with def, not {fn!r}")
    name = fn.__name__
    try:
        signature = signature_of(fn)
    except (TypeError, ValueError, NameError) as exc:
        raise TypeError(f"expose({name}): {name_parameter(fn, str(exc))}") from None
    params = []
    for field in signature.params:
        where = f"expose({name}): parameter {field.name!r}"
        if len(field.shape) != 1 or type(field.shape[0]) not in KINDS:
            raise TypeError(f"{where}: only int, float, bool and str are supported")
        shape = field.shape[0]
        kind = KINDS[type(shape)]
        allowed = (*OPTIONS[kind], "slider") if kind in ("int", "float") else OPTIONS[kind]
        for option, value in vars(shape).items():
            if option == "_extras" and value or not option.startswith("_") and value is not None \
                    and option not in allowed:
                raise TypeError(f"{where}: {option.strip('_')} is not supported (only Min, Max, Step, "
                                "Slider, Label and Description)")
        for bound in (getattr(shape, "min", None), getattr(shape, "max", None)):
            if bound is not None and bound.exclusive:
                raise TypeError(f"{where}: exclusive Min/Max is not supported")
        low, high, step = (getattr(getattr(shape, option, None), "value", None) for option in ("min", "max", "step"))
        default = typing.cast(int | float | bool | str, field.default)  # pytypehint checked it against the shape
        try:
            if kind == "float":  # Min(20) on a float is 20.0, as the control shows it
                low, high, step = (None if v is None else float(v) for v in (low, high, step))
            params.append(Param(name=field.name, kind=kind, default=default, value=default, min=low,
                                max=high, step=step, slider=getattr(shape, "slider", None) is not None,
                                label=field.label.value if field.label else None,
                                description=field.description.value if field.description else None))
        except (TypeError, ValueError, OverflowError) as exc:
            raise TypeError(f"{where}: {exc}") from None
    return signature, params


def name_parameter(fn, message: str) -> str:
    """A pytypehint error as "parameter 'x': ...", finding x when the message does not name it."""
    parameters = inspect.signature(fn).parameters
    head, _, rest = message.partition(": ")
    if head in parameters:
        return f"parameter {head!r}: {rest}"
    try:
        hints = typing.get_type_hints(fn, include_extras=True)
    except NameError:
        return message
    def probe():
        pass

    for parameter in parameters.values():  # the same check, one parameter at a time
        probe.__signature__ = inspect.Signature([parameter])
        probe.__annotations__ = {parameter.name: hints[parameter.name]} if parameter.name in hints else {}
        try:
            signature_of(probe)
        except (TypeError, ValueError):
            return f"parameter {parameter.name!r}: {message}"
    return message


def convert(param: Param, value: object) -> object:
    """A value for param: strings (from --set) become its type, an int is a valid float;
    anything else is kept as is (and checked when the function is called)."""
    if param.kind == "float" and type(value) is int:
        return float(value)
    if not isinstance(value, str) or param.kind == "str":
        return value
    text = value.strip()
    try:
        if param.kind == "int":
            return int(text)
        if param.kind == "float":
            return float(text)
    except ValueError:
        raise ValueError(f"{param.name}: {value!r} is not a valid {param.kind}") from None
    if text.lower() in TRUE:
        return True
    if text.lower() in FALSE:
        return False
    raise ValueError(f"{param.name}: {value!r} is not a valid bool (true/false)")


def to_json(exposed: list[Exposed]) -> list[dict]:
    """The parameters as plain JSON data (for `check`, last-run files and the AI context)."""
    return [dict(function=e.function, params=[asdict(p) for p in e.params]) for e in exposed]
