#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Alex Moncks
"""Cube Maze 3D for MSX: the program, in Python, at the level of the Z80.

This is the specification of cubemaze.asm: the same state, the same integer
arithmetic, the same tables (ztables.py), and the same traffic to geo3d and
to the V9968, in the same order. run_z80.py runs the ROM in a Z80 emulator
and compares, frame by frame, what the ROM sends and what this model sends.

Differences from the reference port (ref/cubemaze.py, checked against the
original JavaScript), all on purpose:
  - integer time (ticks) for the clock and the score; integer geometry;
  - camera matrices from tables (the spins repeat every 628 ticks, a roll in
    25 steps, the cube's orientation as one of 24 permutations);
  - the random generator (the same xorshift32) also runs once per tick on
    the title screen, so each game gets another maze;
  - a maze whose face would not fit geo3d's RAM slot is generated again;
  - ESC on the title opens the stage code entry (the original's B unlocked
    every size; there is no saving on the MSX);
  - at most 30 pictures a second, the game at 60 ticks a second as the
    original: a picture advances it by as many ticks as blanks the previous
    one was shown (2 to 4; the counts come from the ROM's run);
  - on the title the cube keeps its maze while another size is picked (the
    original redraws the old maze at the new size).

Traffic ops (lists of tuples, program order):
  ("G", sel, byte)        geo3d port write (sel 0: index, 1: data)
  ("GC", (x, y, z))       a single-vertex projection the program asks geo3d
                          for (the writes are also in G ops); answers read back
  ("RUN", n)              marks geo3d's RUN number n (after its G writes)
  ("CMD", first, values)  a VDP command: registers first.. (R#46 last)
  ("VW", addr, bytes)     VRAM writes through the data port
  ("PAL", index, bytes)   palette writes (R#16 = index, then the bytes)
  ("FLIP", page)          R#2: page shown, at a vertical blank
  ("REG", r, v)           other VDP register writes
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
GEO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(GEO, "sim"))
sys.path.insert(0, os.path.join(GEO, "sphere7"))
sys.path.insert(0, os.path.join(GEO, "game", "tools"))

import ztables as zt  # noqa: E402
from ztables import C  # noqa: E402
import cubemaze as cm  # noqa: E402
from gen_vectors import model as core_model  # noqa: E402

# ------------------------------------------------------------------ random generator
class Rng:
    def __init__(self, s=0x2545F491):
        self.s = s

    def next(self):
        s = self.s
        s ^= (s << 13) & 0xFFFFFFFF
        s ^= s >> 17
        s ^= (s << 5) & 0xFFFFFFFF
        self.s = s
        return s

    def below(self, n):
        """floor(rnd() * n), n = 2..4 (exact: (s * n) >> 32)"""
        return (self.next() * n) >> 32

    def shuffle(self):
        a = [0, 1, 2, 3]
        for i in range(3, 0, -1):
            j = self.below(i + 1)
            a[i], a[j] = a[j], a[i]
        return a


# ------------------------------------------------------------------ the maze, per face
def face_walls(L, G, f):
    """The face's walls in the original's edge order: (r, c, d, tu, tv)."""
    lv = L.lv
    out = []
    for r in range(lv):
        for c in range(lv):
            g = G[L.ci(f, r, c)]
            for d in range(4):
                if d < 2 or (d == 3 and c == 0) or (d == 2 and r == lv - 1):
                    if not (g >> d) & 1:
                        tu = 2 * c + 1 - lv + ((1 if d == 1 else -1) if d & 1 else 0)
                        tv = 2 * r + 1 - lv + (0 if d & 1 else (-1 if d == 0 else 1))
                        out.append((r, c, d, tu, tv))
    return out


def face_runs(L, G, f):
    """The walls merged into runs: (o, line, ta, tb); o = 0: along u on the
    line v = line; o = 1: along v on u = line; ta..tb the first and last
    wall centres (half-cells)."""
    lv = L.lv
    runs = []
    # horizontal lines: v = -lv (d 0 of row 0), 2r - lv (d 0 of row r), lv (d 2 of row lv-1)
    for k in range(lv + 1):
        line = 2 * k - lv
        cur = None
        for c in range(lv):
            if k < lv:
                wall = not (G[L.ci(f, k, c)] & 1)
            else:
                wall = not (G[L.ci(f, lv - 1, c)] & 4)
            t = 2 * c + 1 - lv
            if wall:
                cur = [t, t] if cur is None else [cur[0], t]
            elif cur is not None:
                runs.append((0, line, cur[0], cur[1]))
                cur = None
        if cur is not None:
            runs.append((0, line, cur[0], cur[1]))
    # vertical lines: u = -lv (d 3 of column 0), 2c + 2 - lv (d 1 of column c)
    for k in range(lv + 1):
        line = 2 * k - lv
        cur = None
        for r in range(lv):
            if k == 0:
                wall = not (G[L.ci(f, r, 0)] & 8)
            else:
                wall = not (G[L.ci(f, r, k - 1)] & 2)
            t = 2 * r + 1 - lv
            if wall:
                cur = [t, t] if cur is None else [cur[0], t]
            elif cur is not None:
                runs.append((1, line, cur[0], cur[1]))
                cur = None
        if cur is not None:
            runs.append((1, line, cur[0], cur[1]))
    return runs


def run_corners(L, run):
    """(u0, u1, v0, v1) of a run's rectangle."""
    o, line, ta, tb = run
    a, b = ta * L.HG - L.WL, tb * L.HG + L.WL
    lo, hi = line * L.HG - L.WW, line * L.HG + L.WW
    return (a, b, lo, hi) if o == 0 else (lo, hi, a, b)


def rect_quad(f, h, u0, u1, v0, v1):
    """Q4 order: (-1,-1) (1,-1) (1,1) (-1,1)."""
    return [zt.face_point(f, h, u0, v0), zt.face_point(f, h, u1, v0),
            zt.face_point(f, h, u1, v1), zt.face_point(f, h, u0, v1)]


def block_size(L, nruns, goal):
    return L.nv_floor + (8 if goal else 0) + 8 * nruns, L.lv * L.lv + (2 if goal else 0) + 2 * nruns


