#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Alex Moncks
"""Cube Maze 3D on MSX: what geo3d v2.0 and the V9968 are given, frame by
frame, in SCREEN 7 (GRAPHIC6, 512 x 212, 16 colours from the V9968's 15-bit
palette).

The drawing follows the original's (ref/cubemaze.py, the logic; the original
draws every element as flat quads, in painter's order with hand-made depth
biases), split between the VDP and geo3d:

  - the floor of each face (background, cells, passages, the walls' shadow
    layer, the goal's base) is a texture, 120 x 60 texels, baked once per
    stage, in two versions: active face (coloured) and the others (grey);
  - geo3d draws each visible face as the lv x lv grid of textured quads, plus
    the walls as real geometry: the top layer always, the middle layer on the
    active face, and the goal's two animated layers;
  - only the visible faces (at most 3) are resident in geo3d's RAMs (1023
    entries each in v2.0); a face is uploaded when it becomes visible;
  - one RUN per layer, lowest first (floor, then the layers by height), with
    VFIRST / FFIRST / NFACE on the face's block: layers are flat and parallel,
    so this is a correct painter's order without the original's depth
    biases; the vertices are transformed once, in the face's first RUN.

The ball and its shadow are bitmaps, copied by the VDP (LMMM, TIMP) from
pre-drawn images after the faces; then the wall tops that the original paints
after the ball (its depth key, same biases) and that overlap it on screen are
painted again, by one more RUN over a few faces written in a scratch area of
the face RAM (they reuse the projections, NVERT = 0). Hardware sprites would
always cover the walls in front of the ball and the HUD. The HUD is written by
the Z80 over the frame.

Output: a list of operations in the format of showcase/showcase.py (geo3d
port writes, the Z80's VDP commands, VRAM blocks, RUN / wait / page flip),
the golden traffic the Z80 program must reproduce.
"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "ref"))
sys.path.insert(0, os.path.join(ROOT, "sim"))

import cubemaze as cm  # noqa: E402

# ------------------------------------------------------------------ screen
W, H = 512, 212
SU = 2048                        # model units per original unit (cube half size K = 1.75)
FOCAL = 272                      # 185 x 212/144: the original's focal length, in lines
CX, CY = 256, 109                # (80, 74) of the 160 x 144 original, scaled
ZNEAR = 16
TZ = round(9.4 * SU / 2)         # camera at 9.4; rows Y and Z halved: SCREEN 7 aspect
YS = 212 / 144                   # original pixels -> SCREEN 7 lines
XS = 2 * YS                      # original pixels -> SCREEN 7 pixels

# ------------------------------------------------------------------ colours
PLAYLOAD = ["#000000", "#55415f", "#646964", "#d77355", "#508cd7", "#64b964", "#e6c86e", "#dcf5ff"]


def _rgb(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def _mix(a, b):
    return tuple((x + y) / 2 for x, y in zip(a, b))


# SCREEN 7 palette, arranged for the original's checkerboard dithers.
#
# The original dithers a colour over the background (colour 1) for the cells
# and passages: grey on the inactive faces, the face's colour on the active
# one. Here the dither is a screen-aligned checkerboard made by the VDP for
# free: the background page (copied every frame) is a checkerboard of indices
# 0 and 1, both black, and the floors are textured with LOP = OR. A dithered
# texel has an even index d whose odd neighbour d + 1 is the background colour,
# so it shows d on the squares of index 0 and d + 1 on the squares of index 1.
# The other texels of a floor (background, start, goal) have odd indices whose
# OR with 0 or 1 is themselves, and also with the stars' indices (3 and 2),
# which sit in the background page under the cube. Everything else is drawn
# after the floors with LOP = IMP and may use any index.
C = {0: 0, 1: 3, 2: 5, 3: 11, 4: 4, 5: 7, 6: 13, 7: 9}     # original colour -> solid index
D_GREY, D_ACT = 2, 14            # dithers over the background: grey, the active face's colour
STAR = {1: 3, 2: 2}              # the stars' colours (2 is grey outside the floors)
SHADOW = 1                       # black, for the ball's shadow (0 is transparent in TIMP)
CHECK_W, CHECK_H = 3, 1          # a checkerboard square: the original's pixel, rounded


def checker(x, y):
    return ((x // CHECK_W) + (y // CHECK_H)) & 1


def palette(act):
    """The 16 entries (RGB) for a frame whose active face is act: only entry
    D_ACT changes, written at the page flip."""
    P = [_rgb(h) for h in PLAYLOAD]
    pal = [P[0]] * 16
    for c, i in C.items():
        pal[i] = P[c]
    pal[1] = P[0]
    pal[D_GREY], pal[D_GREY + 1] = P[2], P[1]
    pal[D_ACT], pal[D_ACT + 1] = P[cm.F[act][3]], P[1]
    return pal


def epal_words(act):
    """15-bit palette entries (R, G, B 5 bits each)."""
    return [tuple(min(31, round(c * 31 / 255)) for c in rgb) for rgb in palette(act)]


# ------------------------------------------------------------------ VRAM map
PAGE_ROWS = 256
BG_Y = 512                       # page 2: starfield and HUD frame, copied every frame
TEX_Y = 768                      # page 3: 12 floor textures in slots of 128 x 64
TEX_W, TEX_H = 120, 60
BALL_Y = 960                     # page 3, below the textures: ball images (32 rows)
SHADOW_Y = 992                   # and their shadows (32 rows)
PR_MIN, PR_MAX = 3, 10           # the original's ball radius, in its pixels
N_SCRATCH = 12                   # wall quads painted again over the ball, at most
V_SCRATCH = 1024 - 4 * N_SCRATCH # vertex RAM 976..1023: their vertices
F_SCRATCH = 1024 - N_SCRATCH     # face RAM 1012..1023: their faces


def tex_slot(face, active):
    s = face * 2 + (1 if active else 0)
    return (s % 4) * 128, TEX_Y + (s // 4) * 64


# ------------------------------------------------------------------ geometry
def dims(lv):
    K = cm.K
    cs = K * 2 / lv
    return dict(K=K, cs=cs, h=(lv - 1) / 2, wH=cs * 0.28, wW=cs * 0.11, wL=(cs + cs * 0.11) / 2,
                bR=cs * 0.26)


def model_point(f, n, u, v):
    """Original LC(F[f], K + n, u, v) in model units (integers)."""
    p = cm.LC(cm.F[f], cm.K + n, u, v)
    return tuple(round(c * SU) for c in p)


def edges_of(g, f):
    """The original's per-face edge loop: (r, c, d, eu, ev, is_passage)."""
    lv, dm = g.lv, dims(g.lv)
    cs, h = dm["cs"], dm["h"]
    out = []
    for r in range(lv):
        for c in range(lv):
            u0, v0 = (c - h) * cs, (r - h) * cs
            k = cm.ID([f, r, c])
            for d in cm.I4:
                s = -0.5 if (d - 1) & 2 else 0.5
                eu = u0 + (s * cs if d & 1 else 0)
                ev = v0 + (0 if d & 1 else s * cs)
                if d < 2 or ((not c) if d > 2 else r == lv - 1):
                    out.append((r, c, d, eu, ev, bool(g.G.get(k, 0) & (1 << d))))
    return out


