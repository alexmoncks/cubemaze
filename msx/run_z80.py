#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Alex Moncks
"""Runs CUBEMAZE_xx.ROM in a Z80 emulator (pip package z80) as an MSX would
(ASCII16 banks in page 2, BIOS slot calls stubbed, RAM in page 3, MSX time:
T-states plus the M1 wait, a vertical blank every 59736 cycles), with the
V9968's status registers, geo3d (its registers, and the single-vertex
projections answered with the bit-exact core model) and the keyboard driven
by a joypad script, one entry per game tick.

Every OUT is decoded into the traffic format of zmodel.py; the ROM's traffic
and the model's are painted by the same models (geo3d: sim/gen_scenes.py
replay; V9968 SCREEN 7: sphere7/vdp6.py + LMMV / LMMM) and compared frame
by frame: the pictures shown (indices and palette), geo3d's byte stream, the
VDP commands. Also printed: the Z80's time per frame (MSX cycles).

Usage: run_z80.py [--base 98|88] [--ticks N] [--png F1,F2,..] [--mp4 FILE]
"""
import argparse
import os
import sys

import numpy as np
import z80

HERE = os.path.dirname(os.path.abspath(__file__))
GEO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(GEO, "rom"))
sys.path.insert(0, os.path.join(GEO, "sim"))
from z80clock import MsxClock  # noqa: E402
from gen_vectors import model as core_model  # noqa: E402
import zmodel as zm  # noqa: E402

FRAME_CYC = 59736
BANK = 0x4000


def signed16(x):
    return x - 0x10000 if x & 0x8000 else x


