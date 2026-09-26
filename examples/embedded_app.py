"""An order desk built on pycodecad's ImGui components (pycodecad.embed, experimental in 1.0): pick an
order and the tray of tray.py is rebuilt to its measures; export it for the printer.

    python examples/embedded_app.py             # the app
    python examples/embedded_app.py shot.png    # hidden: save a picture after the first run, then quit

tray.py opens read only (a template): the orders never change it. Exports are written next
to it, one file per order (order_1041.stl ...).
"""
import sys
from pathlib import Path

from slimgui import imgui

import pycodecad.embed as p3

ORDERS = (  # number, customer, width, depth, height (mm), rounded corners
    ("1041", "Cafe Norte: cutlery", 120.0, 80.0, 30.0, True),
    ("1042", "Workshop: screws", 60.0, 40.0, 20.0, False),
    ("1043", "Studio: pencils", 180.0, 50.0, 25.0, True),
    ("1044", "Kitchen: spices", 150.0, 150.0, 60.0, True),
)
FIRST_USE = imgui.Cond.FIRST_USE_EVER


def place(title: str, x: float, y: float, width: float, height: float) -> None:
    imgui.set_next_window_pos((x, y), FIRST_USE)
    imgui.set_next_window_size((width, height), FIRST_USE)
    imgui.begin(title)


def main(screenshot: str | None = None) -> None:
    window = p3.create_window("Tray orders", size=(1400, 860), visible=screenshot is None)
    part = p3.Workspace(Path(__file__).with_name("tray.py"), read_only=True, run=False)
    part.show_files = False  # only the template, not the other files of its folder
    preview = p3.Viewer()  # the same tray from the front, with a camera of its own
    preview.look_from((0.0, -1.0, 0.0))
    chosen = None
    while window.frame(keep_open=part.dirty()):
        place("Template", 350, 10, 1040, 840)  # first: draw() updates it, what follows sees this frame's state
        part.draw()
        part.close_prompt(window)
        imgui.end()

        place("Orders", 10, 10, 330, 400)
        for index, (number, customer, width, depth, height, rounded) in enumerate(ORDERS):
            if imgui.selectable(f"{number}  {customer}", chosen == index)[0] or (screenshot and chosen is None):
                chosen = index
                part.values.update({"tray.width": width, "tray.depth": depth, "tray.height": height,
                                    "tray.rounded": rounded})
                part.run()  # explicit, as always
        if chosen is not None:
            number, _, width, depth, height, _ = ORDERS[chosen]
            imgui.separator()
            imgui.text(f"Order {number}: {width:g} x {depth:g} x {height:g} mm")
            imgui.begin_disabled(part.running() or part.error is not None)
            if imgui.button("Export STL"):
                part.export("stl", target=f"order_{number}.stl")
            imgui.same_line()
            if imgui.button("Export 3MF (Bambu)"):
                part.export("3mf", "bambu", target=f"order_{number}.3mf")
            imgui.end_disabled()
        imgui.text_wrapped("Running..." if part.running() else part.error or part.message)
        imgui.end()

        place("Preview", 10, 420, 330, 430)
        preview.draw(part.shown)
        imgui.end()

        if screenshot and part.ran() and not part.running():
            window.screenshot(screenshot)
            window.request_close()
    window.close()


if __name__ == "__main__":
    main(*sys.argv[1:2])
