"""expose(): parameters of exposed functions, their values and how a run reports them."""
import dataclasses
import datetime
import enum
import json
import re
import subprocess
import sys
from typing import Annotated, Literal, Optional

import pytest
from pytypehint import (Choices, Description, Extra, FileHint, IsPassword, Label, Max, Min, MultipleOf, Pattern,
                        Placeholder, Rows, Slider, Step)

from pycodecad import api, runner
from pycodecad.params import Exposed, Param, compile_function, convert, to_json


def box(width: Annotated[float, Min(20), Max(200.0), Slider(), Label("Width"), Description("Outside")] = 60.0,
        height: Annotated[int, Min(5), Step(5)] = 30, hollow: bool = False, text: Annotated[str, Max(8)] = "hi"):
    return width, height, hollow, text


def test_simple_parameters_are_accepted():
    signature, params = compile_function(box)
    assert signature.name == "box"
    assert params == [
        Param(name="width", kind="float", default=60.0, value=60.0, min=20.0, max=200.0, slider=True,
              label="Width", description="Outside"),
        Param(name="height", kind="int", default=30, value=30, min=5, step=5),
        Param(name="hollow", kind="bool", default=False, value=False),
        Param(name="text", kind="str", default="hi", value="hi", max=8),
    ]
    assert type(params[0].min) is float  # Min(20) on a float is 20.0


def test_keyword_only_and_no_parameters_are_accepted():
    def kw(*, size: Annotated[float, Step(1)] = 2.0):
        pass

    def nothing():
        pass

    assert compile_function(kw)[1] == [Param(name="size", kind="float", default=2.0, value=2.0, step=1.0)]
    assert compile_function(nothing)[1] == []


class Color(enum.Enum):
    RED = 1


@dataclasses.dataclass
class Size:
    x: int = 1


def f_list(a: list[int] = [1]): pass                            # noqa: B006, E704
def f_union(a: int | float = 1): pass                           # noqa: E704
def f_optional(a: Optional[int] = None): pass                   # noqa: E704
def f_enum(a: Color = Color.RED): pass                          # noqa: E704
def f_date(a: datetime.date = datetime.date(2026, 1, 1)): pass  # noqa: E704
def f_dataclass(a: Size = Size()): pass                         # noqa: B008, E704
def f_tuple(a: tuple[int, int] = (1, 2)): pass                  # noqa: E704
def f_literal(a: Literal["x", "y"] = "x"): pass                 # noqa: E704
def f_no_default(a: int): pass                                  # noqa: E704
def f_no_hint(a=1): pass                                        # noqa: E704
def f_args(*a: int): pass                                       # noqa: E704
def f_kwargs(**a: int): pass                                    # noqa: E704
def f_positional(a: int = 1, /): pass                           # noqa: E704
def f_choices(a: Annotated[int, Choices(values=(1, 2))] = 1): pass  # noqa: E704
def f_pattern(a: Annotated[str, Pattern("x+")] = "x"): pass     # noqa: E704
def f_multiple(a: Annotated[int, MultipleOf(2)] = 2): pass      # noqa: E704
def f_placeholder(a: Annotated[int, Placeholder("n")] = 1): pass  # noqa: E704
def f_extra(a: Annotated[int, Extra("my.key", "v")] = 1): pass  # noqa: E704
def f_password(a: Annotated[str, IsPassword()] = "x"): pass     # noqa: E704
def f_rows(a: Annotated[str, Rows(3)] = "x"): pass              # noqa: E704
def f_file(a: Annotated[str, FileHint()] = "x"): pass           # noqa: E704
def f_exclusive(a: Annotated[int, Min(0, exclusive=True)] = 1): pass  # noqa: E704
def f_slider(a: Annotated[int, Slider()] = 1): pass             # noqa: E704
def f_slider_min(a: Annotated[float, Min(0), Slider()] = 1.0): pass  # noqa: E704
def f_str_step(a: Annotated[str, Step(1)] = "x"): pass          # noqa: E704
def f_bool_min(a: Annotated[bool, Min(1)] = True): pass         # noqa: E704
def f_float_int(a: float = 1): pass                             # noqa: E704
def f_int_bool(a: int = True): pass                             # noqa: E704
def f_bool_int(a: bool = 1): pass  # noqa: E704  # pyright: ignore[reportArgumentType]
def f_nan(a: float = float("nan")): pass                        # noqa: E704
def f_outside(a: Annotated[int, Min(5)] = 1): pass              # noqa: E704
def f_short(a: Annotated[str, Min(3)] = "x"): pass              # noqa: E704


