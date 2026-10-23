#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Alex Moncks
"""The golden traffic of Cube Maze 3D on MSX, and its picture.

From the game states of the reference port (ref/cubemaze.py, 60 logic ticks a
second, one picture every second tick: 30 frames a second), writes what the
Z80 must send to geo3d v2.0 and to the V9968, and paints it with the models
checked against the RTL (sim/gen_scenes.py replay for geo3d,
sphere7/vdp6.py for the V9968 in SCREEN 7). The ball and the HUD are added
by a compositor (sprites and Z80 text in the real program).
"""
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
GEO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(GEO, "sim"))
sys.path.insert(0, os.path.join(GEO, "sphere7"))

import scene as sc  # noqa: E402
import cubemaze as cm  # noqa: E402
from gen_scenes import replay  # noqa: E402
from gen_vectors import model as core_model  # noqa: E402
import vdp6  # noqa: E402


def s16(x):
    return x & 0xFFFF


class Traffic:
    """Operations in program order: (kind, text), kinds W (geo3d port), V (VDP
    register), XB (VRAM block), R (wait geo3d), C (wait VDP), D (page flip),
    F (marks a RUN, for the replay)."""

    def __init__(self):
        self.ops, self.blocks, self.nrun = [], [], 0

    def w(self, sel, b):
        self.ops.append(("W", f"W {sel} {b & 0xFF:02x}"))

    def idx(self, i, data):
        self.w(0, i)
        for b in data:
            self.w(1, b)

    def words(self, i, ws):
        self.idx(i, [x for v in ws for x in (s16(v) & 0xFF, s16(v) >> 8)])

    def reg10(self, lo_idx, hi_idx, v):
        self.idx(lo_idx, [v & 0xFF])
        self.idx(hi_idx, [v >> 8])

    def vram(self, addr, data):
        self.blocks.append((addr, bytes(data)))
        self.ops.append(("XB", len(self.blocks) - 1))

    def vdp_cmd(self, regs):
        for r, v in regs:
            self.ops.append(("V", (r, v & 0xFF)))
        self.ops.append(("C", None))

    def hmmm(self, sx, sy, dx, dy, nx, ny):
        vals = (sx, sx >> 8, sy, sy >> 8, dx, dx >> 8, dy, dy >> 8, nx, nx >> 8, ny, ny >> 8, 0, 0)
        self.vdp_cmd(list(zip(range(32, 46), vals)) + [(46, 0xD0)])

    def lmmm(self, sx, sy, dx, dy, nx, ny, lop=8):
        """Logical copy (V9938 LMMM), TIMP by default: 0 is transparent."""
        vals = (sx, sx >> 8, sy, sy >> 8, dx, dx >> 8, dy, dy >> 8, nx, nx >> 8, ny, ny >> 8, 0, 0)
        self.vdp_cmd(list(zip(range(32, 46), vals)) + [(46, 0x90 | lop)])

    def run(self, ctrl):
        self.idx(0x48, [ctrl])
        self.ops.append(("R", None))
        self.ops.append(("F", self.nrun))
        self.nrun += 1

    def flip(self, ypage):
        self.ops.append(("C", None))
        self.ops.append(("D", ypage))


class Resident:
    """Which face blocks are in geo3d's RAMs, and where."""

    def __init__(self):
        self.map = {}            # face -> (sig, vbase, fbase, block)

    def plan(self, blocks):
        """blocks: {face: (sig, FaceBlock)} for the visible faces. Keeps the
        faces already in place and packs the others in the gaps; when they do
        not fit (the gaps are too small), packs every visible face again."""
        def size(blk):
            return len(blk.verts), sum(len(L[2]) for L in blk.layers)

        def place(used, n, lim):
            pos = 0
            for a, b in used:
                if pos + n <= a:
                    break
                pos = max(pos, b)
            if pos + n > lim:
                return None
            used.append((pos, pos + n))
            used.sort()
            return pos

        for keep_old in (True, False):
            keep = {f: v for f, v in self.map.items()
                    if keep_old and f in blocks and v[0] == blocks[f][0]}
            used_v = sorted((v[1], v[1] + size(v[3])[0]) for v in keep.values())
            used_f = sorted((v[2], v[2] + size(v[3])[1]) for v in keep.values())
            new = dict(keep)
            ok = True
            # the biggest first, so that a repack is a tight one
            for f in sorted((f for f in blocks if f not in keep), key=lambda f: -size(blocks[f][1])[0]):
                sig, blk = blocks[f]
                nv, nf = size(blk)
                vb, fb = place(used_v, nv, sc.V_SCRATCH), place(used_f, nf, sc.F_SCRATCH)
                if vb is None or fb is None:
                    ok = False
                    break
                new[f] = (sig, vb, fb, blk)
            if ok:
                break
        assert ok, "geo3d RAM full"
        self.map = new
        return [f for f in blocks if f not in keep]


