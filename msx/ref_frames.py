#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Alex Moncks
"""The original Cube Maze 3D's frames, for comparison: runs ref/js_trace.js
(the original source in node, with a stub runtime) with DUMP set, and paints
its cls / spr calls on a 160 x 144 screen as the Playload engine does (8 x 8
patterns, sprites drawn ink-only). The patterns are the game's own (chars
1..12, set at load) and the engine's glyph table, read as data from a local
clone of kitao/playload (MIT): PLAYLOAD_GLYPHS or ../../../../ext/pl.
"""
import json
import os
import re
import subprocess
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REF = os.path.join(os.path.dirname(HERE), "ref")
GLYPHS = os.environ.get("PLAYLOAD_GLYPHS", os.path.normpath(
    os.path.join(HERE, "..", "..", "..", "..", "ext", "pl", "src", "engine", "glyphs.js")))
PLAYLOAD = ["#000000", "#55415f", "#646964", "#d77355", "#508cd7", "#64b964", "#e6c86e", "#dcf5ff"]


def patterns():
    pat = {}
    for line in open(GLYPHS, encoding="utf8"):
        m = re.match(r"\s*(\{.*\}),?\s*$", line)
        if m:
            g = json.loads(m.group(1))
            pat[g["ch"]] = g["rows"]
    for i in range(1, 13):                       # the game's own (orig line 9)
        if i != 10:
            pat[chr(i)] = [256 - (256 >> i) if i < 9 else 85 if i & 1 else 170] + [0] * 7
    return pat


def frames(seed, script):
    """One 144 x 160 array of colour indices per tick of the script."""
    with tempfile.TemporaryDirectory() as d:
        inp, dump = os.path.join(d, "in.json"), os.path.join(d, "dump.jsonl")
        json.dump(script, open(inp, "w"))
        subprocess.run(["node", os.path.join(REF, "js_trace.js"), str(seed), str(len(script)), inp],
                       env=dict(os.environ, DUMP=dump, GLYPHS=GLYPHS), stdout=subprocess.DEVNULL, check=True)
        pat = patterns()
        masks = {ch: np.array([[(b >> (7 - k)) & 1 for k in range(8)] for b in rows], bool)
                 for ch, rows in pat.items()}
        out = []
        for line in open(dump):
            fr = json.loads(line)
            img = np.full((152, 176), fr["cls"] or 0, np.uint8)   # 8-pixel margin right / bottom
            for x, y, s, col in fr["spr"]:
                x, y = int(x), int(y)                    # Math.trunc
                for ch in s:
                    o = ord(ch)
                    if 1 <= o <= 8:                      # the spans: one row, o pixels
                        if 0 <= y < 144:
                            img[y, max(0, x):max(0, x + o)] = col
                    elif -8 < x < 160 and -8 < y < 144:
                        m = masks.get(ch)
                        if m is not None:
                            x0, y0 = max(0, -x), max(0, -y)
                            sub = img[y + y0:y + 8, x + x0:x + 8]
                            sub[m[y0:, x0:]] = col
                    x += 8
            out.append(img[:144, :160].copy())
        return out


def to_rgb(img):
    pal = np.array([[int(h[i:i + 2], 16) for i in (1, 3, 5)] for h in PLAYLOAD], np.uint8)
    return pal[img]