# ------------------------------------------------------------------ the game
class Game:
    def __init__(self):
        self.rng = Rng()
        self.ph, self.lv, self.unl, self.best, self.T = 0, 3, 3, [0, 0, 0, 0], 0
        self.T628 = self.T42 = 0
        self.sc, self.rep = 0, 9
        self.code, self.cpos = [0, 0, 0, 0], 0
        self.sfx = []                     # this tick's sound effects
        self.prev = [0] * 6
        self.stage = 0                    # counts gen(): textures and slots follow it
        self.gen()

    # -------------------------------------------------------------- maze
    def gen(self):
        while True:
            self._gen()
            L = zt.LV[self.lv]
            ok = True
            for f in range(6):
                nv, nf = block_size(L, len(face_runs(L, self.G, f)), self.gl // (L.lv * L.lv) == f)
                if nv > zt.VSLOT or nf > zt.FSLOT:
                    ok = False
            if ok:
                break
        self.stage += 1
        self.glv = self.lv                # the maze's size: drawn with it (the title's
                                          # selection in lv may differ)

    def _gen(self):
        L = zt.LV[self.lv]
        lv = self.lv
        self.G = [0] * (6 * lv * lv)
        self.act, self.el, self.rot = 0, 0, 0
        self.mv = None                    # (from ci, to ci, j)
        self.roll = None                  # (axis, k)
        self.o = 0
        self.prv = 179
        start = L.ci(0, lv >> 1, lv >> 1)
        self.cur = self.st = start
        gl, gdp = start, 0
        stack = []

        def enter(p, dp):
            nonlocal gl, gdp
            if dp > gdp:
                gl, gdp = p, dp
            stack.append([p, dp, self.rng.shuffle(), 0])

        enter(start, 0)
        while stack:
            fr = stack[-1]
            if fr[3] == 4:
                stack.pop()
                continue
            d = fr[2][fr[3]]
            fr[3] += 1
            p = fr[0]
            n, din = L.MV[p][d]
            if not self.G[n]:
                self.G[p] |= 1 << d
                self.G[n] |= 1 << ((din + 2) & 3)
                enter(n, fr[1] + 1)
        self.gl = gl

    def go(self, s):
        self.lv = s
        self.gen()
        self.ph = 1
        self.sfx.append(1)

    # -------------------------------------------------------------- camera
    def cam(self):
        """The camera of this tick (taken at its start, as the original)."""
        if self.ph in (0, 1, 5):
            return ("spin", self.T628)
        if self.ph == 2:
            a, k = self.roll if self.roll else (0, 0)
            return ("play", self.o, a, k)
        a, k = self.roll if self.roll else (0, 0)
        return ("clear", self.T628, self.o, a, k)

    # -------------------------------------------------------------- a tick
    def tick(self, held):
        prev = self.prev
        self.prev = list(held)
        btnp = [held[i] and not prev[i] for i in range(6)]
        btn = held
        self.sfx = []
        self.T += 1
        self.T628 = (self.T628 + 1) % zt.SPIN_N
        self.T42 = (self.T42 + 1) % zt.GOAL_N
        self.camera = self.cam()
        stp = (btnp[3] - btnp[2]) or (btnp[1] - btnp[0])
        ph = self.ph
        if ph == 0:
            self.rng.next()
            if stp:
                self.lv = min(self.unl, max(3, self.lv + stp))
                self.sfx.append(0)
            if btnp[5]:
                self.ph = 5
                self.cpos = 0
                self.sfx.append(0)
            elif btnp[4]:
                self.go(self.lv)
        elif ph == 5:
            self.rng.next()
            if btnp[0] or btnp[1]:
                self.code[self.cpos] = (self.code[self.cpos] + (1 if btnp[0] else -1)) % len(zt.CODE_ABC)
                self.sfx.append(0)
            elif btnp[2] or btnp[3]:
                self.cpos = max(0, min(3, self.cpos + (1 if btnp[3] else -1)))
                self.sfx.append(0)
            if btnp[4]:
                s = "".join(zt.CODE_ABC[i] for i in self.code)
                u = next((u for u in (6, 5, 4) if zt.CODES[u] == s), 0)
                if u:
                    self.unl = max(self.unl, u)
                    self.ph = 0
                    self.sfx.append(1)
                else:
                    self.sfx.append(2)
            elif btnp[5]:
                self.ph = 0
        elif ph == 1:
            self.prv -= 1
            if self.prv <= 0 or btnp[4]:
                self.ph = 2
            if btnp[5]:
                self.go(self.lv)
        elif ph == 2:
            self.el = min(65535, self.el + 1)
            if btnp[5]:
                self.go(self.lv)
                return
            if self.mv:
                fr, to, j = self.mv
                j += 1
                self.mv = (fr, to, j)
                if j >= zt.J_END:
                    self.mv = None
                    if self.cur == self.gl:
                        self.sfx.append(3)
                        self.sc = max(0, (60003 - self.el - 300 * self.rot) // 6)
                        if self.sc > self.best[self.lv - 3]:
                            self.best[self.lv - 3] = self.sc
                        if self.lv >= self.unl and self.unl < 6:
                            self.unl = self.lv + 1
                        self.ph = 4 if self.lv > 5 else 3
            if self.roll:
                a, k = self.roll
                k += 1
                if k >= zt.K_END:
                    self.o = zt.ROLLNEXT[self.o][a]
                    self.roll = None
                else:
                    self.roll = (a, k)
            if not self.mv and not self.roll:
                sD = 4
                for i in range(4):
                    if btnp[i]:
                        sD = i
                        break
                    if btn[i]:
                        self.rep -= 1
                        if self.rep < 0:
                            sD = i
                            break
                if not any(btn[:4]):
                    self.rep = 9
                if sD < 4:
                    self.rep = 9
                    d = zt.DIRMAP[self.o][sD]
                    L = zt.LV[self.lv]
                    if not (self.G[self.cur] >> d) & 1:
                        self.sfx.append(2)
                    else:
                        nx, _ = L.MV[self.cur][d]
                        self.mv = (self.cur, nx, 0)
                        nf = nx // (L.lv * L.lv)
                        if nf != self.cur // (L.lv * L.lv):
                            self.rot += 1
                            self.sfx.append(1)
                            wn = zt.ROTN[self.o][nf]          # 0 +x, 1 -x, 4 +z, 5 -z
                            self.roll = ({0: 0, 1: 1, 4: 2, 5: 3}[wn], 0)
                        else:
                            self.sfx.append(0)
                        self.cur = nx
                        self.act = nf
        else:
            if btnp[4]:
                self.go(self.lv + 1 if ph == 3 and self.lv < 6 else 3)
            elif btnp[5]:
                self.ph = 0


# ------------------------------------------------------------------ pictures
FONT = None


def font():
    global FONT
    if FONT is None:
        from sprites import _G
        g = dict(_G)
        g.update({
            "/": ["....#", "...#.", "...#.", "..#..", ".#...", ".#...", "#...."],
            "[": [".###.", ".#...", ".#...", ".#...", ".#...", ".#...", ".###."],
            "]": [".###.", "...#.", "...#.", "...#.", "...#.", "...#.", ".###."],
            "?": [".###.", "#...#", "....#", "...#.", "..#..", ".....", "..#.."],
        })
        FONT = g
    return FONT


CHARSET = " 0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZx:/[]?!"
GLYPHS_PER_ROW = 21


def glyph_cell(ch):
    k = CHARSET.index(ch)
    return (k % GLYPHS_PER_ROW) * zt.ADV, zt.FONT_Y + (k // GLYPHS_PER_ROW) * 14


def font_rows():
    """The glyph masks (15 = ink, 0 = paper), 3 rows of 21 cells of 24 x 14."""
    f = font()
    img = np.zeros((42, 512), np.uint8)
    for k, ch in enumerate(CHARSET):
        g = f[ch]
        x0, y0 = (k % GLYPHS_PER_ROW) * zt.ADV, (k // GLYPHS_PER_ROW) * 14
        for r, row in enumerate(g):
            for c, b in enumerate(row):
                if b == "#":
                    img[y0 + 2 * r:y0 + 2 * r + 2, x0 + 4 * c:x0 + 4 * c + 4] = 15
    return img


def background_rows():
    yy, xx = np.mgrid[0:212, 0:512]
    img = (((xx // zt.CHECK_W) + (yy // zt.CHECK_H)) & 1).astype(np.uint8)
    for i in range(24):
        x, y, c = (i * 67 + 13) % 160, (i * 43 + 7) % 120, 1 if i & 3 else 2
        X = int(round(zt.X0 + x * zt.XS))
        img[int(round(y * zt.YS)), X:X + 2] = zt.STAR[c]
    return img


def ball_images():
    """{pr: (ball, shadow)}: (x, y, w, h, cx, cy, rows) in page 3."""
    import math
    out, xb, xs = {}, 0, 0
    for pr in range(zt.PR_MIN, zt.PR_MAX + 1):
        R = pr * zt.YS
        n = int(R)
        hw = int(math.ceil(2 * R)) + 1
        wd = 2 * hw + 2
        ball = [[0] * wd for _ in range(2 * n + 1)]
        shadow = [[0] * wd for _ in range(n + 2)]
        for yy in range(-n, n + 1):
            w = math.sqrt(max(0, R * R - yy * yy)) * 2
            a, b = int(round(hw - w)), int(round(hw + w))
            for x in range(max(0, a), min(wd, b + 1)):
                ball[yy + n][x] = C[2] if yy > R / 2 else C[6]
                shadow[(yy + n) // 2][x] = zt.SHADOW
        hy_ = n - int(round(zt.YS))
        for x in range(int(round(hw - zt.XS)), int(round(hw + zt.XS))):
            ball[hy_][x] = C[7]
        out[pr] = ((xb, zt.BALL_Y, wd, 2 * n + 1, hw, n, ball),
                   (xs, zt.SHADOW_Y, wd, n + 2, hw, n // 2, shadow))
        xb += wd
        xs += wd
    assert xb <= 512
    return out


BALLS = ball_images()


def rows_bytes(rows):
    out = bytearray()
    for row in rows:
        for x in range(0, len(row), 2):
            out.append((row[x] << 4) | row[x + 1])
    return bytes(out)


def big_digit_runs(ch):
    """runs of set pixels per glyph row: [(r, c0, c1)]"""
    out = []
    for r, row in enumerate(font()[ch]):
        c = 0
        while c < 5:
            if row[c] == "#":
                c0 = c
                while c < 5 and row[c] == "#":
                    c += 1
                out.append((r, c0, c))
            else:
                c += 1
    return out


# ------------------------------------------------------------------ the program's traffic
TOP_DY = 212                     # the cached bars: page 0, lines 212-229
BOT_DY = 230 - zt.hy(132)        # and 230-247
ROW_Y = (468, 212, 226, 240)     # the title's / code screen's text rows: page 1
                                 # 468-481, page 0 212-253 (the play bars' lines)


class Machine:
    """What the Z80 program sends, from boot, frame after frame."""

    def __init__(self):
        self.cache_top = self.cache_bot = None
        self.cmode, self.cache_rows = 0, [None] * 4
        self.occ_sig, self.nocc = None, 0
        self.ops = []
        self.nrun = 0
        self.g = Game()
        self.slots = [None, None, None]      # (face, act at upload, stage)
        self.stage_baked = None
        self.page = 1                        # the page being drawn
        self.pal_act = None
        self.frame_no = 0
        self.matrix = [0] * 9
        self.flip_pending = None             # (page, act colour) of the frame drawn last
        self.frames_meta = []
        self.boot()

    # -------------------------------------------------------------- port helpers
    def gw(self, sel, b):
        self.ops.append(("G", sel, b & 0xFF))

    def gidx(self, i, data=()):
        self.gw(0, i)
        for b in data:
            self.gw(1, b)

    def gwords(self, i, ws):
        self.gidx(i, [x for v in ws for x in ((v & 0xFFFF) & 0xFF, (v & 0xFFFF) >> 8)])

    def g10(self, lo, hi, v):
        self.gidx(lo, [v & 0xFF])
        self.gidx(hi, [(v >> 8) & 3])

    def cmd(self, first, values):
        self.ops.append(("CMD", first, [v & 0xFF for v in values]))

    def hmmv(self, x, y, nx, ny, col):
        self.cmd(36, [x, x >> 8, y, y >> 8, nx, nx >> 8, ny, ny >> 8, col, 0, 0xC0])

    def lmmv(self, x, y, nx, ny, col, lop=0):
        self.cmd(36, [x, x >> 8, y, y >> 8, nx, nx >> 8, ny, ny >> 8, col, 0, 0x80 | lop])

    def hmmm(self, sx, sy, dx, dy, nx, ny):
        self.cmd(32, [sx, sx >> 8, sy, sy >> 8, dx, dx >> 8, dy, dy >> 8, nx, nx >> 8, ny, ny >> 8,
                      0, 0, 0xD0])

    def lmmm(self, sx, sy, dx, dy, nx, ny, lop):
        self.cmd(32, [sx, sx >> 8, sy, sy >> 8, dx, dx >> 8, dy, dy >> 8, nx, nx >> 8, ny, ny >> 8,
                      0, 0, 0x90 | lop])

    def run(self):
        self.gidx(0x48, [0x07])
        self.ops.append(("RUN", self.nrun))
        self.nrun += 1

    # -------------------------------------------------------------- boot
    def boot(self):
        # the probe (geo3d's index register), R#2 = page 0 in the VDP set-up
        self.gidx(0x40)
        self.gidx(0x49)
        self.ops.append(("FLIP", 0))
        # palette, pages 0-1 cleared, the background: two checkerboard lines
        # doubled by HMMM, the stars; the font masks; the ball images
        self.ops.append(("PAL", 0, zt.pal_bytes(zt.FACE_COLOUR[0])))
        self.pal_act = zt.FACE_COLOUR[0]
        self.hmmv(0, 0, 512, 512, 0)
        bg = rows_bytes(background_rows())
        chk = rows_bytes(((np.mgrid[0:2, 0:512][1] // zt.CHECK_W + np.mgrid[0:2, 0:512][0] // zt.CHECK_H) & 1)
                         .astype(np.uint8))
        self.ops.append(("VW", zt.BG_Y * 256, chk))
        done = 2
        while done < 212:
            n = min(done, 212 - done)
            self.hmmm(0, zt.BG_Y, 0, zt.BG_Y + done, 512, n)
            done *= 2
        full = rows_bytes(np.vstack([np.array([[((x // zt.CHECK_W) + (y // zt.CHECK_H)) & 1 for x in range(512)]
                                               for y in range(212)], np.uint8)]))
        for i in range(len(bg)):
            if bg[i] != full[i]:
                self.ops.append(("VW", zt.BG_Y * 256 + i, bytes([bg[i]])))
        fr = rows_bytes(font_rows())
        self.ops.append(("VW", zt.FONT_Y * 256, fr))
        for pr in range(zt.PR_MIN, zt.PR_MAX + 1):
            for x, y, wd, ht, cx, cy, rows in BALLS[pr]:
                for k, row in enumerate(rows):
                    self.ops.append(("VW", (y + k) * 256 + (x >> 1), rows_bytes([row])))
        # geo3d
        self.gidx(0x6F, [1])                                  # extended mode
        self.gwords(0x18, [zt.FOCAL, zt.CX, zt.CY, zt.ZNEAR, zt.W, zt.H])
        self.gidx(0x64, [0])                                  # TSTRIDE

    # -------------------------------------------------------------- textures
    def bake(self):
        g, L = self.g, zt.LV[self.g.glv]
        lv = L.lv
        for f in range(6):
            for active in (0, 1):
                sx, sy = zt.tex_slot(f, active)
                self.hmmv(sx, sy, 128, 64, C[1] * 17)
                dith = zt.D_ACT if active else zt.D_GREY

                def rect(uc, vc, su, sv, col):
                    x0, x1 = L.tx(uc - su), L.tx(uc + su)
                    y0, y1 = L.ty(vc - sv), L.ty(vc + sv)
                    if x1 > x0 and y1 > y0:
                        self.lmmv(sx + x0, sy + y0, x1 - x0, y1 - y0, col)
                for r in range(lv):
                    for c in range(lv):
                        k = L.ci(f, r, c)
                        col = C[5] if k == g.st else C[3] if k == g.gl else dith
                        rect((2 * c + 1 - lv) * L.HG, (2 * r + 1 - lv) * L.HG, L.HC43, L.HC43, col)
                for r in range(lv):
                    for c in range(lv):
                        gg = g.G[L.ci(f, r, c)]
                        for d in range(4):
                            if d < 2 or (d == 3 and c == 0) or (d == 2 and r == lv - 1):
                                tu = 2 * c + 1 - lv + ((1 if d == 1 else -1) if d & 1 else 0)
                                tv = 2 * r + 1 - lv + (0 if d & 1 else (-1 if d == 0 else 1))
                                if (gg >> d) & 1:
                                    if d & 1:
                                        rect(tu * L.HG, tv * L.HG, L.HP10, L.HP36, dith)
                                    else:
                                        rect(tu * L.HG, tv * L.HG, L.HP36, L.HP10, dith)
                                else:
                                    if d & 1:
                                        rect(tu * L.HG, tv * L.HG, L.WW, L.WL, C[1])
                                    else:
                                        rect(tu * L.HG, tv * L.HG, L.WL, L.WW, C[1])
                if g.gl // (lv * lv) == f:
                    r, c = (g.gl // lv) % lv, g.gl % lv
                    rect((2 * c + 1 - lv) * L.HG, (2 * r + 1 - lv) * L.HG, L.GB, L.GB, C[1])

    # -------------------------------------------------------------- face blocks
    def block(self, f):
        """vertices, faces (4 local indices, BASE), uvs of floor faces, and the
        layer ranges [(name, first face, count)]"""
        g, L = self.g, zt.LV[self.g.glv]
        lv = L.lv
        act = f == g.act
        goal = g.gl // (lv * lv) == f
        verts = []
        for i in range(lv + 1):
            for j in range(lv + 1):
                verts.append(zt.face_point(f, L.KS, (2 * j - lv) * L.HG, (2 * i - lv) * L.HG))
        faces, uvs = [], []
        for r in range(lv):
            for c in range(lv):
                a = r * (lv + 1) + c
                faces.append(((a, a + 1, a + lv + 2, a + lv + 1), 0x81))
                uvs.append([c * L.cw, r * L.ch, (c + 1) * L.cw, r * L.ch,
                            (c + 1) * L.cw, (r + 1) * L.ch, c * L.cw, (r + 1) * L.ch])
        layers = [("floor", 0, lv * lv)]
        vg = None
        if goal:
            r, c = (g.gl // lv) % lv, g.gl % lv
            uc, vc = (2 * c + 1 - lv) * L.HG, (2 * r + 1 - lv) * L.HG
            vg = len(verts)
            verts += rect_quad(f, L.KS + zt.GOAL_H1[g.T42], uc - L.GB, uc + L.GB, vc - L.GB, vc + L.GB)
            verts += rect_quad(f, L.KS + zt.GOAL_H2[g.T42], uc - L.GB, uc + L.GB, vc - L.GB, vc + L.GB)
        runs = face_runs(L, g.G, f)
        vm = len(verts)
        for run in runs:
            verts += rect_quad(f, L.HMID, *run_corners(L, run))
        vt = len(verts)
        for run in runs:
            verts += rect_quad(f, L.HTOP, *run_corners(L, run))
        if goal:
            faces.append(((vg, vg + 1, vg + 2, vg + 3), C[2] if act else C[1]))
            layers.append(("goal1", len(faces) - 1, 1))
        m0 = len(faces)
        for k in range(len(runs)):
            b = vm + 4 * k
            faces.append(((b, b + 1, b + 2, b + 3), C[2] if act else C[1]))
        layers.append(("mid", m0, len(runs)))
        if goal:
            faces.append(((vg + 4, vg + 5, vg + 6, vg + 7), C[6] if g.T & 4 else C[3]))
            layers.append(("goal2", len(faces) - 1, 1))
        t0 = len(faces)
        for k in range(len(runs)):
            b = vt + 4 * k
            faces.append(((b, b + 1, b + 2, b + 3), C[7] if act else C[2]))
        layers.append(("top", t0, len(runs)))
        return dict(verts=verts, faces=faces, uvs=uvs, layers=layers, goal=goal, vg=vg, nruns=len(runs))

    def put_verts(self, base, verts):
        self.g10(0x40, 0x68, base)
        self.gw(0, 0x50)
        for p in verts:
            for c in p:
                self.gw(1, c & 0xFF)
                self.gw(1, (c >> 8) & 0xFF)

    def put_faces(self, fbase, vbase, faces):
        self.g10(0x58, 0x6C, fbase)
        self.gw(0, 0x52)
        for ids, base in faces:
            gi = [vbase + i for i in ids]
            hi = sum(((x >> 8) & 3) << (2 * k) for k, x in enumerate(gi))
            for b in [x & 0xFF for x in gi] + [hi, 0, 0, 0, 0, 0, 0, base]:
                self.gw(1, b)

    def put_uvs(self, fbase, uvs):
        self.g10(0x65, 0x6E, fbase)
        self.gw(0, 0x53)
        for uv in uvs:
            for b in uv:
                self.gw(1, b)

    # -------------------------------------------------------------- a frame
    def matrix_of(self, cam):
        if cam[0] == "spin":
            return list(zt.TITLE[cam[1]])
        if cam[0] == "play":
            _, o, a, k = cam
            return zt.apply_perm(zt.ROLLB[a][k], o)
        _, t, o, a, k = cam
        m = zt.CLEARM[t]
        if k:
            m = zt.mat_mul_q14(m, zt.ROLLR[a][k])
        return zt.apply_perm(m, o)

    def cfg(self):
        return list(self.matrix) + [0, 0, zt.TZ, zt.FOCAL, zt.CX, zt.CY, zt.ZNEAR, zt.W, zt.H]

    def project(self, p):
        self.gwords(0x24, list(p))
        self.ops.append(("GC", tuple(p)))
        return core_model(self.cfg(), p)

    def step(self, inputs):
        """The ticks (2 to 4: the inputs, 6 bits each), then the frame. The
        ROM runs as many ticks as blanks its last picture was shown (at most
        4), which depends on its timing: run_z80.py takes the counts from it."""
        g = self.g
        sfx = []
        for held in inputs:
            g.tick(held)
            sfx += g.sfx
        cam = g.camera
        # the previous frame: shown at its blank, with its palette entry
        if self.flip_pending is not None:
            page, actc = self.flip_pending
            self.ops.append(("FLIP", page))
            if actc != self.pal_act:
                self.ops.append(("PAL", zt.D_ACT, zt.pal_bytes(actc, zt.D_ACT, 1)))
                self.pal_act = actc
        if self.stage_baked != g.stage:
            self.bake()
            self.stage_baked = g.stage
            self.slots = [None, None, None]
        self.draw(cam)
        self.flip_pending = (self.page, zt.FACE_COLOUR[g.act])
        self.frames_meta.append(dict(ph=g.ph, act=g.act, page=self.page, sfx=sfx, T=g.T,
                                     slots=list(self.slots), vis=zt.visible_faces(self.matrix)))
        self.page ^= 1
        self.frame_no += 1

    def draw(self, cam):
        g, L = self.g, zt.LV[self.g.glv]
        lv = L.lv
        ypage = self.page * 256
        self.hmmm(0, zt.BG_Y, 0, ypage, 512, 212)
        self.matrix = self.matrix_of(cam)
        self.gwords(0x00, self.matrix + [0, 0, zt.TZ])
        self.gidx(0x46, [ypage & 0xFF, ypage >> 8])
        vis = zt.visible_faces(self.matrix)
        # slots: keep the resident visible faces, put the others in free slots
        keep = {s[0]: i for i, s in enumerate(self.slots) if s is not None and s[0] in vis}
        free = [i for i in range(3) if i not in keep.values()]
        blocks = {}
        where = {}
        for f in vis:
            blk = self.block(f)
            blocks[f] = blk
            act = f == g.act
            if f in keep:
                i = keep[f]
                if self.slots[i][1] != act:                  # colours of the walls
                    self.put_faces(i * zt.FSLOT + lv * lv, i * zt.VSLOT, blk["faces"][lv * lv:])
                    self.slots[i] = (f, act)
            else:
                i = free.pop(0)
                vb, fb = i * zt.VSLOT, i * zt.FSLOT
                self.put_verts(vb, blk["verts"])
                self.put_faces(fb, vb, blk["faces"])
                self.put_uvs(fb, blk["uvs"])
                self.slots[i] = (f, act)
            where[f] = i
            if blk["goal"]:
                vb, fb = i * zt.VSLOT, i * zt.FSLOT
                self.put_verts(vb + blk["vg"], blk["verts"][blk["vg"]:blk["vg"] + 8])
                gi = [x for x in blk["layers"] if x[0] == "goal2"][0][1]
                self.put_faces(fb + gi, vb, blk["faces"][gi:gi + 1])
        # the ball and its shadow: geo3d projects them now (idle)
        bm, stp, cells = self.ball_point()
        px, py, pz, _ = self.project(bm)
        qx, qy, _, _ = self.project(stp)
        # 1. the floors (LOP = OR, the dithers)
        self.gidx(0x45, [2])
        for f in vis:
            i, blk = where[f], blocks[f]
            tx, ty = zt.tex_slot(f, f == g.act)
            self.g10(0x54, 0x55, i * zt.VSLOT)
            self.g10(0x42, 0x6A, len(blk["verts"]))
            self.gidx(0x60, [tx & 0xFF, tx >> 8, ty & 0xFF, ty >> 8])
            self.g10(0x56, 0x57, i * zt.FSLOT)
            self.g10(0x59, 0x6D, lv * lv)
            self.run()
        # 2. the layers above, LOP = IMP, the projections of step 1
        self.gidx(0x45, [0])
        self.g10(0x42, 0x6A, 0)
        for f in vis:
            i, blk = where[f], blocks[f]
            for name, first, count in blk["layers"][1:]:
                if count:
                    self.g10(0x56, 0x57, i * zt.FSLOT + first)
                    self.g10(0x59, 0x6D, count)
                    self.run()
        # 3. the ball, the walls in front of it painted again
        self.draw_ball(px, py, pz, qx, qy, ypage, vis, cells, bm)
        # 4. the HUD
        self.hud(ypage)

    def ball_point(self):
        g, L = self.g, zt.LV[self.g.glv]
        lv = L.lv

        def cp(ci):
            f, r, c = ci // (lv * lv), (ci // lv) % lv, ci % lv
            return zt.face_point(f, L.HBALL, (2 * c + 1 - lv) * L.HG, (2 * r + 1 - lv) * L.HG)
        if g.mv:
            fr, to, j = g.mv
            p0, p1 = cp(fr), cp(to)
            k = zt.K10[j] if j < zt.J_END else 16384
            bm = tuple(a + (((b - a) * k + 8192) >> 14) for a, b in zip(p0, p1))
            cells = [g.cur, fr]
        else:
            bm = cp(g.cur)
            cells = [g.cur]
        st = tuple(v - (v >> 4) - (v >> 7) for v in bm)            # x 0.9297
        return bm, st, cells

    def draw_ball(self, px, py, pz, qx, qy, ypage, vis, cells, bm):
        g, L = self.g, zt.LV[self.g.glv]
        lv = L.lv
        pr = L.pr_of(pz)
        bi, si = BALLS[pr]
        for (x, y, wd, ht, cx, cy, rows), (ox, oy) in ((si, (qx, qy + 3)), (bi, (px, py))):
            dx, dy = ox - cx, oy - cy
            x0, y0 = max(0, -dx), max(0, -dy)
            x1, y1 = min(wd, zt.W - dx), min(ht, zt.H - dy)
            if x1 > x0 and y1 > y0:
                self.lmmm(x + x0, y + y0, dx + x0, ypage + dy + y0, x1 - x0, y1 - y0, 8)
        # the walls near the ball (2 steps), in front of it by the original's
        # keys; nothing changed since the last frame (camera, ball, maze): the
        # same quads, still in geo3d's scratch RAM, painted again
        sig = (tuple(self.matrix), tuple(bm), tuple(cells), g.stage, g.act)
        if sig == self.occ_sig:
            if self.nocc:
                self.g10(0x54, 0x55, zt.V_SCRATCH)
                self.g10(0x42, 0x6A, 4 * self.nocc)
                self.g10(0x56, 0x57, zt.F_SCRATCH)
                self.g10(0x59, 0x6D, self.nocc)
                self.run()
            return
        self.occ_sig = sig

        def n2(ci):
            """cells at most 2 steps from ci, breadth first"""
            order, fr = [ci], [ci]
            for _ in range(2):
                nf = []
                for c in fr:
                    for d in range(4):
                        n = L.MV[c][d][0]
                        if n not in order:
                            order.append(n)
                            nf.append(n)
                fr = nf
            return order
        near = n2(cells[0])
        if len(cells) > 1:
            near += [x for x in n2(cells[1]) if x not in near]
        zb = pz - 512
        m = self.matrix
        occ = []
        walls_of = {}
        for f in vis:
            for r, c, d, tu, tv in face_walls(L, g.G, f):
                walls_of.setdefault(L.ci(f, r, c), []).append((d, tu, tv))
        for f in vis:
            act = f == g.act
            (i_n, s_n), (i_u, s_u), (i_v, s_v) = zt.FACE_AXES[f]
            # depth of a wall's centre: per face, the terms rounded once (Q2.14)
            mn = s_n * m[6 + i_n]
            U = (s_u * m[6 + i_u] * L.HG + 8192) >> 14
            V = (s_v * m[6 + i_v] * L.HG + 8192) >> 14
            for ci in near:
                if ci // (lv * lv) != f:
                    continue
                for d, tu, tv in walls_of.get(ci, []):
                    for layer, hl, bias, col in (("mid", L.HMID, 307 if act else 614, C[2] if act else C[1]),
                                                 ("top", L.HTOP, -307 if act else 0, C[7] if act else C[2])):
                        zc = zt.TZ + ((mn * hl + 8192) >> 14) + tu * U + tv * V
                        if zc + bias < zb and len(occ) < zt.N_SCRATCH:
                            su, sv = (L.WW, L.WL) if d & 1 else (L.WL, L.WW)
                            u0, v0 = tu * L.HG, tv * L.HG
                            occ.append((rect_quad(f, hl, u0 - su, u0 + su, v0 - sv, v0 + sv), col))
        if occ:
            self.put_verts(zt.V_SCRATCH, [p for q, _ in occ for p in q])
            self.put_faces(zt.F_SCRATCH, zt.V_SCRATCH,
                           [((4 * k, 4 * k + 1, 4 * k + 2, 4 * k + 3), col) for k, (_, col) in enumerate(occ)])
            self.g10(0x54, 0x55, zt.V_SCRATCH)
            self.g10(0x42, 0x6A, 4 * len(occ))
            self.g10(0x56, 0x57, zt.F_SCRATCH)
            self.g10(0x59, 0x6D, len(occ))
            self.run()
        self.nocc = len(occ)

    # -------------------------------------------------------------- HUD
    def bar(self, ypage, y0, y1):
        x0, x1 = zt.hx(0), zt.hx(160)
        a, b = zt.hy(y0), zt.hy(y1)
        self.hmmv(x0, ypage + a, x1 - x0, b - a, 0)
        self.hmmv(x0, ypage + a, x1 - x0, 1, C[1] * 17)
        self.hmmv(x0, ypage + b - 1, x1 - x0, 1, C[1] * 17)

    def text(self, ypage, x, y, s, col):
        X, Y = zt.hx(x), zt.hy(y) + ypage
        self.hmmv(X, Y, zt.ADV * len(s), 14, C[col] * 17)
        for k, ch in enumerate(s):
            gx, gy = glyph_cell(ch)
            self.lmmm(gx, gy, X + zt.ADV * k, Y, zt.ADV, 14, 1)          # AND

    def big_digit(self, ypage, ch, x, y, col):
        for r, c0, c1 in big_digit_runs(ch):
            X0, X1 = zt.hx(x + 4 * c0), zt.hx(x + 4 * c1)
            Y0, Y1 = zt.hy(y + 4 * r), zt.hy(y + 4 * r + 4)
            self.hmmv(X0, ypage + Y0, X1 - X0, Y1 - Y0, col * 17)

    def hud(self, ypage):
        g = self.g
        lx = lambda n: f"{n}x{n}"      # noqa: E731
        tm = f"{g.el // 3600}:{(g.el // 60) % 60:02d}"
        x0, w = zt.hx(0), zt.hx(160) - zt.hx(0)
        if g.ph in (0, 5):
            # the bars, then four text rows (14 lines, the bar's width): each
            # drawn into its cache (ROW_Y) when its key changes, copied every
            # frame (HMMM). The caches share page 0's lines 212-253 with the
            # play bars: a change of mode empties the other mode's caches
            if self.cmode != 1:
                self.cache_rows = [None] * 4
                self.cmode = 1
            self.bar(ypage, 2, 20)
            self.bar(ypage, 104, 142)
            rows = [(7, ("T",), [(32, "CUBE MAZE 3D", 7)])]
            if g.ph == 0:
                labs = []
                for i in range(4):
                    s = i + 3
                    lab = f"{s}x?" if s > g.unl else f"[{lx(s)}]" if s == g.lv else lx(s)
                    labs.append((16 + i * 36 - (s == g.lv) * 8, lab, 1 if s > g.unl else 6 if s == g.lv else 7))
                rows += [(110, (0, g.lv, g.unl), labs),
                         (121, (0, g.best[g.lv - 3]), [(8, f"BEST:{g.best[g.lv - 3]}", 5), (94, "ESC:CODE", 5)]),
                         (131, (0,), [(4, "ARW:SEL SPACE:START", 6)])]
            else:
                rows += [(110, (5, tuple(g.code), g.cpos),
                          [(16, "CODE:", 7)] + [(64 + 8 * k, zt.CODE_ABC[g.code[k]], 6 if k == g.cpos else 7)
                                                for k in range(4)]),
                         (121, (5,), [(8, "ARW:EDIT SPACE:OK", 5)]),
                         (131, (5,), [(8, "ESC:BACK", 6)])]
            for i, (y, key, texts) in enumerate(rows):
                cy = ROW_Y[i]
                if self.cache_rows[i] != key:
                    self.hmmv(x0, cy, w, 14, 0)
                    for x, s, col in texts:
                        self.text(cy - zt.hy(y), x, y, s, col)
                    self.cache_rows[i] = key
                self.hmmm(x0, cy, x0, ypage + zt.hy(y), w, 14)
            return
        if self.cmode != 2:
            self.cache_top = self.cache_bot = None
            self.cmode = 2
        # the top bar: drawn in page 0 lines 212-229 when its texts change,
        # copied every frame (HMMM); the bottom bar likewise at 230-247
        top = (f"{lx(g.lv)} F{g.act + 1}/6 R:{g.rot}", tm)
        if self.cache_top != top:
            self.bar(TOP_DY, 0, 12)
            self.text(TOP_DY, 3, 2, top[0], 7)
            self.text(TOP_DY, 116, 2, tm, 6)
            self.cache_top = top
        self.hmmm(x0, TOP_DY + zt.hy(0), x0, ypage + zt.hy(0), w, zt.hy(12) - zt.hy(0))
        if g.ph < 3:
            if g.ph < 2:
                d = str(g.prv // 60 + 1)
                if d in "123":
                    self.big_digit(ypage, d, 66, 58, 0)
                    self.big_digit(ypage, d, 64, 56, C[7])
            if self.cache_bot != g.ph:
                self.bar(BOT_DY, 132, 144)
                if g.ph < 2:
                    self.text(BOT_DY, 4, 134, "PREVIEW SPACE:START", 6)
                else:
                    self.text(BOT_DY, 8, 134, "ARW:ROLL ESC:RETRY", 5)
                self.cache_bot = g.ph
            self.hmmm(x0, BOT_DY + zt.hy(132), x0, ypage + zt.hy(132), w, zt.hy(144) - zt.hy(132))
        else:
            self.bar(ypage, 29, 113)
            self.text(ypage, 16, 35, "ALL 6x6 CLEARED!" if g.ph == 4 else f"STAGE {lx(g.lv)} CLEAR!", 6)
            self.text(ypage, 16, 47, f"TIME:{tm} ROT:{g.rot}", 7)
            self.text(ypage, 16, 58, f"SCORE:{g.sc}", 5)
            self.text(ypage, 16, 69, f"BEST:{g.best[g.lv - 3]}", 5)
            if g.unl >= 4:
                self.text(ypage, 16, 80, f"CODE:{zt.CODES[g.unl]}", 4)
            nxt = "3x3" if g.ph == 4 else lx(g.lv + 1)
            self.text(ypage, 4, 97, f"SPACE:{nxt} ESC:TITLE", 7)


# ------------------------------------------------------------------ painting the traffic
def paint(ops, want_pages=True):
    """Applies the traffic to the models: geo3d (sim/gen_scenes.py replay) and
    the V9968 in SCREEN 7 (sphere7/vdp6.py, plus LMMV / LMMM here). Returns
    the pages shown, as (212 x 512 indices, palette RGB) per FLIP."""
    from gen_scenes import replay
    import vdp6
    eng = []
    for op in ops:
        if op[0] == "G":
            eng.append(f"W {op[1]} {op[2]:02x}")
        elif op[0] == "RUN":
            eng.append("R")
            eng.append(f"F {op[1]}")
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
    pal = [(0, 0, 0)] * 16
    shown = []
    ncmd = [0]

    def exec_cmd(r):
        op = r[46] >> 4
        if op == 0x9:
            lmmm(vr, r)
        elif op == 0x8:
            lmmv(vr, r)
        else:
            vdp6.apply_regs(vr, r)
        ncmd[0] += 1

    for op in ops:
        k = op[0]
        if k == "VW":
            a, d = op[1], op[2]
            vr.b[a:a + len(d)] = d
        elif k == "CMD":
            first, vals = op[1], op[2]
            for i, v in enumerate(vals):
                regs[first + i] = v
            exec_cmd(regs)
        elif k == "RUN":
            for kd, b in groups.get(op[1], []):
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
                exec_cmd(r)
        elif k == "PAL":
            idx, data = op[1], op[2]
            for j in range(len(data) // 3):
                pal[idx + j] = tuple(round(c * 255 / 31) for c in data[3 * j:3 * j + 3])
        elif k == "FLIP":
            if want_pages:
                pg = np.frombuffer(vr.page(op[1] * 256), np.uint8).reshape(212, 256)
                px = np.empty((212, 512), np.uint8)
                px[:, 0::2] = pg >> 4
                px[:, 1::2] = pg & 15
                shown.append((px, list(pal), ncmd[0]))
            ncmd[0] = 0
    return shown


def lmmm(vr, r):
    import vdp6
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


def lmmv(vr, r):
    import vdp6
    dx, dy = r[36] | (r[37] & 1) << 8, r[38] | (r[39] & 3) << 8
    nx, ny = r[40] | (r[41] & 3) << 8, r[42] | (r[43] & 3) << 8
    ix = -1 if r[45] & 4 else 1
    iy = -1 if r[45] & 8 else 1
    col = r[44] & 15
    for j in range(ny or 1024):
        for i in range(nx or 512):
            c, d = (dx + i * ix) & 511, (dy + j * iy) & 1023
            vr.put(c, d, vdp6.lop(r[46] & 15, col, vr.get(c, d)))


def to_rgb(px, pal):
    p = np.array(pal, np.uint8)
    return np.repeat(np.repeat(p[px], 4, axis=0), 2, axis=1)


# ------------------------------------------------------------------ input scripts
UP, DOWN, LEFT, RIGHT, SPACE, ESC = 1, 2, 4, 8, 16, 32


def tour(g):
    """A prefix for solver_script: the screens the solver never visits. On the
    title a locked size, the code screen (a wrong code, then the code of 5x5),
    sizes, the code screen left with ESC; the preview restarted with ESC; in
    play a few steps in each direction (walls included) and ESC (retry)."""
    def press(m, after=3):
        yield m
        for _ in range(after):
            yield 0

    def idle(n):
        for _ in range(n):
            yield 0
    yield from idle(40)
    yield from press(RIGHT)
    yield from press(ESC, 20)
    yield from press(SPACE, 10)                     # BBBB: wrong
    for k, ch in enumerate(zt.CODES[5]):
        if k:
            yield from press(RIGHT)
        n = zt.CODE_ABC.index(ch)
        key, cnt = (UP, n) if n <= len(zt.CODE_ABC) // 2 else (DOWN, len(zt.CODE_ABC) - n)
        for _ in range(cnt):
            yield from press(key)
    yield from press(SPACE, 20)                     # 5x5 unlocked
    for key in (RIGHT, RIGHT, LEFT):
        yield from press(key, 8)
    yield from press(ESC, 10)
    yield from press(ESC, 10)
    yield from press(LEFT, 10)                      # 3x3
    yield from press(SPACE, 30)                     # preview
    yield from press(ESC, 30)                       # preview again
    yield from press(SPACE, 10)                     # play
    for key in (UP, RIGHT, DOWN, LEFT, LEFT, UP):
        yield from press(key, 30)
    yield from press(ESC)                           # retry


def solver_script(ticks, wait=60, gap=6, title_wait=150, seed_ticks=0, prefix=None):
    """Joypad masks per tick that play the model through every size: wait on
    each screen, walk the shortest path. Uses its own Game to decide.
    prefix: a generator function of the Game (tour) whose masks come first."""
    import collections
    g = Game()
    out, idle, prev = [], 0, 0
    pre = prefix(g) if prefix else None
    for t in range(ticks):
        m = 0
        L = zt.LV[g.lv]
        if pre is not None:
            m = next(pre, None)
            if m is None:
                pre, m, idle = None, 0, 0
                title_wait = seed_ticks = 0
            else:
                g.tick([(m >> i) & 1 for i in range(6)])
                prev = m
                out.append(m)
                continue
        if g.ph == 0 and idle < (title_wait + seed_ticks if t < title_wait + seed_ticks else wait):
            idle += 1
        elif g.ph in (1, 3, 4) and idle < wait:
            idle += 1
        elif g.ph == 2 and (g.mv or g.roll or idle < gap):
            if not g.mv and not g.roll:
                idle += 1
        elif g.ph in (0, 1, 3):
            m = SPACE if not prev & SPACE else 0
        elif g.ph == 4:
            m = ESC if not prev & ESC else 0
        elif g.ph == 2:
            # BFS to the goal
            start, goal = g.cur, g.gl
            back = {start: None}
            q = collections.deque([start])
            while q:
                p = q.popleft()
                if p == goal:
                    break
                for d in range(4):
                    if (g.G[p] >> d) & 1:
                        n = L.MV[p][d][0]
                        if n not in back:
                            back[n] = (p, d)
                            q.append(n)
            k, first = goal, None
            while back[k]:
                p, d = back[k]
                first = d
                k = p
            if first is not None:
                key = next(s for s in range(4) if zt.DIRMAP[g.o][s] == first)
                m = (1 << key) if not prev & (1 << key) else 0
        if m:
            idle = 0
        g.tick([(m >> i) & 1 for i in range(6)])
        prev = m
        out.append(m)
    return out


def run(script, tpf=None):
    """The machine over a script: tpf[k] ticks in frame k (two each when
    tpf is None; the ROM's own counts in run_z80.py)."""
    mc = Machine()
    k = 0
    for n in (tpf if tpf is not None else [2] * (len(script) // 2)):
        if k + n > len(script):
            break
        mc.step([[(script[k + j] >> i) & 1 for i in range(6)] for j in range(n)])
        k += n
    # the last frame drawn is shown at the next blank
    if mc.flip_pending:
        page, actc = mc.flip_pending
        mc.ops.append(("FLIP", page))
        if actc != mc.pal_act:
            mc.ops.append(("PAL", zt.D_ACT, zt.pal_bytes(actc, zt.D_ACT, 1)))
    return mc


if __name__ == "__main__":
    import argparse
    from PIL import Image
    ap = argparse.ArgumentParser()
    ap.add_argument("ticks", type=int)
    ap.add_argument("--png", default="")
    ap.add_argument("--mp4", default="")
    a = ap.parse_args()
    sc = solver_script(a.ticks)
    mc = run(sc)
    shown = paint(mc.ops)
    print(len(shown), "frames; commands max", max(s[2] for s in shown))
    if a.png:
        picks = [int(x) for x in a.png.split(",")]
        row = np.concatenate([np.repeat(np.array(shown[k][1], np.uint8)[shown[k][0]], 2, 0) for k in picks], 1)
        Image.fromarray(row).save("zmodel.png" if a.png and not a.mp4 else a.mp4)