@pytest.mark.parametrize("fn, reason", [
    (f_list, "only int, float, bool and str"), (f_union, "only int, float, bool and str"),
    (f_optional, "only int, float, bool and str"), (f_enum, "only int, float, bool and str"),
    (f_date, "only int, float, bool and str"), (f_dataclass, "only int, float, bool and str"),
    (f_tuple, "only int, float, bool and str"), (f_literal, "choices is not supported"),
    (f_no_default, "needs a default of type int"), (f_no_hint, "missing type hint"),
    (f_args, "variadic"), (f_kwargs, "variadic"), (f_positional, "positional-only"),
    (f_choices, "choices is not supported"), (f_pattern, "pattern is not supported"),
    (f_multiple, "multiple_of is not supported"), (f_placeholder, "placeholder is not supported"),
    (f_extra, "extras is not supported"), (f_password, "is_password is not supported"),
    (f_rows, "rows is not supported"), (f_file, "file_hint is not supported"),
    (f_exclusive, "exclusive"), (f_slider, "slider requires min and max"),
    (f_slider_min, "slider requires min and max"), (f_str_step, "unsupported metadata for str"),
    (f_bool_min, "unsupported metadata for bool"), (f_float_int, "expected float, got int"),
    (f_int_bool, "expected int, got bool"), (f_bool_int, "expected bool, got int"),
    (f_nan, "not finite"), (f_outside, "too small"), (f_short, "too short"),
])
def test_anything_else_is_a_type_error_naming_the_parameter(fn, reason):
    with pytest.raises(TypeError) as error:
        compile_function(fn)
    assert str(error.value).startswith(f"expose({fn.__name__}): parameter 'a': ")
    assert reason in str(error.value)


def test_only_functions_defined_with_def():
    async def later(a: int = 1):
        pass

    class Part:
        def make(self, a: int = 1):
            pass

    for thing in (lambda a=1: a, print, Color, Part().make, later, 3):
        with pytest.raises(TypeError, match=r"expose\(\) takes a function defined with def"):
            compile_function(thing)
    with pytest.raises(TypeError, match="'self'"):
        compile_function(Part.make)


def test_an_undefined_annotation_is_a_type_error():
    def f(a: "Undefined" = 1):  # noqa: F821  # pyright: ignore[reportUndefinedVariable]
        pass

    with pytest.raises(TypeError, match=r"expose\(f\): name 'Undefined' is not defined"):
        compile_function(f)


PARAMS = {p.kind: p for p in (Param(name="p", kind="int", default=1, value=1),
                              Param(name="p", kind="float", default=1.0, value=1.0),
                              Param(name="p", kind="bool", default=False, value=False),
                              Param(name="p", kind="str", default="", value=""))}


@pytest.mark.parametrize("kind, text, value", [
    ("int", "42", 42), ("int", " -3 ", -3), ("float", "2.5", 2.5), ("float", "80", 80.0),
    ("str", " hi there ", " hi there "), ("str", "", ""),
    *[("bool", text, True) for text in ("true", "True", "1", "yes", "on", " ON ")],
    *[("bool", text, False) for text in ("false", "FALSE", "0", "no", "off")],
])
def test_convert_strings_to_the_parameter_type(kind, text, value):
    converted = convert(PARAMS[kind], text)
    assert converted == value and type(converted) is type(value)


@pytest.mark.parametrize("kind, text", [("int", "2.5"), ("int", "x"), ("int", ""), ("float", "wide"),
                                        ("bool", "maybe"), ("bool", "")])
def test_convert_bad_strings(kind, text):
    with pytest.raises(ValueError, match=f"p: {text!r} is not a valid {kind}"):
        convert(PARAMS[kind], text)


