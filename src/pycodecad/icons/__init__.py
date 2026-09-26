"""Button icons: the Lucide icon font (https://lucide.dev, ISC license, see LICENSE here), merged into
the ImGui font so an icon is just a character in a label: imgui.button(icon("play"))."""
from __future__ import annotations

from importlib import resources

# Lucide 1.48.0 codepoints of the icons the window uses (the font has them all; only these are named).
CODEPOINTS = {
    "play": 0xE13C,
    "pause": 0xE12E,
    "square": 0xE167,
    "save": 0xE14D,
    "file-plus-2": 0xE0CA,
    "sparkles": 0xE412,
    "copy": 0xE09E,
    "clipboard-paste": 0xE3E8,
    "download": 0xE0B2,
    "refresh-cw": 0xE145,
    "scan": 0xE257,
    "settings-2": 0xE245,
    "rotate-ccw": 0xE148,
}


def icon(name: str) -> str:
    """The character that draws the icon (a KeyError names an icon missing from CODEPOINTS)."""
    return chr(CODEPOINTS[name])


def font_data() -> bytes:
    return resources.files(__name__).joinpath("lucide.ttf").read_bytes()