def upload_block(tr, vbase, fbase, blk, only_goal=False):
    """Vertex, face and texture-coordinate streams of a face block (extended
    mode). only_goal: the goal's quads only (they move every frame)."""
    start_v = 0
    faces = []
    for name, hgt, fl in blk.layers:
        for fc in fl:
            faces.append((name, fc))
    if only_goal:
        gi = [i for i, (name, fc) in enumerate(faces) if name.startswith("goal")]
        if not gi:
            return 0
        vids = sorted({v for i in gi for v in faces[i][1][0]})
        start_v = vids[0]
        verts = blk.verts[start_v:vids[-1] + 1]
        f_lo, f_list = gi[0], [faces[i] for i in gi]
    else:
        verts, f_lo, f_list = blk.verts, 0, faces
    n = 0
    tr.reg10(0x40, 0x68, vbase + start_v)
    tr.w(0, 0x50)
    for v in verts:
        for c in v:
            tr.w(1, s16(c) & 0xFF)
            tr.w(1, s16(c) >> 8)
        n += 6
    tr.reg10(0x58, 0x6C, fbase + f_lo)
    tr.w(0, 0x52)
    for name, (ids, base, uv) in f_list:
        g = [vbase + i for i in ids]
        hi = sum(((x >> 8) & 3) << (2 * k) for k, x in enumerate(g))
        for b in [x & 0xFF for x in g] + [hi, 0, 0, 0, 0, 0, 0, base]:
            tr.w(1, b)
        n += 12
    tex = [(k, fc) for k, (name, fc) in enumerate(f_list) if fc[2]]
    if tex:
        tr.reg10(0x65, 0x6E, fbase + f_lo + tex[0][0])
        tr.w(0, 0x53)
        for k, (ids, base, uv) in tex:
            for b in uv:
                tr.w(1, b)
            n += 8
    return n


def texture_bytes(img):
    """TEX_W x TEX_H texels -> rows of G6 bytes (2 texels a byte, even x high)."""
    rows = []
    for row in img:
        b = bytearray(64)
        for x in range(0, sc.TEX_W, 2):
            b[x >> 1] = (row[x] << 4) | row[x + 1]
        for x in range(sc.TEX_W >> 1, 64):
            b[x] = 0x11                      # border: background colour
        rows.append(bytes(b))
    return rows


BALLS = sc.ball_images()


def ball_setup(tr):
    """Once: the ball and shadow images, in page 3 below the textures."""
    for pr, imgs in BALLS.items():
        for x, y, wd, ht, cx, cy, rows in imgs:
            assert x % 2 == 0 and wd % 2 == 0
            for k, row in enumerate(rows):
                tr.vram((y + k) * 256 + (x >> 1), bytes((row[i] << 4) | row[i + 1] for i in range(0, wd, 2)))


def stage_setup(tr, g):
    """Once per maze: the 12 floor textures, geo3d's configuration."""
    for f in range(6):
        for act in (0, 1):
            x, y = sc.tex_slot(f, act)
            rows = texture_bytes(sc.bake_texture(g, f, act))
            rows += [bytes([0x11]) * 64] * 4       # bottom border rows of the slot
            for k, rb in enumerate(rows):
                tr.vram((y + k) * 256 + (x >> 1), rb)
    tr.idx(0x6F, [1])                               # XCTRL: extended mode
    tr.words(0x18, [sc.FOCAL, sc.CX, sc.CY, sc.ZNEAR, sc.W, sc.H])
    tr.idx(0x64, [0])                               # TSTRIDE = 0 (no shading copies)