def test_convert_keeps_typed_values_and_an_int_is_a_float():
    assert convert(PARAMS["float"], 3) == 3.0 and type(convert(PARAMS["float"], 3)) is float
    for kind, value in (("int", 7), ("float", 7.5), ("bool", True), ("str", "x"), ("int", 2.0), ("bool", 1)):
        assert convert(PARAMS[kind], value) is value  # a wrong type is refused when the function is called


def test_to_json():
    exposed = [Exposed(function="box", params=tuple(compile_function(box)[1]))]
    data = to_json(exposed)
    assert json.loads(json.dumps(data)) == data
    assert data[0]["function"] == "box"
    assert data[0]["params"][0] == dict(name="width", kind="float", default=60.0, value=60.0, min=20.0, max=200.0,
                                        step=None, slider=True, label="Width", description="Outside")


@pytest.mark.parametrize("fields, message", [
    (dict(kind="int", default=1.0), "needs a default of type int"),
    (dict(kind="int", default=True), "needs a default of type int"),
    (dict(kind="float", default=1.0), "needs a value of type float"),
    (dict(kind="float", default=1.0, value=1.0, min=1), "min must be of type float"),
    (dict(kind="str", default="x", value="x", max=2.0), "max must be of type int"),
    (dict(kind="str", default="x", value="x", step=1), "step is not supported for str"),
    (dict(kind="bool", default=True, value=True, min=0), "min is not supported for bool"),
    (dict(min=5, max=1), "min 5 is greater than max 1"),
    (dict(min=0, slider=True), "slider requires min and max"),
    (dict(default=10**9 + 1), "within ±1e9"),
    (dict(value=-10**9 - 1), "within ±1e9"),
    (dict(max=10**10), "within ±1e9"),
    (dict(step=10**8 + 1), "step within ±1e8"),
    (dict(kind="float", default=1.0, value=1.0, step=1e-7), "Step must be at least 1e-6"),
    (dict(step=0), "Step must be at least 1e-6"),
    (dict(value=11, max=10), "value 11 is outside [None, 10]"),
    (dict(default=0, min=1), "default 0 is outside [1, None]"),
    (dict(kind="str", default="abc", value="abc", max=2), "default 'abc' is outside"),
    (dict(kind="str", default="", value="", min=1), "outside [1, None]"),
    (dict(name="not a name"), "name must be an identifier"),
])
def test_invalid_params_cannot_be_built(fields, message):
    fields = dict(name="p", kind="int", default=1, value=1) | fields
    with pytest.raises(ValueError, match=re.escape(message)):
        Param(**fields)


def test_param_field_types_are_exact():
    for fields in (dict(kind="text"), dict(value=float("nan"), kind="float", default=1.0), dict(slider=1),
                   dict(label=3)):
        with pytest.raises((TypeError, ValueError)):
            Param(**dict(name="p", kind="int", default=1, value=1) | fields)  # pyright: ignore[reportArgumentType]
    with pytest.raises(TypeError):
        Param("p", "int", 1, 1)  # pyright: ignore[reportCallIssue]  # keyword-only
    param = Param(name="p", kind="int", default=1, value=1, max=5)
    with pytest.raises(ValueError, match="outside"):
        dataclasses.replace(param, value=6)
    with pytest.raises(dataclasses.FrozenInstanceError):
        param.value = 6  # pyright: ignore[reportAttributeAccessIssue]


def test_invalid_exposed_cannot_be_built():
    p = Param(name="p", kind="int", default=1, value=1)
    assert Exposed(function="box", params=(p,)).params == (p,)
    with pytest.raises(ValueError, match="function must be an identifier"):
        Exposed(function="a box", params=())
    with pytest.raises(ValueError, match="parameter names repeat"):
        Exposed(function="box", params=(p, p))
    with pytest.raises(TypeError):
        Exposed(function="box", params=[p])  # pyright: ignore[reportArgumentType]


def test_a_set_value_beyond_the_controls_is_an_error_naming_the_parameter():
    result = run(BOX, {"height": str(10**9 + 1)})
    assert (result.error or "").endswith("ValueError: expose(box): parameter 'height': numbers must be within ±1e9 "
                                 "(step within ±1e8)")


