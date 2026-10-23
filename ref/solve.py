#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Alex Moncks
"""Writes a joypad script that plays Cube Maze 3D through: start, skip the
preview, walk the shortest path to the goal (choosing the arrow key that the
game maps to the wanted direction), next stage, up to 6x6, then the title.
It drives the Python port to decide the keys; the same script then runs on
the original (check_logic.py), so a wrong port shows up as a divergence.
Usage: solve.py <seed> <frames> <out.json> [wait] [step_gap]"""
import collections
import json
import sys

import cubemaze as cm


def path_to_goal(g):
    lv = g.lv
    start, goal = cm.ID(g.cur), cm.ID(g.gl)
    prev = {start: None}
    q = collections.deque([g.cur])
    while q:
        p = q.popleft()
        if cm.ID(p) == goal:
            break
        for d in cm.I4:
            if g.G.get(cm.ID(p), 0) & (1 << d):
                n = cm.mv(p, d, lv)
                if cm.ID(n) not in prev:
                    prev[cm.ID(n)] = (p, d)
                    q.append(n)
    dirs, k = [], goal
    while prev[k]:
        p, d = prev[k]
        dirs.append(d)
        k = cm.ID(p)
    return dirs[::-1]


def key_for(g, want):
    rQ = cm.qM(cm.VQ, g.cQ)
    for sD in cm.I4:
        dr, bD = 0, -9
        for d in cm.I4:
            lc = cm.qR(cm.dV(g.act, d), rQ)
            v = (lc[0] if sD > 1 else -lc[1]) * (1 if sD & 1 else -1)
            if v > bD:
                bD, dr = v, d
        if dr == want:
            return sD
    return None


def script(seed, frames, wait=0, step_gap=0):
    """wait: ticks to stay on each title / preview / clear screen before
    pressing; step_gap: ticks between moves (a player's pace)."""
    g = cm.Game(seed)
    prev = [0] * 6
    script, hold, idle = [], 0, 0
    for _ in range(frames):
        m = 0
        if g.ph != 2 and idle < wait:
            idle += 1
        elif g.ph == 2 and idle < step_gap and not g.mA and not g.rA:
            idle += 1
        elif hold:
            hold -= 1
        elif g.ph in (0, 1) or g.ph in (3, 4):
            m = 16 if not prev[4] else 0
            if g.ph == 4:
                m = 32 if not prev[5] else 0     # back to the title after 6x6
        elif g.ph == 2 and not g.mA and not g.rA:
            path = path_to_goal(g)
            if path:
                k = key_for(g, path[0])
                m = 1 << k if k is not None and not prev[k] else 0
        if m:
            idle = 0
        held = [(m >> i) & 1 for i in range(6)]
        g.tick(held, prev)
        prev = held
        script.append(m)
    return script


def main():
    seed, frames, out = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
    wait = int(sys.argv[4]) if len(sys.argv) > 4 else 0
    gap = int(sys.argv[5]) if len(sys.argv) > 5 else 0
    json.dump(script(seed, frames, wait, gap), open(out, "w"))


if __name__ == "__main__":
    main()
