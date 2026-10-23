#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Alex Moncks
"""Every constant and table of the MSX program, in integers: the Python model
of the program (zmodel.py) and the Z80 program (cubemaze.asm, through
gen_assets.py) read the same numbers, so the model's traffic is what the
program must send, byte for byte.

The continuous parts of the original (quaternions, smoothstep, sines) are
computed here once, in floating point, from the original's own formulas
(ref/cubemaze.py), and kept as tables:
  - the 24 orientations of the cube (after a roll) as signed permutation
    matrices, and what a roll does to them;
  - the camera matrices (geo3d rows, Q2.14, SCREEN 7 aspect) of the title /
    preview spin, of the clear screens' spin, and of a roll in progress,
    each to be multiplied by the cube's orientation, which only permutes and
    negates columns;
  - the ball's smoothstep while it rolls from cell to cell;
  - per maze size, the integer geometry (in model units) and the texture
    rectangles.
"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "ref"))
sys.path.insert(0, HERE)

import cubemaze as cm  # noqa: E402

# ------------------------------------------------------------------ screen, geo3d
W, H = 512, 212
SU = 2048                         # model units per original unit
FOCAL, CX, CY, ZNEAR = 272, 256, 109, 16
TZ = round(9.4 * SU / 2)          # 9626: the camera at 9.4, rows Y and Z halved
YS = 212 / 144                    # original pixel -> SCREEN 7 lines
XS = 2 * YS                       # original pixel -> SCREEN 7 pixels
X0 = (512 - 160 * XS) / 2
LEVELS = (3, 4, 5, 6)

# ------------------------------------------------------------------ colours
PLAYLOAD = ["#000000", "#55415f", "#646964", "#d77355", "#508cd7", "#64b964", "#e6c86e", "#dcf5ff"]
C = {0: 0, 1: 3, 2: 5, 3: 11, 4: 4, 5: 7, 6: 13, 7: 9}      # original colour -> solid index
D_GREY, D_ACT = 2, 14            # dithers over the background (see scene.py)
STAR = {1: 3, 2: 2}
SHADOW = 1
CHECK_W, CHECK_H = 3, 1


def _rgb(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def palette(act_colour):
    """16 RGB entries; act_colour: the original colour of the active face."""
    P = [_rgb(h) for h in PLAYLOAD]
    pal = [P[0]] * 16
    for c, i in C.items():
        pal[i] = P[c]
    pal[1] = P[0]
    pal[D_GREY], pal[D_GREY + 1] = P[2], P[1]
    pal[D_ACT], pal[D_ACT + 1] = P[act_colour], P[1]
    return pal


def pal_bytes(act_colour, first=0, n=16):
    """Palette port bytes for entries first .. first + n - 1 (EPAL: R, G, B,
    5 bits each, one byte each, from the index set in R#16)."""
    out = []
    for rgb in palette(act_colour)[first:first + n]:
        out += [min(31, round(c * 31 / 255)) for c in rgb]
    return out


def pal_rgb(act_colour):
    """The colours the V9968 shows for those entries (5 bits back to 8)."""
    return [tuple(round(min(31, round(c * 31 / 255)) * 255 / 31) for c in rgb) for rgb in palette(act_colour)]


FACE_COLOUR = [f[3] for f in cm.F]            # 4, 3, 4, 6, 5, 6

# ------------------------------------------------------------------ VRAM
BG_Y = 512                       # page 2: checkerboard + stars (212 lines)
FONT_Y = 724                     # page 2: 3 rows of glyph masks, 24 x 14 each
TEX_Y = 768                      # page 3: 12 floor textures in slots of 128 x 64
TEX_W, TEX_H = 120, 60
BALL_Y, SHADOW_Y = 960, 992      # page 3: ball and shadow images
PR_MIN, PR_MAX = 3, 10


def tex_slot(face, active):
    s = face * 2 + (1 if active else 0)
    return (s % 4) * 128, TEX_Y + (s // 4) * 64


# ------------------------------------------------------------------ geo3d RAMs
VSLOT, FSLOT = 321, 104          # a face block: vertices, faces (3 slots)
N_SCRATCH = 15                   # quads painted again over the ball, at most
V_SCRATCH = 3 * VSLOT            # 963 .. 1022
F_SCRATCH = 3 * FSLOT            # 312 .. 326
assert V_SCRATCH + 4 * N_SCRATCH <= 1024

# ------------------------------------------------------------------ orientation group
AXES = [(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)]


def axis_index(v):
    return AXES.index(tuple(int(round(x)) for x in v))


def qmat(q):
    """R with R v = qR(v, q) (floats)."""
    cols = [cm.qR(e, q)[:3] for e in ((1, 0, 0), (0, 1, 0), (0, 0, 1))]
    return [[cols[j][i] for j in range(3)] for i in range(3)]


def mmul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def mvec(a, v):
    return [sum(a[i][k] * v[k] for k in range(3)) for i in range(3)]


# the roll rotations: wn (the new face's normal, rotated) -> r = qN([-wn.z, 0, wn.x, wn.y + 1])
ROLL_WN = [(1, 0, 0), (-1, 0, 0), (0, 0, 1), (0, 0, -1)]
ROLL_Q = [cm.qN([-w[2], 0, w[0], w[1] + 1]) for w in ROLL_WN]
ROLL_M = [[[int(round(x)) for x in row] for row in qmat(q)] for q in ROLL_Q]


def _group():
    ident = ((1, 0, 0), (0, 1, 0), (0, 0, 1))
    seen, order = {ident: 0}, [ident]
    i = 0
    while i < len(order):
        m = [list(r) for r in order[i]]
        for r in ROLL_M:
            n = tuple(tuple(x) for x in mmul(r, m))
            if n not in seen:
                seen[n] = len(order)
                order.append(n)
        i += 1
    assert len(order) == 24
    return order, seen


ORIENT, _ORIENT_IDX = _group()
ROLLNEXT = [[_ORIENT_IDX[tuple(tuple(x) for x in mmul(ROLL_M[a], [list(r) for r in ORIENT[o]]))]
             for a in range(4)] for o in range(24)]
ROTN = [[axis_index(mvec(ORIENT[o], cm.F[f][0])) for f in range(6)] for o in range(24)]
UPFACE = [ROTN[o].index(2) for o in range(24)]


def perm(o):
    """P(o) column by column: (row of the 1, sign) per column j."""
    m = ORIENT[o]
    out = []
    for j in range(3):
        for k in range(3):
            if m[k][j]:
                out.append((k, m[k][j]))
    return out


PERM = [perm(o) for o in range(24)]

# ------------------------------------------------------------------ camera matrices
VQ = cm.VQ
S_ROWS = (1.0, 0.5, -0.5)


def q14(x):
    return max(-32768, min(32767, int(math.floor(x * 16384 + 0.5))))


def geo_rows(R):
    """geo3d matrix (9 Q2.14 words, row-major), rows scaled for SCREEN 7."""
    return [q14(S_ROWS[i] * R[i][j]) for i in range(3) for j in range(3)]


def apply_perm(m9, o):
    """B . P(o): column j of the result is sign * column perm[j] of B."""
    out = [0] * 9
    for j, (k, s) in enumerate(PERM[o]):
        for i in range(3):
            out[i * 3 + j] = s * m9[i * 3 + k]
    return out


# rolls: rA += 0.04 per tick (floating point, as the original): the steps
RA_STEPS = []
_s = 0.0
while _s < 1:
    _s += 0.04
    RA_STEPS.append(_s)
K_END = len(RA_STEPS)            # 25: the roll ends at its 25th tick


def roll_rt(a, k):
    """r_t: the roll in progress after k steps (k = 0: none): nlerp(1, r, sm(sum))."""
    if k == 0:
        return [0.0, 0.0, 0.0, 1.0]
    t = cm.sm(RA_STEPS[k - 1])
    q = ROLL_Q[a]
    return cm.qN([v * t + (1 - t) * (1.0 if i == 3 else 0.0) for i, v in enumerate(q)])


RVQ = qmat(VQ)
# B[a][k] = S . R(VQ) . R(r_t(a, k)), k = 0 .. K_END - 1 (k = 0: no roll)
ROLLB = [[geo_rows(mmul(RVQ, qmat(roll_rt(a, k)))) for k in range(K_END)] for a in range(4)]
# the bare roll matrices R(r_t), Q2.14, for the clear screens frozen mid-roll
ROLLR = [[[q14(x) for row in qmat(roll_rt(a, k)) for x in row] for k in range(K_END)] for a in range(4)]

# spins: T mod 628 (the original's periods: 0.02 rad and 0.01 rad per tick)
SPIN_N = 628
TITLE = [geo_rows(qmat(cm.qM(VQ, cm.qE(0.22 + math.sin(2 * math.pi * t / 314) * 0.1,
                                       2 * math.pi * t / 628)))) for t in range(SPIN_N)]
CLEARM = [geo_rows(qmat(cm.qM(VQ, cm.qE(0.15, 2 * math.pi * t / 628)))) for t in range(SPIN_N)]


def mat_mul_q14(a9, b9):
    """(A . B) in Q2.14 as the Z80 does it: sum of the 3 products, +8192, >> 14."""
    out = []
    for i in range(3):
        for j in range(3):
            s = sum(a9[i * 3 + k] * b9[k * 3 + j] for k in range(3))
            out.append((s + 8192) >> 14)
    return out


# visibility: the rotated normal's z >= 0.19 <=> s * M[2][i] <= -VIS_T (row Z = -0.5 R)
VIS_T = 1557                     # ceil(0.19 * 0.5 * 16384) = ceil(1556.48)


def visible_faces(m9):
    """Faces facing the camera, farthest first (ties: lower face first)."""
    out = []
    for f in range(6):
        n = cm.F[f][0]
        i = next(k for k in range(3) if n[k])
        v = n[i] * m9[6 + i]                     # s * M[2][i]
        if v <= -VIS_T:
            out.append((-v, f))                  # nearer: more negative v
    out.sort()
    return [f for _, f in out]


# the key -> direction table: dirmap[o][sD] (the original's argmax, on the
# static camera of orientation o, its active face being the face up)
def dirmap_for(R, act):
    res = []
    for sD in range(4):
        best, bD = 0, -9
        for d in range(4):
            lc = mvec(R, cm.dV(act, d))
            v = (lc[0] if sD > 1 else -lc[1]) * (1 if sD & 1 else -1)
            if v > bD:
                bD, best = v, d
        res.append(best)
    return res


DIRMAP = [dirmap_for(mmul(RVQ, [list(r) for r in ORIENT[o]]), UPFACE[o]) for o in range(24)]


def _check_dirmap():
    """The original reads the keys with the camera at the start of the tick:
    on the tick a roll ends, that is the roll's step K_END - 1, not the final
    orientation; the table must give the same answers there."""
    for o in range(24):
        for a in range(4):
            o2 = ROLLNEXT[o][a]
            R = mmul(mmul(RVQ, qmat(roll_rt(a, K_END - 1))), [list(r) for r in ORIENT[o]])
            assert dirmap_for(R, UPFACE[o2]) == DIRMAP[o2], (o, a)


_check_dirmap()

# ball moves: mA += 0.1 per tick; k = sm(mA) for the states shown (Q2.14)
MA_STEPS = []
_s = 0.0
while _s < 1:
    _s += 0.1
    MA_STEPS.append(_s)
J_END = len(MA_STEPS)            # 11
K10 = [0] + [q14(cm.sm(s)) for s in MA_STEPS[:-1]]       # index j = 1..10
SHADOW_K = q14(0.93)             # 15237

# goal box: n = 0.12 + sin(T * 0.15) * 0.04 -> T mod 42
GOAL_N = 42
GOAL_H2 = [round((0.12 + math.sin(2 * math.pi * t / GOAL_N) * 0.04) * SU) for t in range(GOAL_N)]
GOAL_H1 = [round((0.12 + math.sin(2 * math.pi * t / GOAL_N) * 0.04) * 0.5 * SU) for t in range(GOAL_N)]


# ------------------------------------------------------------------ per maze size
class Lv:
    def __init__(self, lv):
        self.lv = lv
        cs = cm.K * 2 / lv
        self.HG = round(cm.K * SU / lv)           # half a cell
        self.KS = lv * self.HG                   # the cube's half size
        self.WL = round((cs + cs * 0.11) / 2 * SU)
        self.WW = round(cs * 0.11 * SU)
        self.HMID = self.KS + round(cs * 0.28 * 0.5 * SU)
        self.HTOP = self.KS + round(cs * 0.28 * SU)
        self.GB = round(cs * 0.22 * SU)
        bR = cs * 0.26
        self.HBALL = self.KS + round((bR + 0.02) * SU)
        # pr = max(3, int(bR * 185 / pz)), pz = Zgeo / 1024: pr >= p <=> Zgeo <= bR*185*1024/p
        self.PR_Z = [int(bR * 185 * 1024 / p) for p in range(PR_MIN + 1, PR_MAX + 1)]
        self.HC43 = round(cs * 0.43 * SU)
        self.HP10 = round(cs * 0.10 * SU)
        self.HP36 = round(cs * 0.36 * SU)
        self.cw, self.ch = TEX_W // lv, TEX_H // lv
        self.nv_floor = (lv + 1) ** 2
        n = lv * lv
        # neighbours: ci = f * n + r * lv + c; MV[ci][d] = (ci', d_in)
        self.MV = []
        for f in range(6):
            for r in range(lv):
                for c in range(lv):
                    row = []
                    for d in range(4):
                        nx = cm.mv([f, r, c], d, lv)
                        row.append((nx[0] * n + nx[1] * lv + nx[2], nx[3]))
                    self.MV.append(row)

    def ci(self, f, r, c):
        return f * self.lv * self.lv + r * self.lv + c

    def pr_of(self, zgeo):
        pr = PR_MIN
        for p, zt in zip(range(PR_MIN + 1, PR_MAX + 1), self.PR_Z):
            if zgeo <= zt:
                pr = p
        return pr

    def tx(self, u):
        """texel column of model coordinate u (rounded, clipped 0..TEX_W)"""
        x = ((u + self.KS) * 2 * TEX_W + 2 * self.KS) // (4 * self.KS)
        return max(0, min(TEX_W, x))

    def ty(self, v):
        y = ((v + self.KS) * 2 * TEX_H + 2 * self.KS) // (4 * self.KS)
        return max(0, min(TEX_H, y))


LV = {lv: Lv(lv) for lv in LEVELS}


def face_point(f, n, u, v):
    """LC(F[f], n, u, v) with integer n, u, v (the axes are signed unit axes)."""
    p = [0, 0, 0]
    for axis, val in zip(cm.F[f][:3], (n, u, v)):
        for i in range(3):
            if axis[i]:
                p[i] += axis[i] * val
    return tuple(p)


# per face: (component, sign) of the normal, u and v axes
FACE_AXES = []
for _f in range(6):
    row = []
    for axis in cm.F[_f][:3]:
        i = next(k for k in range(3) if axis[k])
        row.append((i, axis[i]))
    FACE_AXES.append(row)

Q4 = ((-1, -1), (1, -1), (1, 1), (-1, 1))

# ------------------------------------------------------------------ HUD
ADV = 24                         # character advance (pixels); glyphs 20 x 14 in cells of 24 x 14


def hx(x):
    """the original's column x -> an even SCREEN 7 pixel"""
    return 2 * int(math.floor((X0 + x * XS) / 2 + 0.5))


def hy(y):
    return int(math.floor(y * YS + 0.5))


CODE_ABC = "BCDFGHJKLMNPRSTVWXZ2345679"


def stage_code(unl):
    if unl <= 3:
        return None
    x = (0x9E3779B9 * unl) & 0xFFFFFFFF
    out = ""
    for _ in range(4):
        x ^= (x << 13) & 0xFFFFFFFF
        x ^= x >> 17
        x ^= (x << 5) & 0xFFFFFFFF
        out += CODE_ABC[x % len(CODE_ABC)]
    return out


CODES = {u: stage_code(u) for u in (4, 5, 6)}
assert len(set(CODES.values())) == 3

if __name__ == "__main__":
    print("orientations", len(ORIENT), "K_END", K_END, "J_END", J_END, "K10", K10)
    print("UPFACE", UPFACE)
    print("DIRMAP", DIRMAP[:4])
    for lv in LEVELS:
        L = LV[lv]
        print(lv, vars(L)["HG"], L.KS, L.WL, L.WW, L.HMID, L.HTOP, L.GB, L.HBALL, L.PR_Z)
    print("codes", CODES)