# --- expose() in a run ----------------------------------------------------------------------

HEAD = ("from typing import Annotated\nfrom pytypehint import Min, Max\nfrom pycodecad import expose\n"
        "def box(width: Annotated[float, Min(20.0), Max(200.0)] = 60.0, height: int = 30, hollow: bool = False,"
        " text: str = 'hi'):\n    print(width, height, hollow, text)\n")
BOX = HEAD + "expose(box)\n"


def run(code, values=None, strict=True, filename="<editor>"):
    return runner.Run(code, str(filename), values=values, strict=strict).wait(60)


def used(result):
    return {p.name: p.value for e in result.parameters for p in e.params}


def test_defaults_without_values():
    result = run(BOX)
    assert result.error is None and result.stdout == "60.0 30 False hi\n"
    [exposed] = result.parameters
    assert exposed.function == "box" and [p.name for p in exposed.params] == ["width", "height", "hollow", "text"]


def test_typed_values_and_strings_by_param_or_function_param():
    result = run(BOX, {"width": 80.0, "box.hollow": True, "text": "yo"})
    assert result.error is None and result.stdout == "80.0 30 True yo\n"
    result = run(BOX, {"box.width": "90", "height": "12", "hollow": "yes"})
    assert result.error is None and result.stdout == "90.0 12 True hi\n"
    assert used(result) == dict(width=90.0, height=12, hollow=True, text="hi")


def test_function_param_wins_over_param():
    result = run(BOX, {"width": "30", "box.width": "40"})
    assert result.error is None and result.stdout == "40.0 30 False hi\n"


def test_a_plain_param_reaches_every_exposed_function():
    code = HEAD + "def lid(width: float = 1.0):\n    print('lid', width)\nexpose(box)\nexpose(lid)\n"
    result = run(code, {"width": "50", "lid.width": "5"})
    assert result.error is None and result.stdout == "50.0 30 False hi\nlid 5.0\n"
    assert [e.function for e in result.parameters] == ["box", "lid"]


def test_unknown_key_is_an_error_only_when_strict():
    result = run(BOX, {"widht": "80", "lid.width": "1", "width": "70"})
    assert (result.error or "").endswith("ValueError: No exposed parameter lid.width, widht (see expose() in the script)")
    result = run(BOX, {"widht": 80.0, "width": 70.0}, strict=False)
    assert result.error is None and result.stdout == "70.0 30 False hi\n"


def test_bad_values_are_errors_naming_the_parameter():
    for values, message in [({"width": "300"}, "parameter 'width': too large: 300.0, maximum 200.0"),
                            ({"width": 10.0}, "parameter 'width': too small: 10.0, minimum 20.0"),
                            ({"height": "tall"}, "parameter 'height': 'tall' is not a valid int"),
                            ({"height": 2.0}, "parameter 'height': expected int, got float"),
                            ({"hollow": "maybe"}, "parameter 'hollow': 'maybe' is not a valid bool (true/false)"),
                            ({"text": 3}, "parameter 'text': expected str, got int")]:
        result = run(BOX, values)
        assert (result.error or "").endswith(f"ValueError: expose(box): {message}"), values
        assert result.stdout == ""


def test_the_window_skips_values_a_parameter_no_longer_accepts():
    # strict=False (the window): an edited script may no longer accept a kept value; its default is used
    for values in ({"width": 300.0}, {"height": "tall"}, {"height": 2.0}, {"hollow": "maybe"}, {"text": 3}):
        result = run(BOX, values, strict=False)
        assert result.error is None, values
        assert result.parameters[0].params == run(BOX).parameters[0].params


def test_exposing_the_same_function_twice_is_an_error():
    result = run(BOX + "expose(box)\n")
    assert (result.error or "").endswith("ValueError: expose(box) was already called in this run")
    assert result.error_line == 7


def test_a_rejected_function_fails_the_run_at_its_line():
    result = run("from pycodecad import expose\ndef f(a: list[int] = []):\n    pass\nexpose(f)\n")
    assert (result.error or "").endswith("TypeError: expose(f): parameter 'a': only int, float, bool and str are supported")
    assert result.error_line == 4