def frame(tr, g, res, ypage, stats):
    """One picture: background, the visible faces' RUNs, page flip."""
    tr.hmmm(0, sc.BG_Y, 0, ypage, 512, 212)
    vis = sc.visible_faces(g.rQ)
    blocks = {}
    for f in vis:
        blk = sc.face_block(g, f)
        sig = (id(g.G), g.lv, f == g.act)
        blocks[f] = (sig, blk)
    ups = res.plan(blocks)
    nbytes = 0
    for f in vis:
        sig, vb, fb, _ = res.map[f]
        blk = blocks[f][1]
        res.map[f] = (sig, vb, fb, blk)
        if f in ups:
            nbytes += upload_block(tr, vb, fb, blk)
        else:
            nbytes += upload_block(tr, vb, fb, blk, only_goal=True)
    tr.words(0x00, sc.geo_matrix(g.rQ) + [0, 0, sc.TZ])
    tr.idx(0x46, [ypage & 0xFF, ypage >> 8])
    nruns = 0
    # 1. every visible floor, with LOP = OR over the background's checkerboard
    #    (the dithers, see scene.py); floors of a convex cube do not overlap,
    #    so they only ever meet the background. Each face's vertices are
    #    transformed here, in its floor's RUN.
    tr.idx(0x45, [2])
    for f in vis:
        sig, vb, fb, blk = res.map[f]
        tx, ty = sc.tex_slot(f, f == g.act)
        assert blk.layers[0][0] == "floor"
        tr.reg10(0x54, 0x55, vb)                       # VFIRST
        tr.reg10(0x42, 0x6A, len(blk.verts))            # NVERT
        tr.idx(0x60, [tx & 0xFF, tx >> 8, ty & 0xFF, ty >> 8])
        tr.reg10(0x56, 0x57, fb)                        # FFIRST
        tr.reg10(0x59, 0x6D, len(blk.layers[0][2]))     # NFACE
        tr.run(0x07)
        nruns += 1
    # 2. the layers above the floors, face by face (farthest first), lowest
    #    layer first, LOP = IMP, with the projections left by step 1
    tr.idx(0x45, [0])
    tr.reg10(0x42, 0x6A, 0)
    for f in vis:
        sig, vb, fb, blk = res.map[f]
        fpos = fb + len(blk.layers[0][2])
        for name, hgt, fl in blk.layers[1:]:
            if not fl:
                continue
            tr.reg10(0x56, 0x57, fpos)                  # FFIRST
            tr.reg10(0x59, 0x6D, len(fl))               # NFACE
            tr.run(0x07)
            nruns += 1
            fpos += len(fl)
    nocc = 0
    if g.ph >= 1:
        nocc, nb = draw_ball(tr, g, res, vis, ypage)
        nbytes += nb
    tr.flip(ypage)
    stats.append(dict(vis=len(vis), runs=nruns, upload=nbytes, occ=nocc,
                      verts=sum(len(res.map[f][3].verts) for f in vis),
                      faces=sum(len(L[2]) for f in vis for L in res.map[f][3].layers)))


def draw_ball(tr, g, res, vis, ypage):
    """The ball and its shadow (LMMM from page 3), then the walls' quads
    (middle and top layers) that the original paints after the ball and that
    overlap it, painted again: each wall's own quads, unmerged, written to the
    scratch areas of the vertex and face RAMs and drawn by one RUN (geo3d
    orders them by depth)."""
    b = sc.ball_state(g)
    (bi, si) = BALLS[b["pr"]]
    px, py, _, _ = project(g, g.rQ, b["pt"])
    qx, qy, _, _ = project(g, g.rQ, b["st"])
    boxes = []
    for (x, y, wd, ht, cx, cy, rows), (ox, oy) in ((si, (qx, qy + round(2 * sc.YS))), (bi, (px, py))):
        dx, dy = ox - cx, oy - cy
        # clipped to the screen (the Z80 does the same)
        x0, y0 = max(0, -dx), max(0, -dy)
        x1, y1 = min(wd, sc.W - dx), min(ht, sc.H - dy)
        if x1 > x0 and y1 > y0:
            tr.lmmm(x + x0, y + y0, dx + x0, ypage + dy + y0, x1 - x0, y1 - y0)
        boxes.append((dx, dy, dx + wd, dy + ht))
    bx0, by0 = min(a[0] for a in boxes), min(a[1] for a in boxes)
    bx1, by1 = max(a[2] for a in boxes), max(a[3] for a in boxes)
    near = sc.near_cells(g, b["cells"])
    wH = sc.dims(g.lv)["wH"]
    occ = []
    for f in vis:
        blk = res.map[f][3]
        act = f == g.act
        for r, c, d, eu, ev, su, sv in blk.top_meta:
            if (f, r, c) not in near:
                continue
            for layer, hf, _ in sc.WALL_LAYERS:
                key = sc.wall_key(g, f, eu, ev, layer)
                if key >= b["key"]:
                    continue
                pts = sc.quad(f, wH * hf, eu, ev, su, sv)
                pp = [project(g, g.rQ, p) for p in pts]
                xs, ys = [p[0] for p in pp], [p[1] for p in pp]
                if max(xs) < bx0 or min(xs) >= bx1 or max(ys) < by0 or min(ys) >= by1:
                    continue
                col = sc.C[(7 if act else 2) if layer == "top" else (2 if act else 1)]
                occ.append((key, pts, col))
    occ.sort(key=lambda o: -o[0])                  # farthest first, as the original
    assert len(occ) <= sc.N_SCRATCH, len(occ)
    nb = 0
    if occ:
        # the walls' own top quads, unmerged (the runs may pass behind the ball)
        tr.reg10(0x40, 0x68, sc.V_SCRATCH)
        tr.w(0, 0x50)
        for _, pts, _ in occ:
            for p in pts:
                for v in p:
                    tr.w(1, s16(v) & 0xFF)
                    tr.w(1, s16(v) >> 8)
            nb += 24
        tr.reg10(0x58, 0x6C, sc.F_SCRATCH)
        tr.w(0, 0x52)
        for k, (_, _, col) in enumerate(occ):
            g4 = [sc.V_SCRATCH + 4 * k + i for i in range(4)]
            hi = sum(((x >> 8) & 3) << (2 * j) for j, x in enumerate(g4))
            for v in [x & 0xFF for x in g4] + [hi, 0, 0, 0, 0, 0, 0, col]:
                tr.w(1, v)
            nb += 12
        tr.reg10(0x54, 0x55, sc.V_SCRATCH)
        tr.reg10(0x42, 0x6A, 4 * len(occ))
        tr.reg10(0x56, 0x57, sc.F_SCRATCH)
        tr.reg10(0x59, 0x6D, len(occ))
        tr.run(0x07)
    return len(occ), nb


