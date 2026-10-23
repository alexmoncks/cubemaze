#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Alex Moncks
"""Reference port of the game logic of Cube Maze 3D (harukaappscreate,
JavaScript, ported to MSX with the author's permission).

This is the logic only: the maze generator, the step across the 24 cube
edges, the joypad, the rolls and the score, written to follow the original
line by line so that its frame-by-frame state can be compared with the
original running in node (js_trace.js, check_logic.py). Drawing is not here:
the MSX version draws with geo3d (see build_scene.py).
"""
import json
import math
import sys

I3, I4 = (0, 1, 2), (0, 1, 2, 3)

# 6 cube faces: normal, u axis, v axis, colour (as the original)
F = [
    ((0, 1, 0), (1, 0, 0), (0, 0, 1), 4),
    ((0, -1, 0), (1, 0, 0), (0, 0, -1), 3),
    ((-1, 0, 0), (0, 0, 1), (0, -1, 0), 4),
    ((1, 0, 0), (0, 0, -1), (0, -1, 0), 6),
    ((0, 0, 1), (1, 0, 0), (0, -1, 0), 5),
    ((0, 0, -1), (-1, 0, 0), (0, -1, 0), 6),
]


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def LC(o, x, y, z):
    a, b, c = o[0], o[1], o[2]
    return [a[i] * x + b[i] * y + c[i] * z for i in I3]


def dV(f, d):
    s = -1 if (d - 1) & 2 else 1
    return [x * s for x in F[f][1 if d & 1 else 2]]


def ID(p):
    return p[0] * 64 + p[1] * 8 + p[2]


def jsint(x):
    """JavaScript `x | 0` for the small values used here (truncation)."""
    return int(x)


def mv(p, d, lv):
    """Seamless step on the 6-face grid; returns [f, r, c, d_in]."""
    f, r, c = p[0], p[1], p[2]
    nr = r + (d == 2) - (not d)
    nc = c + (d == 1) - (d == 3)
    if (nr | nc) >= 0 and nr < lv and nc < lv:
        return [f, nr, nc, d]
    h = (lv - 1) / 2
    o = F[f]
    tv = dV(f, d)
    nf = next(i for i, x in enumerate(F) if dot(x[0], tv) > 0)
    p3 = LC(o, h, c - h, r - h)
    return [nf, jsint(dot(p3, F[nf][2]) + h + 0.5), jsint(dot(p3, F[nf][1]) + h + 0.5),
            next(i for i in I4 if dot(dV(nf, i), o[0]) < 0)]


# quaternions [x, y, z, w]
def qN(q):
    n = math.hypot(*q)
    return [v / n for v in q]


def qM(p, q):
    x, y, z, w = p
    a, b, c, d = q
    return [w * a + x * d + y * c - z * b,
            w * b - x * c + y * d + z * a,
            w * c + x * b - y * a + z * d,
            w * d - x * a - y * b - z * c]


def qR(v, q):
    x, y, z, w = q
    return qM(qM([x, y, z, w], [v[0], v[1], v[2], 0]), [-x, -y, -z, w])


def qE(x, y):
    return qM([math.sin(x), 0, 0, math.cos(x)], [0, math.sin(y), 0, math.cos(y)])


K = 1.75
VQ = qE(0.38, -0.34)


def sm(t):
    return t * t * (3 - 2 * t)


class Rng:
    """32-bit xorshift, the same as js_trace.js."""

    def __init__(self, seed):
        self.s = (seed & 0xFFFFFFFF) or 1

    def __call__(self):
        s = self.s
        s ^= (s << 13) & 0xFFFFFFFF
        s ^= s >> 17
        s ^= (s << 5) & 0xFFFFFFFF
        self.s = s
        return s / 4294967296

    def shuffle(self):
        a = [0, 1, 2, 3]
        for i in range(3, 0, -1):
            j = int(self() * (i + 1))
            a[i], a[j] = a[j], a[i]
        return a


