#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Alex Moncks
"""The ROM's traffic on the RTL: geo3d_bus (rtl/) driving HRA!'s V9968 command
engine (vdp_command.v, vdp_command_cache.v, unmodified) in SCREEN 7, through
sim/tb_system_cm.v (a copy of sphere7/sim/tb_system_g6.v that logs every wait).

  1. run_z80.py's emulator runs the ROM with the solver script (as run_z80.py)
  2. its OUTs become the testbench stimulus: geo3d port writes, the Z80's own
     command-register writes, the VRAM uploads, a page dump at every flip
  3. the pages the RTL shows are compared with the model's (zmodel.paint)
  4. the frame times: the Z80's own work per frame (emulator, MSX cycles,
     with geo3d and the VDP answering at once) and the drawing time the RTL
     needs per frame (geo3d busy + CE up, with the VRAM always ready). Real
     hardware lies between max(work, draw) and work + draw (the occluder
     search runs while geo3d draws the first floor; the rest waits).

Usage: sys_rtl.py [--ticks N] [--wait N] [--frames N] [--base 98|88]
"""
import argparse
import collections
import os
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
GEO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import zmodel as zm  # noqa: E402
import run_z80  # noqa: E402

FRAME_CYC = 59736           # MSX cycles per vertical blank (60 Hz)
MSX_HZ = 3579545


