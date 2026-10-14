"""Build original SVG tile art and Tiled maps; no external artwork or dependencies.

Run with Python from any directory. All coordinates and shapes are authored here.
SVG stays editable and Pixi rasterizes it at its native pixel dimensions.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "ui/src/assets"
SEATS = [
    "desk-ceo",
    "pc-1",
    "pc-2",
    "pc-3",
    "pc-4",
    "pc-5",
    "pc-6",
    "desk-chief-architect",
    "desk-product-manager",
    "desk-team-lead",
    "desk-backend-engineer",
    "desk-ui-ux-expert",
    "desk-data-engineer",
    "desk-project-manager",
    "desk-market-researcher",
    "desk-agent-organizer",
]


def rect(x: int, y: int, w: int, h: int, color: str) -> str:
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{color}"/>'


def atlas() -> str:
    ink, wood, mint, blue = "#343b52", "#ba8f68", "#7cae94", "#9dc8da"
    tiles: dict[int, str] = {}

    def tile(gid: int, *shapes: tuple[int, int, int, int, str]) -> None:
        x, y = ((gid - 1) % 8) * 16, ((gid - 1) // 8) * 16
        tiles[gid] = f'<g transform="translate({x} {y})">' + "".join(rect(*s) for s in shapes) + "</g>"

    tile(1, (0, 0, 16, 16, "#ddd6c7"), (0, 15, 16, 1, "#c7bfaf"), (15, 0, 1, 16, "#d3cbbb"))
    tile(2, (0, 0, 16, 16, "#c5d9d4"), (0, 15, 16, 1, "#aec4be"), (15, 0, 1, 16, "#b9cec8"))
    tile(3, (0, 0, 16, 16, ink), (0, 0, 16, 11, "#68778c"), (0, 11, 16, 2, "#9da8b5"))
    tile(
        4, (5, 10, 7, 5, wood), (7, 3, 2, 8, "#477861"), (2, 4, 6, 4, mint), (9, 1, 5, 5, "#91c7a1"), (8, 7, 6, 3, mint)
    )
    tile(
        5,
        (3, 2, 10, 4, ink),
        (4, 2, 8, 3, mint),
        (3, 7, 10, 5, ink),
        (4, 7, 8, 4, mint),
        (5, 12, 2, 3, ink),
        (10, 12, 2, 3, ink),
    )
    tile(6, (1, 3, 14, 10, ink), (2, 3, 12, 7, wood), (3, 13, 2, 3, ink), (11, 13, 2, 3, ink))
    tile(
        7,
        (1, 1, 14, 14, ink),
        (2, 2, 12, 12, wood),
        (3, 3, 2, 4, blue),
        (6, 3, 3, 4, mint),
        (10, 3, 2, 4, "#d98b7b"),
        (2, 8, 12, 1, ink),
        (4, 10, 7, 3, "#e6d4a4"),
    )
    tile(8, (4, 1, 8, 5, blue), (3, 6, 10, 9, "#e6e9e3"), (6, 7, 5, 2, ink), (6, 10, 3, 3, blue))
    # A 32x32 desk with an inset display, keyboard, and two legs. The two
    # variants occupy adjacent 2x2 blocks; screen animation uses the same inset.
    for left, lit in [(9, False), (11, True)]:
        sx, sy = ((left - 1) % 8) * 16, ((left - 1) // 8) * 16
        shapes = [
            (1, 18, 30, 8, ink),
            (2, 18, 28, 6, wood),
            (4, 26, 3, 6, ink),
            (25, 26, 3, 6, ink),
            (1, 3, 29, 16, ink),
            (3, 5, 25, 12, blue if lit else "#505e70"),
            (14, 19, 4, 3, ink),
            (8, 23, 16, 2, "#e3e5dd"),
        ]
        tiles[left] = f'<g transform="translate({sx} {sy})">' + "".join(rect(*s) for s in shapes) + "</g>"
    tile(13, (2, 0, 12, 16, ink), (3, 1, 10, 14, "#d4e1dc"), (3, 6, 10, 1, ink), (11, 3, 1, 2, ink), (11, 9, 1, 3, ink))
    tile(
        14,
        (1, 10, 14, 5, wood),
        (3, 1, 9, 10, ink),
        (4, 2, 7, 3, "#c08463"),
        (6, 7, 4, 3, "#f1e4cf"),
        (12, 11, 2, 3, "#f1e4cf"),
    )
    tile(15, (4, 4, 8, 11, "#68778c"), (3, 3, 10, 2, ink), (6, 6, 1, 7, "#9da8b5"), (9, 6, 1, 7, "#9da8b5"))
    tile(
        16,
        (0, 0, 16, 16, ink),
        (1, 1, 14, 14, "#e6d4a4"),
        (3, 3, 4, 4, mint),
        (9, 3, 4, 4, blue),
        (3, 9, 4, 4, "#d98b7b"),
    )
    tile(21, (3, 1, 10, 12, ink), (4, 2, 8, 10, "#f1e4cf"), (7, 4, 1, 4, ink), (8, 7, 3, 1, ink))
    tile(
        22,
        (0, 0, 16, 16, ink),
        (1, 1, 14, 14, blue),
        (7, 1, 2, 14, "#e6e9e3"),
        (1, 8, 14, 1, "#e6e9e3"),
        (2, 2, 3, 5, "#c9e4e9"),
    )
    tile(23, (0, 2, 16, 13, wood), (2, 4, 12, 8, ink), (3, 5, 10, 6, blue), (7, 1, 2, 5, "#e6e9e3"))
    tile(24, (0, 0, 16, 16, "#789b96"), (1, 1, 14, 14, "#89aca7"), (3, 7, 10, 2, "#9bbcb7"))
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="128" height="64" shape-rendering="crispEdges">'
        + "".join(tiles.values())
        + "</svg>\n"
    )


def make_map(theme: str) -> dict:
    w, h = 36, 26
    layers = {name: [0] * (w * h) for name in ["floor", "walls", "furniture-below", "furniture-above", "collision"]}

    def put(layer: str, x: int, y: int, gid: int, blocked: bool = False) -> None:
        assert 0 <= x < w and 0 <= y < h
        layers[layer][y * w + x] = gid
        if blocked:
            layers["collision"][y * w + x] = 1

    for y in range(h):
        for x in range(w):
            put("floor", x, y, 2 if (theme == "atrium" or x >= 26) else 1)
            if x in (0, w - 1) or y in (0, h - 1):
                put("walls", x, y, 3, True)
    # Separate meeting and break areas with rugs, leaving open circulation.
    for x0, y0, x1, y1 in [(11, 2, 23, 6), (27, 11, 34, 18)]:
        for y in range(y0, y1):
            for x in range(x0, x1):
                put("floor", x, y, 24)
    points = {"desk-ceo": (4, 5)}
    for i, name in enumerate(SEATS[1:]):
        # Two independent authored arrangements share semantic prop anchors.
        x = (3 + (i % 5) * 4) if theme == "studio" else (4 + (i % 5) * 4)
        points[name] = (x, 11 + (i // 5) * 5)
    for x, y in points.values():
        for gid, dx, dy in [(9, 0, -2), (10, 1, -2), (17, 0, -1), (18, 1, -1)]:
            put("furniture-above", x + dx, y + dy, gid, True)
        put("furniture-below", x, y, 5)
    points.update(
        {
            "entrance": (23, 24),
            "warroom-seat": (16, 5),
            "cafe-seat-1": (28, 13),
            "cafe-seat-2": (28, 15),
            "cafe-seat-3": (32, 13),
            "cafe-seat-4": (32, 15),
            "cafe-stand-coffee": (28, 21),
            "cafe-stand-vending": (33, 21),
        }
    )
    for name, (x, y) in points.items():
        if name.startswith("cafe-seat"):
            put("furniture-below", x, y, 5)
    for x, y in [(28, 14), (32, 14), (15, 3), (16, 3), (17, 3), (18, 3)]:
        put("furniture-below", x, y, 6, True)
    for x, y, gid in [
        (2, 3, 4),
        (24, 9, 4),
        (25, 20, 4),
        (33, 18, 7),
        (28, 20, 14),
        (31, 20, 23),
        (32, 20, 13),
        (33, 20, 8),
        (24, 23, 15),
        (7, 1, 16),
        (4, 1, 16),
        (1, 1, 21),
        (11, 0, 22),
        (18, 0, 22),
        (6, 2, 7),
    ]:
        put("furniture-above", x, y, gid, True)
    result = {
        "type": "map",
        "version": "1.10",
        "orientation": "orthogonal",
        "renderorder": "right-down",
        "width": w,
        "height": h,
        "tilewidth": 16,
        "tileheight": 16,
        "infinite": False,
        "tilesets": [
            {
                "firstgid": 1,
                "name": "agentlab-original",
                "image": "../tilesets/workspace.svg",
                "imagewidth": 128,
                "imageheight": 64,
                "tilewidth": 16,
                "tileheight": 16,
                "columns": 8,
                "tilecount": 32,
            }
        ],
        "layers": [
            {"name": name, "type": "tilelayer", "width": w, "height": h, "data": data} for name, data in layers.items()
        ],
    }
    result["layers"].append(
        {
            "name": "spawn-points",
            "type": "objectgroup",
            "objects": [{"name": name, "x": x * 16, "y": y * 16, "point": True} for name, (x, y) in points.items()],
        }
    )
    result["layers"].append(
        {
            "name": "zones",
            "type": "objectgroup",
            "objects": [
                {"name": "boardroom", "x": 11 * 16, "y": 2 * 16, "width": 12 * 16, "height": 5 * 16},
                {"name": "cafeteria", "x": 27 * 16, "y": 11 * 16, "width": 7 * 16, "height": 12 * 16},
            ],
        }
    )
    return result


def main() -> None:
    (ROOT / "tilesets").mkdir(exist_ok=True)
    (ROOT / "maps").mkdir(exist_ok=True)
    (ROOT / "tilesets/workspace.svg").write_text(atlas())
    for theme in ["studio", "atrium"]:
        (ROOT / f"maps/{theme}.tmj").write_text(json.dumps(make_map(theme), separators=(",", ":")) + "\n")


if __name__ == "__main__":
    main()