# ------------------------------------------------------------------ picture
def system(tr, frames_meta, on_flip=None):
    """Paints the traffic: returns one 212 x 512 array of palette indices per flip."""
    eng = []
    for k, t in tr.ops:
        if k == "W":
            eng.append(t)
        elif k == "R":
            eng.append("R")
        elif k == "F":
            eng.append(f"F {t}")
    log = replay(eng, {"draw": 0, "skip": 0, "cull": 0})
    groups, cur = {}, []
    for line in log:
        p = line.split()
        if p[0] in ("L", "M"):
            cur.append((p[0], [int(x, 16) for x in p[1:]]))
        elif p[0] == "F":
            groups[int(p[1])] = cur
            cur = []
    vr = vdp6.Vram6()
    regs = [0] * 64
    regs[51:59] = [0, 0, 0, 0, 0xFF, 1, 0xFF, 7]
    pages, run_i, cmds = [], 0, []
    ncmd = 0
    for k, t in tr.ops:
        if k == "XB":
            a, d = tr.blocks[t]
            vr.b[a:a + len(d)] = d
        elif k == "V":
            r, v = t
            regs[r] = v
            if r == 46:
                if v >> 4 == 9:
                    lmmm(vr, regs)
                else:
                    vdp6.apply_regs(vr, regs)
        elif k == "F":
            for kd, b in groups.get(t, []):
                r = list(regs)
                if kd == "M":
                    for kk, v in zip(list(range(32, 46)) + list(range(47, 51)), b[:18]):
                        r[kk] = v
                    r[46] = b[18]
                else:
                    for kk, v in zip(range(36, 46), b[:10]):
                        r[kk] = v
                    r[46] = b[10]
                regs[32:51] = r[32:51]
                vdp6.apply_regs(vr, r)
                ncmd += 1
        elif k == "D":
            if on_flip:
                on_flip(vr, t)
            pg = np.frombuffer(vr.page(t), np.uint8).reshape(212, 256)
            px = np.empty((212, 512), np.uint8)
            px[:, 0::2] = pg >> 4
            px[:, 1::2] = pg & 15
            pages.append(px)
            cmds.append(ncmd)
            ncmd = 0
    return pages, cmds


def lmmm(vr, r):
    """V9938 LMMM in G6 (not in vdp6.py, which holds what was checked against
    the RTL): pixel copy with a logical operation, DIX / DIY."""
    sx, sy = r[32] | (r[33] & 1) << 8, r[34] | (r[35] & 3) << 8
    dx, dy = r[36] | (r[37] & 1) << 8, r[38] | (r[39] & 3) << 8
    nx, ny = r[40] | (r[41] & 3) << 8, r[42] | (r[43] & 3) << 8
    ix = -1 if r[45] & 4 else 1
    iy = -1 if r[45] & 8 else 1
    for j in range(ny or 1024):
        for i in range(nx or 512):
            a, b = (sx + i * ix) & 511, (sy + j * iy) & 1023
            c, d = (dx + i * ix) & 511, (dy + j * iy) & 1023
            vr.put(c, d, vdp6.lop(r[46] & 15, vr.get(a, b), vr.get(c, d)))


def project(g, rQ, p):
    """geo3d's projection of a model point (phase 1 core, bit-exact)."""
    m = sc.geo_matrix(rQ)
    cfg = list(m) + [0, 0, sc.TZ, sc.FOCAL, sc.CX, sc.CY, sc.ZNEAR, sc.W, sc.H]
    return core_model(cfg, p)