def test_parameters_are_reported_even_when_the_function_fails(tmp_path):
    script = tmp_path / "part.py"
    result = run(HEAD.replace("print(", "1 / 0; print(") + "expose(box)\n", {"height": 9}, filename=script)
    assert "ZeroDivisionError" in (result.error or "") and used(result)["height"] == 9
    saved = json.loads((tmp_path / ".pycodecad" / "part.py.last-run.json").read_text())
    assert saved["parameters"][0]["function"] == "box"
    assert saved["parameters"][0]["params"][1] == dict(name="height", kind="int", default=30, value=9, min=None,
                                                       max=None, step=None, slider=False, label=None,
                                                       description=None)
    assert runner.report("x.py", run(BOX))["parameters"][0]["params"][0]["value"] == 60.0
    assert runner.report("x.py", run("x = 1\n"))["parameters"] == []


def test_expose_returns_what_the_function_returns():
    code = "from pycodecad import expose, show\nfrom build123d import Box\ndef part(size: float = 5.0):\n" \
           "    return Box(size, size, size)\nshow(expose(part))\n"
    result = run(code, {"size": 2})
    assert result.error is None and result.shown[0].volume == pytest.approx(8)


def test_outside_pycodecad_expose_uses_the_defaults(monkeypatch):
    assert api.scene is None
    monkeypatch.setattr(api, "exposed", [])
    assert api.expose(box) == (60.0, 30, False, "hi")
    assert api.expose(box) == (60.0, 30, False, "hi")  # nothing is recorded: no "already called"
    assert api.exposed == []
    with pytest.raises(TypeError, match="parameter 'a'"):
        api.expose(f_list)


def test_plain_python_runs_an_exposed_script(tmp_path):
    script = tmp_path / "part.py"
    script.write_text(BOX)
    done = subprocess.run([sys.executable, str(script)], env=runner.python_env(), capture_output=True, text=True,
                          timeout=60)
    assert done.returncode == 0 and done.stdout == "60.0 30 False hi\n"


def test_values_and_parameters_cross_a_spawned_process(monkeypatch):
    monkeypatch.setattr(runner, "USE_FORK", False)
    result = run(BOX, {"height": "7"})
    assert result.error is None and result.stdout == "60.0 7 False hi\n" and used(result)["height"] == 7


def test_the_window_skips_a_value_of_another_kind():
    # int -> float in the script: the window's kept int is stale, not converted
    code = "from pycodecad import expose\ndef part(size: float = 10.0):\n    print(size)\nexpose(part)\n"
    result = run(code, {"part.size": 30}, strict=False)
    assert result.error is None and result.stdout.strip() == "10.0"


def test_int_parameters_must_fit_the_controls():
    code = "from pycodecad import expose\ndef part(seed: int = 2147483648):\n    pass\nexpose(part)\n"
    assert "numbers must be within ±1e9" in (run(code).error or "")
    slider = "from typing import Annotated\nfrom pytypehint import Min, Max, Slider\n" + code.replace(
        "seed: int = 2147483648", "seed: Annotated[int, Min(-2147483648), Max(2147483647), Slider()] = 0")
    assert "numbers must be within ±1e9" in (run(slider).error or "")
    big = code.replace("seed: int = 2147483648", "seed: float = 1e300")
    assert "numbers must be within ±1e9" in (run(big).error or "")
    code = code.replace("seed: int = 2147483648", "seed: Annotated[int, Step(214748365)] = 0")
    code = "from typing import Annotated\nfrom pytypehint import Step\n" + code
    assert "numbers must be within ±1e9" in (run(code).error or "")


def test_a_tiny_step_is_rejected():
    code = ("from typing import Annotated\nfrom pytypehint import Min, Max, Slider, Step\nfrom pycodecad import expose\n"
            "def part(x: Annotated[float, Min(0.0), Max(1.0), Step(1e-320), Slider()] = 0.0):\n    pass\n"
            "expose(part)\n")
    assert "Step must be at least 1e-6" in (run(code).error or "")