Q4 = ((-1, -1), (1, -1), (1, 1), (-1, 1))


def quad(f, n, u, v, su, sv):
    return [model_point(f, n, u + a * su, v + b * sv) for a, b in Q4]


class FaceBlock:
    """One face's vertices and faces, in layers: [(name, height, faces)],
    faces = (4 vertex indices local to the block, BASE, uv or None)."""

    def __init__(self, f):
        self.f = f
        self.verts = []
        self.layers = []
        self.top_meta = []           # (r, c, d) of each face of the "top" layer

    def add_quad(self, pts):
        i = len(self.verts)
        self.verts += pts
        return (i, i + 1, i + 2, i + 3)


def floor_block(g, f, blk):
    lv, dm = g.lv, dims(g.lv)
    cs, K = dm["cs"], dm["K"]
    grid = {}
    for r in range(lv + 1):
        for c in range(lv + 1):
            grid[(r, c)] = len(blk.verts)
            blk.verts.append(model_point(f, 0, -K + c * cs, -K + r * cs))
    cw, ch = TEX_W // lv, TEX_H // lv
    faces = []
    for r in range(lv):
        for c in range(lv):
            ids = (grid[(r, c)], grid[(r, c + 1)], grid[(r + 1, c + 1)], grid[(r + 1, c)])
            uv = [c * cw, r * ch, (c + 1) * cw, r * ch, (c + 1) * cw, (r + 1) * ch, c * cw, (r + 1) * ch]
            faces.append((ids, 0x81, uv))
    blk.layers.append(("floor", 0.0, faces))


