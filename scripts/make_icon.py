"""Dessine l'icone de Rexo Studio (PNG 1024 x 1024) sans dependance.

Clap de cinema blanc avec un bouton lecture, sur un carre orange aux
coins arrondis (gabarit des icones macOS). Bords lisses par distance
signee : chaque forme donne une couverture 0..1 au lieu d'un pixel net.

Usage : python3 scripts/make_icon.py sortie.png
"""
import struct
import sys
import zlib

SIZE = 1024
ORANGE_TOP = (255, 157, 61)
ORANGE_BOTTOM = (240, 106, 0)
WHITE = (250, 250, 250)
DARK = (27, 31, 39)


def clamp(value: float) -> float:
    return 0.0 if value < 0.0 else 1.0 if value > 1.0 else value


def rounded_rect(x, y, x0, y0, x1, y1, radius) -> float:
    """Couverture du pixel (x, y) par un rectangle aux coins arrondis."""
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    hx, hy = (x1 - x0) / 2.0 - radius, (y1 - y0) / 2.0 - radius
    dx, dy = max(abs(x - cx) - hx, 0.0), max(abs(y - cy) - hy, 0.0)
    inside = min(max(abs(x - cx) - hx, abs(y - cy) - hy), 0.0)
    distance = (dx * dx + dy * dy) ** 0.5 + inside - radius
    return clamp(0.5 - distance)


def triangle(x, y, points) -> float:
    """Couverture par un triangle (distance au bord le plus proche)."""
    worst = -1e9
    for i in range(3):
        (ax, ay), (bx, by) = points[i], points[(i + 1) % 3]
        nx, ny = by - ay, -(bx - ax)                # normale sortante (sens horaire)
        length = (nx * nx + ny * ny) ** 0.5
        worst = max(worst, ((x - ax) * nx + (y - ay) * ny) / length)
    return clamp(0.5 - worst)


def mix(base, color, alpha):
    return tuple(b + (c - b) * alpha for b, c in zip(base, color))


def pixel(x, y):
    shape = rounded_rect(x, y, 100, 100, 924, 924, 185)
    if shape <= 0.0:
        return (0, 0, 0, 0)
    t = (y - 100) / 824.0
    color = mix(ORANGE_TOP, ORANGE_BOTTOM, clamp(t))
    # Barre du clap, inclinee de quelques degres, rayee en diagonale.
    lift = (x - 230) * 0.12
    bar = rounded_rect(x, y + lift, 230, 250, 794, 352, 22)
    if bar > 0.0:
        stripe = ((x + (y + lift) * 1.0) // 70) % 2 == 0
        color = mix(color, DARK if stripe else WHITE, bar)
    # Corps du clap.
    body = rounded_rect(x, y, 230, 380, 794, 774, 40)
    if body > 0.0:
        color = mix(color, WHITE, body)
    # Bouton lecture.
    play = triangle(x, y, [(452, 468), (652, 577), (452, 686)])
    if play > 0.0:
        color = mix(color, ORANGE_BOTTOM, play)
    return tuple(int(round(c)) for c in color) + (int(round(255 * shape)),)


def write_png(path: str) -> None:
    rows = []
    for y in range(SIZE):
        row = bytearray(b"\x00")                    # filtre PNG "aucun"
        for x in range(SIZE):
            row.extend(pixel(x + 0.5, y + 0.5))
        rows.append(bytes(row))
    raw = zlib.compress(b"".join(rows), 9)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))

    header = struct.pack(">IIBBBBB", SIZE, SIZE, 8, 6, 0, 0, 0)   # RGBA 8 bits
    with open(path, "wb") as fh:
        fh.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
                 + chunk(b"IDAT", raw) + chunk(b"IEND", b""))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage : make_icon.py sortie.png")
    write_png(sys.argv[1])
