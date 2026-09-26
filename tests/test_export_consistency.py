import pytest

from pycodecad import runner
from pycodecad.workspace import Workspace


def write_box(script, target, width):
    code = ("from build123d import Box\nfrom pycodecad import show\n"
            f"show(Box({width}, 1, 1))\n")
    result = runner.Run(code, str(script), export=str(target)).wait(30)
    assert result.error is None, result.error
    assert result.exported == str(target)


def finish_run(workspace):
    workspace.start_run()
    assert workspace.child is not None
    result = workspace.child.wait(30)
    assert result.error is None, result.error
    workspace.check_runs()


@pytest.mark.parametrize("run_again", [False, True])
def test_an_exported_mesh_used_as_input_is_checked_after_external_changes(tmp_path, run_again):
    script = tmp_path / "part.py"
    mesh = tmp_path / "part.stl"
    write_box(script, mesh, 10)
    script.write_text("from pycodecad import import_mesh, show\nshow(import_mesh('part.stl'))\n")
    workspace = Workspace(script, run=False)
    try:
        finish_run(workspace)
        workspace.export("stl")
        assert len(workspace.exports) == 1
        result = workspace.exports[0].wait(30)
        assert result.error is None, result.error
        workspace.check_runs()
        if run_again:
            finish_run(workspace)
        bounds = workspace.shown[0].bbox()
        assert bounds is not None and bounds[1][0] - bounds[0][0] == pytest.approx(10)

        write_box(script, mesh, 30)  # another tool changes a file previously exported by this window
        workspace.export("3mf")
        assert not workspace.exports
        assert workspace.message_is_error and "part.stl changed since the last run" in workspace.message
        assert not (tmp_path / "part.3mf").exists()
    finally:
        workspace.close()
