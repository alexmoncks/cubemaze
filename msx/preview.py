#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Alex Moncks
"""Preview of Cube Maze 3D on MSX: plays a joypad script on the reference
port, builds the golden traffic (traffic.py), paints it with the geo3d v2.0
and SCREEN 7 VDP models (the ball included), adds the HUD (Z80 text), and
writes PNGs or an MP4, optionally next to the original (ref_frames.py).

Usage: preview.py <seed> <ticks> <out> [--wait N] [--gap N] [--png k1,k2,..]
                  [--side]
"""
import argparse
import json
import math
import os
import subprocess
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
REF = os.path.join(os.path.dirname(HERE), "ref")
sys.path.insert(0, HERE)
sys.path.insert(0, REF)

import cubemaze as cm  # noqa: E402
import hud  # noqa: E402
import scene as sc  # noqa: E402
import solve  # noqa: E402
import traffic as tf  # noqa: E402


def ball_sprites(g, img):
    """The original's ball and shadow (ref: tick(), the last list entry),
    positioned with geo3d's projection, drawn as 256-wide sprite pixels."""
    dm = sc.dims(g.lv)
    h, cs, bR = dm["h"], dm["cs"], dm["bR"]

    def cP(c):
        return cm.LC(cm.F[c[0]], cm.K + bR + 0.02, (c[2] - h) * cs, (c[1] - h) * cs)
    k = cm.sm(g.mA[2]) if g.mA else 1
    p0, p1 = cP(g.mA[0] if g.mA else g.cur), cP(g.cur)
    bm = [p0[i] + (p1[i] - p0[i]) * k for i in range(3)]
    pt = tuple(round(c * sc.SU) for c in bm)
    st = tuple(round(c * 0.93 * sc.SU) for c in bm)
    px, py, pz, fl = tf.project(g, g.rQ, pt)
    sx, sy, _, _ = tf.project(g, g.rQ, st)
    d = 2 * pz / sc.SU
    pr = max(3, int(bR * 185 / d))                 # original pixels, as the original
    R = pr * sc.YS

    def span(x0, x1, y, col):
        y = int(round(y))
        if 0 <= y < 212:
            a = max(0, int(x0) & ~1)
            b = min(512, int(x1 + 1) & ~1)
            img[y, a:b] = col
    for yy in range(-int(R), int(R) + 1):
        w = math.sqrt(max(0, R * R - yy * yy)) * 2      # 512-wide pixels
        span(sx - w, sx + w, sy + yy / 2 + 2 * sc.YS, sc.SPR_BLACK)
    for yy in range(-int(R), int(R) + 1):
        w = math.sqrt(max(0, R * R - yy * yy)) * 2
        span(px - w, px + w, py + yy, 2 if yy > R / 2 else 6)
    span(px - 2 * sc.XS / 2, px + sc.XS, py - sc.YS, 7)


def run(seed, ticks, wait, gap):
    script = solve.script(seed, ticks, wait, gap)
    g = cm.Game(seed)
    tr = tf.Traffic()
    res = tf.Resident()
    stats, states = [], []
    prev = [0] * 6
    stage_G = None
    tr.vram(sc.BG_Y * 256, hud.background_bytes())
    tf.ball_setup(tr)
    ypage, nfr = 256, 0
    for t, m in enumerate(script):
        held = [(m >> i) & 1 for i in range(6)]
        g.tick(held, prev)
        prev = held
        if t % 2:
            continue                                    # 30 pictures a second
        if g.G is not stage_G:
            stage_G = g.G
            res.map = {}
            tf.stage_setup(tr, g)
        tf.frame(tr, g, res, ypage, stats)
        snap = cm.Game.__new__(cm.Game)
        snap.__dict__.update({k: (v.copy() if isinstance(v, (list, dict)) else v)
                              for k, v in g.__dict__.items()})
        snap.mA = [list(g.mA[0]), list(g.mA[1]), g.mA[2]] if g.mA else None
        states.append(snap)
        ypage ^= 256
        nfr += 1
    return tr, stats, states


def compose(pages, states):
    out = []
    for px, g in zip(pages, states):
        img = px.copy()
        hud.draw(img, g)
        out.append(img)
    return out


def to_rgb(img, act):
    pal = np.array(sc.palette(act), np.uint8)
    rgb = pal[img]
    # 512 x 212 G6 pixels on a 4:3 screen: show as 1024 x 848 (2 x 4)
    return np.repeat(np.repeat(rgb, 4, axis=0), 2, axis=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("seed", type=int)
    ap.add_argument("ticks", type=int)
    ap.add_argument("out")
    ap.add_argument("--wait", type=int, default=90)
    ap.add_argument("--gap", type=int, default=8)
    ap.add_argument("--png", default="")
    ap.add_argument("--side", action="store_true")
    a = ap.parse_args()
    tr, stats, states = run(a.seed, a.ticks, a.wait, a.gap)
    pages, cmds = tf.system(tr, None)
    imgs = compose(pages, states)
    mx = {k: max(s[k] for s in stats) for k in stats[0]}
    print(f"{len(imgs)} quadros; máximo por quadro: {mx}; comandos do VDP até {max(cmds)}")
    if a.png:
        picks = [int(x) for x in a.png.split(",")]
        row = np.concatenate([np.repeat(np.array(sc.palette(states[k].act), np.uint8)[imgs[k]], 2, 0)
                              for k in picks], axis=1)
        Image.fromarray(row).save(a.out)
        return
    ref = None
    if a.side:
        import ref_frames
        ref = ref_frames.frames(a.seed, solve.script(a.seed, a.ticks, a.wait, a.gap))[::2]
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{1024 + (944 if ref is not None else 0)}x848", "-r", "30", "-i", "-",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-movflags", "+faststart", a.out]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for k, im in enumerate(imgs):
        fr = to_rgb(im, states[k].act)
        if ref is not None:
            r = ref_frames.to_rgb(ref[min(k, len(ref) - 1)])        # 160 x 144 -> 944 x 848
            fr = np.concatenate([np.array(Image.fromarray(r).resize((944, 848), Image.NEAREST)), fr], axis=1)
        p.stdin.write(fr.tobytes())
    p.stdin.close()
    p.wait()


if __name__ == "__main__":
    main()
