#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Alex Moncks
"""A video of the ROM: run_z80.py's emulator plays it with a joypad script,
the pictures it shows are painted from its own traffic (zmodel.paint: the
geo3d model and the SCREEN 7 command model) and kept on screen from the blank
of their flip to the next one; the sound is rendered from the PSG / OPLL
writes the ROM made (music/preview.py's renderers).

The pacing is the emulator's: the Z80's own time, with geo3d and the VDP
answering at once. On hardware the drawing adds to it (sys_rtl.py estimates
how much); the game's speed is the same either way (the ROM runs more ticks
per picture when its pictures are slower).

Usage: make_video.py [--ticks N] [--tour] [--fm] [--out FILE.mp4]
"""
import argparse
import os
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "music"))
import zmodel as zm  # noqa: E402
import run_z80  # noqa: E402

FRAME_CYC = 59736


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticks", type=int, default=2400)
    ap.add_argument("--wait", type=int, default=40)
    ap.add_argument("--tour", action="store_true")
    ap.add_argument("--fm", action="store_true")
    ap.add_argument("--base", default="98")
    ap.add_argument("--out", default=os.path.join(HERE, "out", "cubemaze_rom.mp4"))
    a = ap.parse_args()
    script = zm.solver_script(a.ticks, wait=a.wait, prefix=zm.tour if a.tour else None)
    ops, info = run_z80.run_rom(int(a.base, 16), script, 10 ** 9, max_ticks=len(script), fm=a.fm)
    shown = zm.paint(ops)
    blanks = [t // FRAME_CYC for t in info["flip_t"]][:len(shown)]
    n_bl = blanks[-1] + 2
    print(f"{len(shown)} pictures over {n_bl} blanks ({n_bl / 60:.1f} s), {len(script)} ticks")

    # video: 60 frames a second, 512 x 424 (each line twice), then x2
    tmp_v = a.out + ".video.mp4"
    W, H = 1024, 848
    ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                           "-s", f"{W}x{H}", "-r", "60", "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                           "-crf", "18", tmp_v], stdin=subprocess.PIPE)
    black = np.zeros((H, W, 3), np.uint8).tobytes()
    k = -1
    cur = black
    for b in range(n_bl):
        while k + 1 < len(blanks) and blanks[k + 1] <= b:
            k += 1
            px, pal = shown[k][0], shown[k][1]
            rgb = np.array(pal, np.uint8)[px]                      # 212 x 512
            rgb = np.repeat(np.repeat(rgb, 4, axis=0), 2, axis=1)  # 848 x 1024
            cur = rgb.tobytes()
        ff.stdin.write(cur)
    ff.stdin.close()
    ff.wait()

    # sound: the PSG / OPLL state per blank (music/test_music.replay)
    import test_music as T
    import preview as P
    snaps, per_tick = T.replay(info["snd"], n_bl)
    P.TICKS = n_bl
    audio = P.render_psg(snaps, channels=(0, 1, 2) if not a.fm else (2,))
    if a.fm:
        audio = audio + P.render_fm(per_tick, snaps)
    wav = a.out + ".wav"
    P.write_wav(wav, audio)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", tmp_v, "-i", wav, "-c:v", "copy", "-c:a", "aac",
                    "-b:a", "160k", "-shortest", a.out], check=True)
    os.remove(tmp_v)
    os.remove(wav)
    print("written", a.out)


if __name__ == "__main__":
    main()
