#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Alex Moncks
"""The starfield and the HUD of Cube Maze 3D on MSX (SCREEN 7), laid out as
the original's (160 x 144, 8-pixel text cells) scaled to 512 x 212, with the
5 x 7 font of geo3d's VECTOR RAID (game/tools/sprites.py) and a few extra
glyphs. Font pixels are 4 x 2 G6 pixels, so a glyph fills about the original
8 x 8 cell. Keys are named as on the MSX: SPACE for A, ESC for B."""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
GEO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(GEO, "game", "tools"))
sys.path.insert(0, HERE)

import scene as sc  # noqa: E402
from sprites import _G as VR_FONT  # noqa: E402

FONT = dict(VR_FONT)
FONT.update({
    "/": ["....#", "...#.", "...#.", "..#..", ".#...", ".#...", "#...."],
    "[": [".###.", ".#...", ".#...", ".#...", ".#...", ".#...", ".###."],
    "]": [".###.", "...#.", "...#.", "...#.", "...#.", "...#.", ".###."],
    "?": [".###.", "#...#", "....#", "...#.", "..#..", ".....", "..#.."],
})
X0 = (512 - 160 * sc.XS) / 2          # the original's 160 columns, centred


def X(x):
    return int(round(X0 + x * sc.XS))


def Y(y):
    return int(round(y * sc.YS))


def text(img, x, y, s, col, sx=4, sy=2):
    """col: the original's colour index."""
    col = sc.C[col]
    px, py = X(x), Y(y)
    for ch in s:
        g = FONT.get(ch, FONT[" "])
        for r, row in enumerate(g):
            for c, b in enumerate(row):
                if b == "#":
                    y0, x0 = py + r * sy, px + c * sx
                    img[y0:y0 + sy, x0:x0 + sx] = col
        px += int(round(8 * sc.XS))


def bar(img, y0, y1):
    a, b = Y(y0), Y(y1)
    img[a:b, X(0):X(160)] = 0
    img[a, X(0):X(160)] = sc.C[1]
    img[b - 1, X(0):X(160)] = sc.C[1]


def big_digit(img, ch, x, y, col):
    """The preview countdown: a glyph drawn with 4 x 4 blocks (original)."""
    g = FONT[ch]
    for r, row in enumerate(g):
        for c, b in enumerate(row):
            if b == "#":
                img[Y(y + r * 4):Y(y + r * 4 + 4), X(x + c * 4):X(x + c * 4 + 4)] = sc.C[col]


def stars():
    """The original's 24 background dots, at the same places."""
    for i in range(24):
        yield (i * 67 + 13) % 160, (i * 43 + 7) % 120, 1 if i & 3 else 2


def background_bytes():
    import numpy as np
    # the checkerboard of indices 0 / 1 (both black) that the floors OR with
    yy, xx = np.mgrid[0:212, 0:512]
    img = (((xx // sc.CHECK_W) + (yy // sc.CHECK_H)) & 1).astype(np.uint8)
    for x, y, c in stars():
        img[Y(y), X(x):X(x) + 2] = sc.STAR[c]
    out = bytearray()
    for row in img:
        for x in range(0, 512, 2):
            out.append((row[x] << 4) | row[x + 1])
    return bytes(out)


CODE_ABC = "BCDFGHJKLMNPRSTVWXZ2345679"     # no vowels (no words), no 0/O, 1/I, 8/B


def stage_code(unl):
    """The code that unlocks sizes up to unl (4..6) from the title: 4
    letters from a fixed table (a placeholder until the format is agreed)."""
    if unl <= 3:
        return "----"
    x = (0x9E3779B9 * unl) & 0xFFFFFFFF
    out = ""
    for _ in range(4):
        x ^= (x << 13) & 0xFFFFFFFF
        x ^= x >> 17
        x ^= (x << 5) & 0xFFFFFFFF
        out += CODE_ABC[x % len(CODE_ABC)]
    return out


def Lx(n):
    return f"{n}x{n}"


def draw(img, g):
    tm = f"{int(g.el // 60)}:{str(100 + int(g.el % 60))[1:]}"
    if not g.ph:
        bar(img, 2, 20)
        text(img, 32, 7, "CUBE MAZE 3D", 7)
        bar(img, 104, 142)
        for i in range(4):
            s = i + 3
            lab = f"{s}x?" if s > g.unl else f"[{Lx(s)}]" if s == g.lv else Lx(s)
            text(img, 16 + i * 36 - (s == g.lv) * 8, 110, lab, 1 if s > g.unl else 6 if s == g.lv else 7)
        text(img, 8, 121, f"BEST:{g.best[g.lv - 3]}", 5)
        text(img, 104, 121, "ESC:CODE", 5)          # orig "B:UNLOCK": stage codes on MSX
        text(img, 8, 131, "ARW:SEL SPACE:START", 6)
        return
    bar(img, 0, 12)
    text(img, 3, 2, f"{Lx(g.lv)} F{g.act + 1}/6 R:{g.rot}", 7)
    text(img, 116, 2, tm, 6)
    if g.ph < 3:
        if g.ph < 2:
            d = str(int(g.prv / 60 + 1))
            if d in "123":
                big_digit(img, d, 66, 58, 0)          # shadow, then the digit (orig)
                big_digit(img, d, 64, 56, 7)
        bar(img, 132, 144)
        text(img, 8, 134, "PREVIEW SPACE:START" if g.ph < 2 else "ARW:ROLL  ESC:RETRY", 6 if g.ph < 2 else 5)
    else:
        bar(img, 29, 113)
        # the original's lines, one more for the stage code (no saving on MSX)
        text(img, 16, 35, "ALL 6x6 CLEARED!" if g.ph == 4 else f"STAGE {Lx(g.lv)} CLEAR!", 6)
        text(img, 16, 47, f"TIME:{tm}  ROT:{g.rot}", 7)
        text(img, 16, 58, f"SCORE:{g.sc}", 5)
        text(img, 16, 69, f"BEST:{g.best[g.lv - 3]}", 5)
        text(img, 16, 80, f"CODE:{stage_code(g.unl)}", 4)       # blue: index 4, outside the floors
        nxt = "3x3" if g.ph == 4 else Lx(g.lv + 1)
        text(img, 8, 97, f"SPACE:{nxt} ESC:TITLE", 7)