def wall_runs(g, f):
    """The face's walls, and the same walls merged into runs: consecutive
    walls on one grid line overlap by their thickness (wL = (cs + wW) / 2),
    so a run of them is one rectangle, the same pixels as its walls.
    Returns (walls, runs): walls (r, c, d, eu, ev, su, sv), runs (u, v, su, sv)."""
    dm = dims(g.lv)
    cs, wW, wL = dm["cs"], dm["wW"], dm["wL"]
    walls, lines = [], {}
    for r, c, d, eu, ev, ps in edges_of(g, f):
        if ps:
            continue
        su, sv = (wW, wL) if d & 1 else (wL, wW)
        walls.append((r, c, d, eu, ev, su, sv))
        if d & 1:     # along v, on the line u = eu
            lines.setdefault((1, round(eu * 2 / cs)), []).append(round(ev * 2 / cs))
        else:         # along u, on the line v = ev
            lines.setdefault((0, round(ev * 2 / cs)), []).append(round(eu * 2 / cs))
    runs = []
    for (o, k), ts in sorted(lines.items()):
        ts.sort()
        groups = [[ts[0]]]
        for t in ts[1:]:
            if t - groups[-1][-1] == 2:
                groups[-1].append(t)
            else:
                groups.append([t])
        for gp in groups:
            a, b = gp[0] * cs / 2, gp[-1] * cs / 2
            m, hl = (a + b) / 2, (b - a) / 2 + wL
            runs.append((k * cs / 2, m, wW, hl) if o else (m, k * cs / 2, hl, wW))
    return walls, runs


def wall_layers(g, f, blk, mid=True):
    """The walls' middle and top layers (the low one is in the texture), as
    runs. The middle layer is on every visible face, as in the original
    (without it the walls of the grey faces look hollow)."""
    wH = dims(g.lv)["wH"]
    top = f == g.act
    walls, runs = wall_runs(g, f)
    blk.top_meta = walls
    mids = [(blk.add_quad(quad(f, wH * 0.5, u, v, su, sv)), C[2 if top else 1], None) for u, v, su, sv in runs]
    tops = [(blk.add_quad(quad(f, wH, u, v, su, sv)), C[7 if top else 2], None) for u, v, su, sv in runs]
    if mid:
        blk.layers.append(("mid", wH * 0.5, mids))
    blk.layers.append(("top", wH, tops))