def run_rom(base, script, max_flips, fm=False, verbose=True, timing=None, rom_dir=None, max_ticks=None):
    """timing: None (geo3d and the VDP answer at once) or (run_cyc, cmd_cyc),
    the drawing time of every RUN and of every Z80 command in MSX cycles, in
    order (sys_rtl.py measures them on the RTL): geo3d's status and CE then
    stay busy that long, and the waits cost what they would."""
    P = base
    VDP_DATA, VDP_CTRL, VDP_PAL, VDP_IND, PORT4, GEO_IDX, GEO_DAT = (P + k for k in (0, 1, 2, 3, 4, 5, 7))
    rom_dir = rom_dir or os.path.join(HERE, "out")
    rom = open(os.path.join(rom_dir, f"CUBEMAZE_{P:02X}.ROM"), "rb").read()
    labels = {}
    for ln in open(os.path.join(rom_dir, f"labels_{P:02X}.txt")):
        if ":" in ln and "$" in ln:
            labels[ln.split(":")[0].strip()] = int(ln.split("$")[1], 16)
    m = z80.Z80Machine()
    m.set_memory_block(0x4000, rom[0:BANK])
    m.set_memory_block(0x8000, rom[BANK:2 * BANK])
    stubs = (0x000C, 0x0014, 0x0024, 0x0138, 0x006C, 0x00A2)
    for a in stubs:
        m.set_memory_block(a, b"\xC9")
    m.set_memory_block(0x002D, bytes([2]))          # MSXVER: MSX2+
    m.set_memory_block(0xFCC1, bytes(5))            # EXPTBL: not expanded
    m.pc = rom[2] | rom[3] << 8
    m.sp = 0xF380
    clk = MsxClock(m)
    tick_t = labels["tick_t"]

    st = dict(r15=0, vb=0, gidx=0, rptr=0x30, row=0, text="", flips=0, pend=None, ptr=0, pinc=True,
              r14=0, addr=0, palidx=0, palbuf=[], psg_reg=0, psg15=0, nrun=0, gbusy=False,
              geo_until=0, ce_until=0, ncmd=0, last_busy=None)
    stalls = {}                 # waits for geo3d / CE, by the waiting code's return address
    issues = []
    regs = [0] * 64
    cfg = [0] * 21
    proj = [0, 0, 0, 0]
    lo = [0]
    ops = []
    flip_t = []
    flip_in = []
    snd = []                    # PSG / OPLL writes: (port, value, 0, 0, blank)
    df_ticks = []               # tick_t at each draw_frame: the ticks per frame
    slot_log = []

    def gwrite_dat(v):
        i = st["gidx"]
        ops.append(("G", 1, v))
        if i < 0x2A:
            if i % 2 == 0:
                lo[0] = v
            else:
                w = (v << 8) | lo[0]
                cfg[i >> 1] = signed16(w) if (i >> 1) != 12 else w
                if i == 0x29:
                    c = cfg[0:9] + cfg[9:12] + cfg[12:18]
                    r = core_model(c, (cfg[18], cfg[19], cfg[20]))
                    proj[:] = r
                    st["rptr"] = 0x30
        if i == 0x48 and v & 1:
            st["gbusy"] = True                        # until the Z80 reads the status
            if timing and st["nrun"] < len(timing[0]):
                st["geo_until"] = max(clk.now(), st["ce_until"]) + timing[0][st["nrun"]]
            ops.append(("RUN", st["nrun"]))
            st["nrun"] += 1
        # index advance (the engine's rule)
        if i >> 4 == 4:
            st["gidx"] = 0x40 | ((i + 1) & 0xF)
        elif i >> 2 == 0x15:
            st["gidx"] = 0x54 | ((i + 1) & 3)
        elif i >> 3 == 0x0B:
            st["gidx"] = 0x58 | ((i + 1) & 7)
        elif i >> 3 == 0x0C:
            st["gidx"] = 0x60 | ((i + 1) & 7)
        elif i >> 3 == 0x0D:
            st["gidx"] = 0x68 | ((i + 1) & 7)
        elif i == 0x29:
            st["gidx"] = 0x24
        elif i < 0x40:
            st["gidx"] = i + 1

    def vreg(r, v):
        if st["gbusy"] and (r == 17 or 32 <= r <= 58) and len(issues) < 20:
            issues.append(f"R#{r} written before the Z80 saw geo3d idle (flip {st['flips']})")
        if 32 <= r <= 58:
            ops.append(("VR", r, v))                   # the raw writes (tb_system)
        if r == 17:
            st["ptr"], st["pinc"] = v & 0x3F, not (v & 0x80)
        elif r == 16:
            st["palidx"], st["palbuf"] = v, []
        elif r == 14:
            st["r14"] = v & 0x0F
        elif r == 15:
            st["r15"] = v & 0x0F
        elif r == 2:
            st["flips"] += 1
            if os.environ.get("OCC"):
                n = m.memory[labels["occ_n"]]
                occ = [tuple(m.memory[labels["occ"] + 8 * k + i] for i in range(6)) for k in range(n)]
                nl = [m.memory[labels["nl"] + i] for i in range(m.memory[labels["nl_n"]])]
                fl = [[m.memory[labels["flist"] + 32 * f + i] for i in range(m.memory[labels["flist"] + 32 * f] + 1)] for f in range(6)]
                slot_log.append((occ, nl, fl))
            if os.environ.get("SLOTS"):
                sl = [m.memory[labels["slots"] + i] for i in range(6)]
                vs = [m.memory[labels["vis"] + i] for i in range(m.memory[labels["vis_n"]])]
                slot_log.append((sl, vs))
            flip_t.append(clk.now())
            ops.append(("FLIP", (v >> 5) & 3))
        if 32 <= r <= 46:
            regs[r] = v
            if r == 46:
                ops.append(("CMD", 32, list(regs[32:47])))
                if timing and st["ncmd"] < len(timing[1]):
                    st["ce_until"] = max(clk.now(), st["ce_until"], st["geo_until"]) + timing[1][st["ncmd"]]
                st["ncmd"] += 1
        elif r not in (2, 14, 15, 16, 17):
            ops.append(("REG", r, v))

    def on_out(port, v):
        p = port & 0xFF
        if p == GEO_IDX:
            if st["gbusy"] and len(issues) < 20:
                issues.append(f"geo3d written before the Z80 saw it idle (flip {st['flips']})")
            st["gidx"] = st["rptr"] = v
            ops.append(("G", 0, v))
        elif p == GEO_DAT:
            gwrite_dat(v)
        elif p == VDP_CTRL:
            if st["pend"] is None:
                st["pend"] = v
            else:
                a, st["pend"] = st["pend"], None
                if v & 0x80:
                    vreg(v & 0x3F, a)
                else:
                    st["addr"] = (st["r14"] << 14) | ((v & 0x3F) << 8) | a
        elif p == VDP_DATA:
            ad = st["addr"]
            if ops and ops[-1][0] == "VW" and ops[-1][1] + len(ops[-1][2]) == ad:
                ops[-1][2].append(v)
            else:
                ops.append(("VW", ad, [v]))
            st["addr"] = (ad + 1) & 0x3FFFF
        elif p == VDP_PAL:
            st["palbuf"].append(v & 31)
            if len(st["palbuf"]) == 3:
                ops.append(("PAL", st["palidx"], list(st["palbuf"])))
                st["palidx"] += 1
                st["palbuf"] = []
        elif p == VDP_IND:
            r = st["ptr"]
            if st["pinc"]:
                st["ptr"] = (r + 1) & 0x3F
            vreg(r, v)
        elif p == 0xAA:
            st["row"] = v & 0x0F
        elif p in (0x7C, 0x7D):
            snd.append((p, v, 0, 0, clk.now() // FRAME_CYC))
        elif p == 0xA0:
            snd.append((p, v, 0, 0, clk.now() // FRAME_CYC))
            st["psg_reg"] = v & 15
        elif p == 0xA1:
            snd.append((p, v, 0, 0, clk.now() // FRAME_CYC))
            if st["psg_reg"] == 15:
                st["psg15"] = v

    def keys():
        t = m.memory[tick_t] | m.memory[tick_t + 1] << 8
        return script[t] if t < len(script) else 0

    def stall_note():
        now = clk.now()
        lb = st["last_busy"]
        if lb is not None and now - lb < 400:
            ra = m.memory[m.sp + 4] | m.memory[m.sp + 5] << 8
            stalls[ra] = stalls.get(ra, 0) + now - lb
        st["last_busy"] = now

    def on_in(port):
        p = port & 0xFF
        if p == VDP_CTRL:
            st["pend"] = None
            if st["r15"] == 0:
                fr = clk.now() // FRAME_CYC
                if fr > st["vb"]:
                    st["vb"] = fr
                    return 0x80
                return 0x00
            if st["r15"] == 1:
                return 0x04
            if st["r15"] == 2 and clk.now() < max(st["ce_until"], st["geo_until"]):
                stall_note()
                return 0x01                            # CE = 1
            return 0x00                                # CE = 0
        if p == PORT4:
            return 0x80
        if p == GEO_IDX:
            if clk.now() < st["geo_until"]:
                stall_note()
                return 0x01                            # RUN busy
            st["gbusy"] = False
            return 0x00                                # status: idle
        if p == GEO_DAT:
            r = st["rptr"]
            if 0x30 <= r <= 0x36:
                k = r - 0x30
                v = (proj[k >> 1] >> (8 * (k & 1))) & 0xFF if r < 0x36 else proj[3] & 0xFF
                st["rptr"] = 0x30 if r == 0x36 else r + 1
                return v
            v = 0x20 if r == 0x49 else 0x00
            if r >> 4 == 4:
                st["rptr"] = 0x40 | ((r + 1) & 0xF)
            return v
        if p == 0xA9:
            k = keys()
            row = st["row"]
            v = 0xFF
            if row == 8:
                for bit, mask in ((0, 16), (4, 4), (5, 1), (6, 2), (7, 8)):
                    if k & mask:
                        v &= ~(1 << bit)
            if row == 7 and k & 32:
                v &= ~4
            return v & 0xFF
        if p == 0xA2:
            return st["psg15"] if st["psg_reg"] == 15 else 0xFF
        return 0xFF

    m.set_output_callback(on_out)
    m.set_input_callback(on_in)
    segs = [x for x in os.environ.get("SEG", "").split(",") if x]
    seg_at = {labels[x]: x for x in segs}
    seg_log = []
    for a in stubs + (labels["setbank"], labels["hw_fail"], labels["nogeo"], labels["flip"],
                      labels["draw_frame"]) + tuple(seg_at):
        m.set_breakpoint(a)
    prof = {}
    while st["flips"] < max_flips:
        if os.environ.get("PROF") and st["flips"] >= 3:
            stop = clk.run(97)
            prof[m.pc] = prof.get(m.pc, 0) + 1
        else:
            stop = clk.run(200000)
        if stop:
            pc = m.pc
            if pc == labels["flip"]:
                flip_in.append((st["flips"], clk.now()))
            if pc == labels["draw_frame"]:
                t = m.memory[tick_t] | m.memory[tick_t + 1] << 8
                if max_ticks is not None and t + 4 > max_ticks:
                    break
                df_ticks.append(t)
            if pc in seg_at and st["flips"] >= 3:
                seg_log.append((seg_at[pc], clk.now()))
            if pc in (labels["hw_fail"], labels["nogeo"]):
                st["text"] = f"{'hw_fail' if pc == labels['hw_fail'] else 'nogeo'} (fail={m.memory[labels['fail']]}, " \
                    f"b={m.b}, ticks={m.memory[tick_t]}, flips={st['flips']}, sp={m.sp:04x})"
                stk = [m.memory[m.sp + i] | m.memory[m.sp + i + 1] << 8 for i in range(0, 12, 2)]
                st["text"] += " stack " + " ".join(f"{x:04x}" for x in stk)
                break
            if pc == 0x0138:
                m.a = 0x04
            elif pc == 0x000C:
                # RDSLT: nothing there, but with fm=True internal MSX-MUSIC in
                # slot 0 ("APRLOPLL" at 401Ch)
                a_, hl_ = m.a, m.hl
                m.a = ord("APRLOPLL"[hl_ - 0x401C]) if fm and a_ == 0 and 0x401C <= hl_ < 0x4024 else 0xFF
            elif pc == labels["setbank"]:
                b = m.a
                m.set_memory_block(0x8000, rom[b * BANK:(b + 1) * BANK])
            elif pc == 0x006C:
                st["text"] += "<INITXT>"
            elif pc == 0x00A2:
                st["text"] += chr(m.a)
            if m.halted:
                break
            clk.step_over()
            m.set_memory_block(0x7000, rom[0x3000:0x3001])     # (the bank write hit ROM)
        if st["text"] and m.pc == labels.get("ng_stay"):
            break
    if st["text"]:
        print("BIOS text:", st["text"])
    if seg_log:
        tot = {}
        for (a, t0), (b, t1) in zip(seg_log, seg_log[1:]):
            tot[a] = tot.get(a, 0) + (t1 - t0)
        nfr = max(1, st["flips"] - 3)
        print("segments (MSX cycles per frame):", ", ".join(f"{k} {v // nfr}" for k, v in tot.items()))
    if prof:
        import bisect
        inv = sorted((v, k) for k, v in labels.items() if 0x4000 <= v < 0x8000)
        keys = [v for v, _ in inv]
        agg = {}
        for pc, n in prof.items():
            i = bisect.bisect_right(keys, pc) - 1
            name = inv[i][1] if i >= 0 else hex(pc)
            agg[name] = agg.get(name, 0) + n
        tot = sum(agg.values())
        print("profile:", ", ".join(f"{k} {100 * v / tot:.1f}%" for k, v in sorted(agg.items(), key=lambda kv: -kv[1])[:45]))
    ram = lambda k: m.memory[labels[k]] | m.memory[labels[k] + 1] << 8      # noqa: E731
    info = dict(slot_log=slot_log, late=ram("late"), vbl=ram("vbl"), flips=st["flips"], ticks=ram("tick_t"),
                frame_cyc=[b - a for a, b in zip(flip_t, flip_t[1:])], text=st["text"],
                flip_t=flip_t, flip_in=flip_in, issues=issues,
                tpf=[b - a for a, b in zip([0] + df_ticks, df_ticks)], snd=snd, stalls=stalls, labels=labels,
                fm_flag=m.memory[labels["MUS_FLAG"]] if "MUS_FLAG" in labels else None)
    return ops, info


def canon_cmds(ops):
    """the VDP commands as register snapshots (R#32..R#46) per frame"""
    regs = [0] * 64
    out, cur = [], []
    for op in ops:
        if op[0] == "CMD":
            for i, v in enumerate(op[2]):
                regs[op[1] + i] = v
            cur.append(tuple(regs[32:47]))
        elif op[0] == "FLIP":
            out.append(cur)
            cur = []
    out.append(cur)
    return out


def geo_frames(ops):
    out, cur = [], []
    for op in ops:
        if op[0] == "G":
            cur.append((op[1], op[2]))
        elif op[0] == "FLIP":
            out.append(cur)
            cur = []
    out.append(cur)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="98")
    ap.add_argument("--ticks", type=int, default=400)
    ap.add_argument("--wait", type=int, default=60)
    ap.add_argument("--png", default="")
    ap.add_argument("--mp4", default="")
    ap.add_argument("--tour", action="store_true", help="the code screen, sizes, retries first (zmodel.tour)")
    ap.add_argument("--fm", action="store_true", help="internal MSX-MUSIC in slot 0")
    a = ap.parse_args()
    base = int(a.base, 16)
    script = zm.solver_script(a.ticks, wait=a.wait, prefix=zm.tour if a.tour else None)
    # the ROM first: it decides how many ticks each frame has (2 to 4, from
    # its own timing); the model then runs with the same counts
    ops, info = run_rom(base, script, 10 ** 9, max_ticks=len(script), fm=a.fm)
    mc = zm.run(script, info["tpf"])
    nflip = info["flips"]
    nopll = sum(1 for w in info["snd"] if w[0] == 0x7D)
    print(f"sound: MUS_FLAG {info['fm_flag']} (1: MSX-MUSIC found), {nopll} OPLL writes, "
          f"{sum(1 for w in info['snd'] if w[0] == 0xA1)} PSG writes")
    print("ticks per frame:", dict(sorted(__import__("collections").Counter(info["tpf"]).items())))
    print(f"ROM: {info['flips']} flips, {info['ticks']} ticks, {info['vbl']} blanks, late {info['late']}")
    print("order checks:", "; ".join(info["issues"]) if info["issues"] else
          "geo3d and the command registers are only written after geo3d was seen idle")
    fc = info["frame_cyc"]
    if fc:
        print(f"frame time (MSX cycles, 2 blanks = {2 * FRAME_CYC}): max {max(fc)}, mean {sum(fc) / len(fc):.0f}")
        print("  per frame:", " ".join(str(x // 1000) for x in fc[:400]), "(k)")
    if os.environ.get("OCC"):
        k = int(os.environ["OCC"])
        print("ROM occ at flip", k + 1, info["slot_log"][k + 1])
    if os.environ.get("SLOTS"):
        for k in range(20, 28):
            print(k, "ROM", info["slot_log"][k] if k < len(info["slot_log"]) else None, "model",
                  mc.frames_meta[k - 1]["slots"] if k - 1 < len(mc.frames_meta) else None,
                  mc.frames_meta[k - 1]["vis"] if k - 1 < len(mc.frames_meta) else None)
    if fc:
        byph = {}
        for k, c in enumerate(fc):
            if k + 1 < len(mc.frames_meta):
                ph = mc.frames_meta[k + 1]["ph"]
                byph.setdefault(ph, []).append(c)
        import collections
        h = collections.Counter(round(c / FRAME_CYC) for c in byph.get(2, []))
        print("play frames by blanks:", dict(sorted(h.items())))
        print("frame time by phase:", ", ".join(f"ph{p} n={len(v)} mean {sum(v) // len(v)} max {max(v)}"
                                                for p, v in sorted(byph.items())))
    gz, gm = geo_frames(ops)[:nflip], geo_frames(mc.ops)[:nflip]
    cz, cmm = canon_cmds(ops)[:nflip], canon_cmds(mc.ops)[:nflip]
    bad = None
    for k in range(min(len(gz), len(gm))):
        if gz[k] != gm[k] or cz[k] != cmm[k]:
            bad = k
            break
    if bad is None and (len(gz) != len(gm)):
        bad = min(len(gz), len(gm))
    if bad is not None:
        print(f"traffic differs first in frame {bad}: geo3d {len(gz[bad]) if bad < len(gz) else '-'} vs "
              f"{len(gm[bad]) if bad < len(gm) else '-'} bytes, commands "
              f"{len(cz[bad]) if bad < len(cz) else '-'} vs {len(cmm[bad]) if bad < len(cmm) else '-'}")
        if bad < len(gz) and bad < len(gm):
            nz_, nm_ = len(gz[bad]), len(gm[bad])
            if nz_ != nm_:
                k0 = min(nz_, nm_)
                print("  ROM tail  ", gz[bad][k0 - 4:k0 + 50])
                print("  model tail", gm[bad][k0 - 4:k0 + 50])
            for i, (x, y) in enumerate(zip(gz[bad], gm[bad])):
                if x != y:
                    print(f"  geo3d byte {i}: ROM {x} model {y}; ROM context {gz[bad][max(0, i - 6):i + 6]}")
                    print(f"                   model context {gm[bad][max(0, i - 6):i + 6]}")
                    break
            for i, (x, y) in enumerate(zip(cz[bad], cmm[bad])):
                if x != y:
                    print(f"  command {i}: ROM {x}\n             model {y}")
                    break
    else:
        print(f"traffic identical: {len(gz)} frames of geo3d bytes and VDP commands")
    # the rest of the traffic that changes the pictures: per flip, the VRAM
    # bytes and palette entries written since the last one, and the page shown
    def segs(o, n):
        out, vw, pal = [], {}, {}
        for x in o:
            if x[0] == "VW":
                for i, v in enumerate(x[2]):
                    vw[x[1] + i] = v
            elif x[0] == "PAL":
                for j in range(len(x[2]) // 3):
                    pal[x[1] + j] = tuple(x[2][3 * j:3 * j + 3])
            elif x[0] == "FLIP":
                out.append((x[1], vw, pal))
                vw, pal = {}, {}
                if len(out) >= n:
                    break
        return out
    same_rest = segs(ops, nflip) == segs(mc.ops, nflip)
    print(f"VRAM writes, palette entries, pages shown: {'identical' if same_rest else 'DIFFER'} ({nflip} flips)")
    if (bad is not None and os.environ.get("NOPAINT")) or (bad is None and same_rest and nflip > 1200):
        if bad is None:
            print("(pictures not painted for a run this long: the same traffic paints the same pictures)")
        return
    pz = zm.paint(ops)
    pmod = zm.paint(mc.ops)
    same = sum(1 for x, y in zip(pz, pmod) if np.array_equal(x[0], y[0]) and x[1] == y[1])
    print(f"pictures: {same} of {min(len(pz), len(pmod))} identical (ROM {len(pz)}, model {len(pmod)})")
    if a.png:
        from PIL import Image
        picks = [int(x) for x in a.png.split(",")]
        rows = []
        for k in picks:
            rr = [np.repeat(np.array(s[k][1], np.uint8)[s[k][0]], 2, 0) for s in (pz, pmod) if k < len(s)]
            rows.append(np.concatenate(rr, 1))
        Image.fromarray(np.concatenate(rows, 0)).save(os.path.join(HERE, "out", "rom_vs_model.png"))


if __name__ == "__main__":
    main()