def stimulus(ops, nflip, skip=0):
    """ROM ops -> (tb_system lines up to the nflip-th flip, events). Before
    flip `skip` nothing is drawn into the two pictures (no RUN, no Z80
    command whose DY is in page 0 / 1's 212 lines) and no page is dumped:
    the VRAM the later frames need (textures, caches, background) is still
    built, and each frame redraws its page whole. events: per RUN and per Z80
    command, in order, whether a wait line (R / C) measured it."""
    out, ev, busy, nf = [], [], False, 0
    regs = [0] * 64
    for op in ops:
        k = op[0]
        live = nf >= skip
        if k == "G":
            if busy:
                out.append("R")
                busy = False
            out.append(f"W {op[1]} {op[2]:02x}")
        elif k == "RUN":
            if live:
                busy = True
            else:
                out.pop()                       # (the write that starts it)
            ev.append(("run", live))
        elif k == "VR":
            if busy:
                out.append("R")
                busy = False
            regs[op[1]] = op[2]
            if op[1] == 46:
                dy = regs[38] | (regs[39] & 3) << 8
                draw = live or not (dy < 212 or 256 <= dy < 468)
                if draw:
                    out += [f"V 46 {op[2]:02x}", "C"]
                ev.append(("cmd", draw))
            else:
                out.append(f"V {op[1]} {op[2]:02x}")
        elif k == "VW":
            a, d = op[1], op[2]
            out += [f"X {(a + i) & 0x3FFFF:05x} {v:02x}" for i, v in enumerate(d)]
        elif k == "FLIP":
            if busy:
                out.append("R")
                busy = False
            out += ["C", f"D {op[1] * 256}" if live else "N"]
            nf += 1
            if nf >= nflip:
                break
    return out, ev


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="98")
    ap.add_argument("--ticks", type=int, default=1400)
    ap.add_argument("--wait", type=int, default=40)
    ap.add_argument("--frames", type=int, default=60)
    ap.add_argument("--skip", type=int, default=0, help="frames before this flip are not drawn (see stimulus)")
    ap.add_argument("--reuse", action="store_true", help="the last RTL run's files (no new run)")
    ap.add_argument("--dir", default="sys")
    ap.add_argument("--rom-dir", default=None, help="the ROM and its labels (default out/)")
    ap.add_argument("--tour", action="store_true")
    a = ap.parse_args()
    base = int(a.base, 16)
    script = zm.solver_script(a.ticks, wait=a.wait, prefix=zm.tour if a.tour else None)
    rd = os.path.join(HERE, a.rom_dir) if a.rom_dir else None
    ops, info = run_z80.run_rom(base, script, a.frames, rom_dir=rd, max_ticks=len(script))
    mc = zm.run(script, info["tpf"])
    nflip = min(a.frames, info["flips"])
    out_dir = os.path.join(HERE, "out", a.dir)
    os.makedirs(out_dir, exist_ok=True)
    stim, ev = stimulus(ops, nflip, a.skip)
    if not a.reuse:
        open(os.path.join(out_dir, "sys_stim.txt"), "w").write("\n".join(stim) + "\n")
    shown = zm.paint(ops)[:nflip]
    hra = os.path.join(GEO, "..", "fpga", "V9968_Cartridge_TangNano20K", "src", "v9968")
    srcs = [os.path.join(HERE, "sim", "tb_system_cm.v")] + \
        [os.path.join(GEO, "rtl", f) for f in ("geo3d_bus.v", "geo3d_engine.v", "geo3d_core.v")] + \
        [os.path.join(hra, f) for f in ("vdp_command.v", "vdp_command_cache.v")]
    vvp = os.path.join(out_dir, "tbsys.vvp")
    got_f, tim_f = os.path.join(out_dir, "sys_got.hex"), os.path.join(out_dir, "sys_times.txt")
    if not a.reuse:
        if not os.path.exists(vvp) or any(os.path.getmtime(s) > os.path.getmtime(vvp) for s in srcs):
            subprocess.run(["iverilog", "-g2012", "-o", vvp] + srcs, check=True)
        r = subprocess.run(["vvp", "-n", vvp, "+stim=sys_stim.txt", "+frames=sys_got.hex", "+times=sys_times.txt"],
                           capture_output=True, text=True, cwd=out_dir)     # (the testbench's names: 80 chars)
        print("\n".join(x for x in r.stdout.splitlines() if x.startswith("System")) or r.stdout[-600:] + r.stderr[-600:])

    # pages: RTL vs model
    got = np.array([int(x, 16) for x in open(got_f).read().split()], np.uint8)
    pages = len(got) // (212 * 256)
    bad = []
    for k in range(pages):
        px = shown[a.skip + k][0]
        exp = (px[:, 0::2] << 4 | px[:, 1::2]).astype(np.uint8).ravel()
        if not np.array_equal(got[k * 54272:(k + 1) * 54272], exp):
            bad.append(a.skip + k)
    print(f"RTL (geo3d_bus + HRA!'s vdp_command.v, SCREEN 7): {pages - len(bad)} of {pages} pages identical "
          f"to the model" + (f"; differ: {bad[:12]}" if bad else ""))

    # times
    draw, cur = [], 0
    for ln in open(tim_f):
        p = ln.split()
        if p[0] in ("R", "C"):
            cur += int(p[1])
        elif p[0] == "D":
            draw.append(cur * 1e-9 * MSX_HZ)       # ns -> MSX cycles
            cur = 0
    # work[k]: the Z80's cycles for the frame shown at flip k (from the flip
    # before it to its flip call; the waits for geo3d / CE are instant here)
    ft, fin = info["flip_t"], dict(info["flip_in"])
    work = [None] + [fin[k] - ft[k - 1] if k in fin else None for k in range(1, len(ft))]
    rows = []
    for i, d_ in enumerate(draw):
        k = a.skip + i                              # the flip (0-based)
        if k < 1 or k >= len(work) or work[k] is None or k >= len(mc.frames_meta):
            continue
        rows.append((mc.frames_meta[k]["ph"], work[k], d_))
    for ph in sorted(set(r_[0] for r_ in rows)):
        sel = [r_ for r_ in rows if r_[0] == ph]
        w = np.array([r_[1] for r_ in sel])
        d = np.array([r_[2] for r_ in sel])
        lo = np.maximum(w, d)
        hi = w + d
        bl = lambda x: dict(sorted(collections.Counter(np.maximum(2, np.ceil(x / FRAME_CYC)).astype(int).tolist()).items()))  # noqa: E731
        print(f"phase {ph}: {len(sel)} frames; Z80 work mean {w.mean():.0f} max {w.max():.0f}; "
              f"RTL draw mean {d.mean():.0f} max {d.max():.0f} (MSX cycles)")
        print(f"   blanks per frame, best case {bl(lo)}, worst case {bl(hi)}")

    # the ROM again, geo3d and CE busy as long as the RTL needed: the frame
    # times with the real overlap of the Z80's work and the drawing
    # the wait lines in the stimulus, in order: R (a RUN), C after V 46 (a
    # command) or before D / N (a flip); their times in the same order
    kinds, prev = [], ""
    for ln in stim:
        if ln[:1] == "R":
            kinds.append("run")
        elif ln[:1] == "C":
            kinds.append("cmd" if prev.startswith("V 46") else "flip")
        if ln.strip():
            prev = ln
    tl = [int(ln.split()[1]) * 1e-9 * MSX_HZ for ln in open(tim_f) if ln[:1] in ("R", "C")]
    meas = {"run": [], "cmd": []}
    for kd, t in zip(kinds, tl):
        if kd in meas:
            meas[kd].append(t)
    its = {kd: iter(v) for kd, v in meas.items()}
    run_cyc, cmd_cyc = [], []
    for kd, measured in ev:
        t = next(its[kd], None) if measured else 0
        if t is None:
            break
        (run_cyc if kd == "run" else cmd_cyc).append(t)
    covered = len(draw) + a.skip
    ops2, info2 = run_z80.run_rom(base, script, covered, timing=(run_cyc, cmd_cyc), rom_dir=rd,
                                  max_ticks=len(script))
    ft2 = info2["flip_t"]
    same = run_z80.geo_frames(ops2)[:covered] == run_z80.geo_frames(ops)[:covered]
    # (with fewer pictures the ROM runs more ticks per frame: the traffic then
    # changes, and the k-th RUN / command of this run is only close to the
    # k-th measured one: the times are an estimate)
    print(f"with the RTL's drawing times ({len(run_cyc)} RUNs, {len(cmd_cyc)} Z80 commands): "
          f"traffic {'unchanged' if same else 'changed (more ticks per frame)'}; "
          + ("; ".join(info2["issues"]) or "order checks pass")
          + f"; ticks per frame {dict(sorted(collections.Counter(info2['tpf']).items()))}")
    mc = zm.run(script, info2["tpf"])
    import bisect
    lab = info2["labels"]
    inv = sorted((v, k) for k, v in lab.items() if 0x4000 <= v < 0x8000)
    keys = [v for v, _ in inv]
    agg = {}
    for ra, c in info2["stalls"].items():
        i = bisect.bisect_right(keys, ra) - 1
        agg[inv[i][1] if i >= 0 else hex(ra)] = agg.get(inv[i][1] if i >= 0 else hex(ra), 0) + c
    nfr = max(1, len(ft2) - a.skip)
    print("   waits per frame (MSX cycles, by the caller of the wait):",
          ", ".join(f"{k} {v // nfr}" for k, v in sorted(agg.items(), key=lambda kv: -kv[1])[:14]))
    byph = {}
    for k in range(max(1, a.skip + 1), len(ft2)):
        if k < len(mc.frames_meta):
            byph.setdefault(mc.frames_meta[k]["ph"], []).append(round((ft2[k] - ft2[k - 1]) / FRAME_CYC))
    names = {0: "title", 1: "preview", 2: "play", 3: "clear", 4: "all clear", 5: "code"}
    for ph, v in sorted(byph.items()):
        print(f"   {names.get(ph, ph)}: {len(v)} frames, blanks per frame {dict(sorted(collections.Counter(v).items()))}, "
              f"{60 * len(v) / sum(v):.1f} fps")


if __name__ == "__main__":
    main()