def goal_layers(g, f, blk):
    """The goal's animated box: layers at n/2 and n (the base is in the texture)."""
    if g.gl[0] != f:
        return
    dm = dims(g.lv)
    cs, h = dm["cs"], dm["h"]
    n = 0.12 + math.sin(g.T * 0.15) * 0.04
    u0, v0 = (g.gl[2] - h) * cs, (g.gl[1] - h) * cs
    top = f == g.act
    q1 = blk.add_quad(quad(f, n * 0.5, u0, v0, cs * 0.22, cs * 0.22))
    q2 = blk.add_quad(quad(f, n, u0, v0, cs * 0.22, cs * 0.22))
    blk.layers.append(("goal1", n * 0.5, [(q1, C[2 if top else 1], None)]))
    blk.layers.append(("goal2", n, [(q2, C[6 if g.T & 4 else 3], None)]))


def face_block(g, f, active_mid=True):
    blk = FaceBlock(f)
    floor_block(g, f, blk)
    wall_layers(g, f, blk)
    goal_layers(g, f, blk)
    blk.layers.sort(key=lambda L: L[1])          # lowest layer first
    return blk


# ------------------------------------------------------------------ textures
def bake_texture(g, f, active):
    """The floor of face f as G6 texels: TEX_W x TEX_H palette indices."""
    lv, dm = g.lv, dims(g.lv)
    cs, h, K = dm["cs"], dm["h"], dm["K"]
    wW, wL = dm["wW"], dm["wL"]
    sx, sy = TEX_W / (2 * K), TEX_H / (2 * K)
    img = [[C[1]] * TEX_W for _ in range(TEX_H)]

    def rect(u, v, su, sv, col):
        x0 = round((u - su + K) * sx)
        x1 = round((u + su + K) * sx)
        y0 = round((v - sv + K) * sy)
        y1 = round((v + sv + K) * sy)
        for y in range(max(0, y0), min(TEX_H, y1)):
            row = img[y]
            for x in range(max(0, x0), min(TEX_W, x1)):
                row[x] = col
    st, gl = cm.ID(g.st), cm.ID(g.gl)
    for r in range(lv):
        for c in range(lv):
            u0, v0 = (c - h) * cs, (r - h) * cs
            k = cm.ID([f, r, c])
            isS, isG = k == st, k == gl
            dith = D_ACT if active else D_GREY
            rect(u0, v0, cs * 0.43, cs * 0.43, C[5] if isS else C[3] if isG else dith)
    for r, c, d, eu, ev, ps in edges_of(g, f):
        if ps:
            col = D_ACT if active else D_GREY
            rect(eu, ev, cs * 0.1 if d & 1 else cs * 0.36, cs * 0.36 if d & 1 else cs * 0.1, col)
        else:
            su, sv = (wW, wL) if d & 1 else (wL, wW)
            rect(eu, ev, su, sv, C[1])                    # the walls' shadow layer
    if g.gl[0] == f:
        u0, v0 = (g.gl[2] - h) * cs, (g.gl[1] - h) * cs
        rect(u0, v0, cs * 0.22, cs * 0.22, C[1])          # the goal's base layer
    return img


# ------------------------------------------------------------------ matrices
def q14(x):
    return max(-32768, min(32767, round(x * 16384)))


def quat_matrix(q):
    """R with R v = qR(v, q)."""
    cols = [cm.qR(e, q)[:3] for e in ((1, 0, 0), (0, 1, 0), (0, 0, 1))]
    return [[cols[j][i] for j in range(3)] for i in range(3)]


def geo_matrix(rQ):
    """geo3d rows: X = x, Y = y / 2, Z = (9.4 - z) / 2 (camera space, SCREEN 7)."""
    R = quat_matrix(rQ)
    s = (1.0, 0.5, -0.5)
    return [q14(s[i] * R[i][j]) for i in range(3) for j in range(3)]


def visible_faces(rQ):
    """Faces the original draws (rotated normal z >= 0.19), farthest first."""
    out = []
    for f in range(6):
        z = cm.qR(cm.F[f][0], rQ)[2]
        if z >= 0.19:
            out.append((z, f))
    return [f for z, f in sorted(out)]