class Game:
    def __init__(self, seed=1):
        self.rnd = Rng(seed)
        self.ph, self.lv, self.unl, self.best, self.T = 0, 3, 3, [0, 0, 0, 0], 0
        self.sc, self.rep = 0, 9
        self.rQ = VQ
        self.gen()

    # -------------------------------------------------------------- maze
    def gen(self):
        lv = self.lv
        G = {}
        self.act = self.el = self.rot = 0
        self.mA = self.rA = None
        self.cQ = [0, 0, 0, 1]
        self.prv = 179
        start = [0, lv >> 1, lv >> 1, 0, 0]
        self.cur = self.gl = self.st = start
        sys.setrecursionlimit(5000)

        def cv(p, dp):
            if dp > self.gl[4]:
                self.gl = list(p) + [dp]
            for d in self.rnd.shuffle():
                n = mv(p, d, lv)
                i0, i1 = ID(p), ID(n)
                if not G.get(i1):
                    G[i0] = G.get(i0, 0) | (1 << d)
                    G[i1] = G.get(i1, 0) | (1 << ((n[3] + 2) & 3))
                    cv(n, dp + 1)
        cv(start, 0)
        self.G = G

    def go(self, s):
        self.lv = s
        self.gen()
        self.ph = 1

    # -------------------------------------------------------------- frame
    def tick(self, held, prev):
        btn = lambda i: bool(held[i])                    # noqa: E731
        btnp = lambda i: bool(held[i] and not prev[i])   # noqa: E731
        self.T += 1
        T = self.T
        stp = (btnp(3) - btnp(2)) or (btnp(1) - btnp(0))
        if self.ph < 2:
            r = qE(0.22 + math.sin(T * 0.02) * 0.1, T * 0.01)
        elif self.ph > 2:
            r = qM(qE(0.15, T * 0.01), self.cQ)
        else:
            r = self.cQ
        rQ = qM(VQ, r)
        self.rQ = rQ              # the frame is drawn with the rotation of the tick's start
        ph = self.ph
        if not ph:
            if stp:
                self.lv = min(self.unl, max(3, self.lv + stp))
            if btnp(5):
                self.unl = 6
            if btnp(4):
                self.go(self.lv)
        elif ph == 1:
            self.prv -= 1
            if self.prv <= 0 or btnp(4):
                self.ph = 2
            if btnp(5):
                self.go(self.lv)
        elif ph == 2:
            self.el += 1 / 60
            if btnp(5):
                self.go(self.lv)
                return
            if self.mA:
                self.mA[2] += 0.1
                if self.mA[2] >= 1:
                    self.mA = None
                    if ID(self.cur) == ID(self.gl):
                        lv = self.lv
                        self.sc = max(0, jsint(1e4 - self.el * 10 - self.rot * 50 + 0.5))
                        if self.sc > self.best[lv - 3]:
                            self.best[lv - 3] = self.sc
                        if lv >= self.unl and self.unl < 6:
                            self.unl = lv + 1
                        self.ph = 4 if lv > 5 else 3
            if self.rA:
                a, b = self.rA[0], self.rA[1]
                self.rA[2] += 0.04
                t = sm(self.rA[2])
                self.cQ = qN([v * (1 - t) + b[i] * t for i, v in enumerate(a)])
                if self.rA[2] >= 1:
                    self.rA = None
            if not self.mA and not self.rA:
                sD = None
                for i in I4:
                    if btnp(i):
                        sD = i
                        break
                    if btn(i):
                        self.rep -= 1
                        if self.rep < 0:
                            sD = i
                            break
                if not any(btn(i) for i in I4):
                    self.rep = 9
                if sD is not None:
                    self.rep = 9
                    dr, bD = 0, -9
                    for d in I4:
                        lc = qR(dV(self.act, d), rQ)
                        v = (lc[0] if sD > 1 else -lc[1]) * (1 if sD & 1 else -1)
                        if v > bD:
                            bD, dr = v, d
                    if self.G.get(ID(self.cur), 0) & (1 << dr):
                        nx = mv(self.cur, dr, self.lv)
                        self.mA = [self.cur, nx, 0]
                        if nx[0] != self.cur[0]:
                            self.rot += 1
                            wn = qR(F[nx[0]][0], self.cQ)
                            self.rA = [self.cQ, qM(qN([-wn[2], 0, wn[0], wn[1] + 1]), self.cQ), 0]
                        self.cur = nx
                        self.act = nx[0]
        else:
            if btnp(4):
                self.go(self.lv + 1 if ph == 3 and self.lv < 6 else 3)
            if btnp(5):
                self.ph = 0

    def state(self):
        n = max(self.G) + 1 if self.G else 0
        return {"ph": self.ph, "lv": self.lv, "unl": self.unl, "T": self.T, "cur": self.cur,
                "gl": self.gl, "st": self.st, "act": self.act, "rot": self.rot, "el": self.el,
                "prv": self.prv,
                "mA": [self.mA[0], self.mA[1], self.mA[2]] if self.mA else 0,
                "rA": self.rA[2] if self.rA else 0, "cQ": self.cQ,
                "G": [self.G.get(i, 0) for i in range(n)], "sc": self.sc, "best": self.best}


def random_inputs(seed, frames):
    """The random joypad script of js_trace.js."""
    r2 = (seed * 2654435761) & 0xFFFFFFFF or 7

    def rn():
        nonlocal r2
        r2 ^= (r2 << 13) & 0xFFFFFFFF
        r2 ^= r2 >> 17
        r2 ^= (r2 << 5) & 0xFFFFFFFF
        return r2
    out, cur, left = [], 0, 0
    for _ in range(frames):
        if left <= 0:
            k = rn() % 16
            cur = 1 << k if k < 4 else 16 if k < 6 else (32 * (rn() % 9 == 0)) if k == 6 else 0
            left = 1 + rn() % 24
        else:
            left -= 1
        out.append(cur)
    return out


def run(seed, inputs):
    g = Game(seed)
    prev = [0] * 6
    out = []
    for m in inputs:
        held = [(m >> i) & 1 for i in range(6)]
        g.tick(held, prev)
        prev = held
        out.append(json.loads(json.dumps(g.state())))      # a snapshot, not references
    return out


if __name__ == "__main__":
    seed, frames = int(sys.argv[1]), int(sys.argv[2])
    src = sys.argv[3] if len(sys.argv) > 3 else "random"
    inputs = random_inputs(seed, frames) if src == "random" else json.load(open(src))[:frames]
    for s in run(seed, inputs):
        print(json.dumps(s))