# ------------------------------------------------------------------ the ball
def ball_images():
    """The original's ball and shadow (tick(), the last entry of the depth
    list) for each radius pr, scaled to SCREEN 7: {pr: (ball, shadow)}, each
    (x in page 3, y, width, height, cx, cy, rows of palette indices), cx / cy
    the centre's place in the image. 0 is transparent (TIMP)."""
    out, xb, xs = {}, 0, 0
    for pr in range(PR_MIN, PR_MAX + 1):
        R = pr * YS
        n = int(R)
        hw = int(math.ceil(2 * R)) + 1
        wd = 2 * hw + 2
        ball = [[0] * wd for _ in range(2 * n + 1)]
        shadow = [[0] * wd for _ in range(n + 2)]
        for yy in range(-n, n + 1):
            w = math.sqrt(max(0, R * R - yy * yy)) * 2      # SCREEN 7 pixels
            a, b = int(round(hw - w)), int(round(hw + w))
            for x in range(max(0, a), min(wd, b + 1)):
                ball[yy + n][x] = C[2] if yy > R / 2 else C[6]
                shadow[(yy + n) // 2][x] = SHADOW
        hy = n - int(round(YS))                              # the highlight (orig spr(px-1, py-1, 2px))
        for x in range(int(round(hw - XS)), int(round(hw + XS))):
            ball[hy][x] = C[7]
        bi = (xb, BALL_Y, wd, 2 * n + 1, hw, n, ball)
        si = (xs, SHADOW_Y, wd, n + 2, hw, n // 2, shadow)
        out[pr] = (bi, si)
        xb += wd + (wd & 1)
        xs += wd + (wd & 1)
    assert xb <= 512 and 2 * PR_MAX * YS + 1 <= 32
    return out


def ball_state(g):
    """The ball's model position (SU units, before the rotation), its
    shadow's, and the original's radius pr and depth key (original units)."""
    dm = dims(g.lv)
    h, cs, bR = dm["h"], dm["cs"], dm["bR"]

    def cP(c):
        return cm.LC(cm.F[c[0]], cm.K + bR + 0.02, (c[2] - h) * cs, (c[1] - h) * cs)
    k = cm.sm(g.mA[2]) if g.mA else 1
    p0, p1 = cP(g.mA[0] if g.mA else g.cur), cP(g.cur)
    bm = [p0[i] + (p1[i] - p0[i]) * k for i in range(3)]
    bV = cm.qR(bm, g.rQ)
    pz = 9.4 - bV[2]
    pr = max(PR_MIN, min(PR_MAX, int(bR * 185 / pz)))
    return dict(pt=tuple(round(c * SU) for c in bm), st=tuple(round(c * 0.93 * SU) for c in bm),
                pr=pr, key=pz - 0.5, cells=[g.cur] + ([g.mA[0]] if g.mA else []))


def near_cells(g, cells, steps=3):
    """Cells within `steps` grid steps (across face edges too) of the ball's."""
    dist = {tuple(c[:3]): 0 for c in cells}
    fr = list(dist)
    for k in range(1, steps + 1):
        nf = []
        for c in fr:
            for d in cm.I4:
                n = tuple(cm.mv(list(c), d, g.lv)[:3])
                if n not in dist:
                    dist[n] = k
                    nf.append(n)
        fr = nf
    return dist


WALL_LAYERS = (("mid", 0.5, 0.6), ("top", 1.0, 0.0))     # name, height / wH, depth bias


def wall_key(g, f, eu, ev, layer="top"):
    """The original's depth key of a wall's quad: the depth of its centre plus
    the layer's bias (bx(): 0.6 for the middle, 0 for the top, both 0.3 less
    on the active face)."""
    wH = dims(g.lv)["wH"]
    hf, zb = {n: (h, b) for n, h, b in WALL_LAYERS}[layer]
    z = cm.qR(cm.LC(cm.F[f], cm.K + wH * hf, eu, ev), g.rQ)[2]
    return 9.4 - z + zb - (0.3 if f == g.act else 0)
