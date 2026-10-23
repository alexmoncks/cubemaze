#!/usr/bin/env python3
"""Tests of music.asm in the pip `z80` emulator against music.py's reference
timeline (Playload's rules on a 60 Hz grid).

A tiny program (MUS_RAM at C800h, org 4000h, include "music.asm") runs with a
stub BIOS: RDSLT (000Ch) and WRSLT (0014h) are trapped and answered from a
simulated slot map (EXPTBL at FCC1h), clobbering AF/BC/DE like the real ones
and leaving interrupts enabled so the driver's DI after each call is checked.
Every OUT to A0h/A1h (PSG) and 7Ch/7Dh (OPLL) is recorded with its tick and
its time in T-states (and in MSX cycles: T-states + one wait per M1).

    python3 test_music.py            all scenarios, prints the results
    python3 test_music.py --quick    shorter runs
"""
import os
import subprocess
import sys

import z80

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import music  # noqa: E402

BUILD = os.path.join(HERE, 'build')
MUS_RAM = 0xC800
RET_ADDR = 0x0100           # sentinel return address (breakpoint)
STACK = 0xF000
FRAME = 100000              # the emulator's frame_tick wraps here
SLICE = 400                 # < 128 M1 cycles per run, so R cannot wrap unseen


def assemble():
    os.makedirs(BUILD, exist_ok=True)
    music.write_asm()
    src = os.path.join(BUILD, 'test_prog.asm')
    with open(src, 'w') as f:
        f.write(f'MUS_RAM: equ 0{MUS_RAM:X}h\n\torg 4000h\n\tinclude "music.asm"\nmus_prog_end:\n')
    binf = os.path.join(BUILD, 'test_prog.bin')
    r = subprocess.run(['z80asm', '-I', HERE, '-i', src, '-o', binf, '-L'],
                       capture_output=True, text=True, cwd=HERE)  # -L: labels on stderr
    if r.returncode or 'error' in r.stderr:
        raise SystemExit('z80asm failed:\n' + r.stderr)
    labels = {}
    for ln in r.stderr.splitlines():
        if ':' in ln and '$' in ln:
            labels[ln.split(':')[0].strip()] = int(ln.split('$')[1], 16)
    return open(binf, 'rb').read(), labels


class Slots:
    """Simulated slot map. contents[(prim, sub or None)] = {addr: byte}."""

    def __init__(self, expanded, contents):
        self.expanded = expanded            # 4 bools
        self.mem = {k: dict(v) for k, v in contents.items()}
        self.reads, self.writes, self.bad_ids = [], [], []

    def key(self, sid):
        p = sid & 3
        if self.expanded[p]:
            if not sid & 0x80:
                self.bad_ids.append(sid)
            return (p, (sid >> 2) & 3)
        if sid & 0x80:
            self.bad_ids.append(sid)
        return (p, None)

    def read(self, sid, addr):
        self.reads.append((sid, addr))
        k = self.key(sid)
        return self.mem.get(k, {}).get(addr, (addr * 37 + 11) & 0xFF if k == (0, None) else 0xFF)

    def write(self, sid, addr, v):
        self.writes.append((sid, addr, v))
        self.mem.setdefault(self.key(sid), {})[addr] = v


def id_bytes(s):
    return {0x401C + i: ord(c) for i, c in enumerate(s)}


class Machine:
    def __init__(self, rom, labels, slots):
        self.labels, self.slots = labels, slots
        m = self.m = z80.Z80Machine()
        m.set_memory_block(0x4000, rom)
        m.set_memory_block(0xFCC1, bytes(0x80 if e else 0 for e in slots.expanded))
        m.set_memory_block(RET_ADDR, b'\x76')
        for a in (0x000C, 0x0014, RET_ADDR):
            m.set_breakpoint(a)
        m.set_output_callback(self.on_out)
        m.set_input_callback(lambda p: 0xFF)
        self.ft, self.r, self.t, self.m1 = m.frame_tick, m.r & 0x7F, 0, 0
        self.outs = []              # (port, value, T-states, MSX cycles, tick)
        self.tick = -1              # -1 = snd_init
        self.bios_not_di = []

    def now(self):
        m = self.m
        ft = m.frame_tick
        self.t += (ft - self.ft) % FRAME
        self.ft = ft
        r = m.r & 0x7F
        self.m1 += (r - self.r) & 0x7F
        self.r = r
        return self.t, self.t + self.m1

    def on_out(self, port, v):
        t, c = self.now()
        p = port & 0xFF
        if p in (0xA0, 0xA1, 0x7C, 0x7D):
            self.outs.append((p, v, t, c, self.tick))

    def _ret(self):
        m = self.m
        sp = m.sp
        ra = m.memory[sp] | m.memory[sp + 1] << 8
        m.sp = sp + 2
        m.pc = ra
        if m.memory[ra] != 0xF3:            # the driver must DI right after a BIOS call
            self.bios_not_di.append(ra)
        m.iff1 = m.iff2 = 1                 # the BIOS may return with interrupts on

    def call(self, name, a=None):
        """Runs a routine to its RET; returns (T-states, MSX cycles)."""
        m = self.m
        m.sp = STACK
        m.sp -= 2
        m.memory[m.sp] = RET_ADDR & 0xFF
        m.memory[m.sp + 1] = RET_ADDR >> 8
        m.pc = self.labels[name]
        if a is not None:
            m.a = a
        t0 = self.now()
        while True:
            m.ticks_to_stop = SLICE
            m.run()
            self.now()
            pc = m.pc
            if pc == RET_ADDR:
                break
            if pc == 0x000C:                # RDSLT: A = slot, HL = address -> A
                v = self.slots.read(m.a, m.hl)
                m.a = v
                m.bc, m.de, m.f = 0x5A5A, 0xA5A5, 0xFF
                self._ret()
            elif pc == 0x0014:              # WRSLT: A = slot, HL = address, E = value
                self.slots.write(m.a, m.hl, m.e)
                m.a, m.bc, m.d, m.f = 0x33, 0x5A5A, 0xA5, 0xFF
                self._ret()
            elif m.halted:
                raise RuntimeError(f'halted at {pc:04x}')
        t1 = self.now()
        return t1[0] - t0[0], t1[1] - t0[1]


SCENARIOS = {
    # name: (expanded, slot contents, expected FM, expected FM-PAC enable (slot id) or None)
    'none': ([False, False, False, True], {(3, 0): {0x401C: 0x41}, (1, None): id_bytes('PAC2OPL!')}, 0, None),
    'internal-0': ([False, False, False, True], {(0, None): id_bytes('APRLOPLL')}, 1, None),
    'internal-3-3': ([True, False, False, True], {(3, 3): id_bytes('APRLOPLL')}, 1, None),
    'fmpac-1': ([False, False, False, True], {(1, None): {**id_bytes('PAC2OPLL'), 0x7FF6: 0x10}}, 1, 0x01),
    'fmpac-2-1': ([True, False, True, True], {(2, 1): {**id_bytes('PAC2OPLL'), 0x7FF6: 0x00}}, 1, 0x86),
    'fmpac+internal': ([True, False, False, False],
                       {(1, None): {**id_bytes('PAC2OPLL'), 0x7FF6: 0x00}, (0, 2): id_bytes('APRLOPLL')}, 1, None),
}


def run_driver(scenario, n_ticks, sfx_at, rom=None, labels=None):
    if rom is None:
        rom, labels = assemble()
    exp, contents, fm_exp, pac_exp = SCENARIOS[scenario]
    slots = Slots(exp, contents)
    mc = Machine(rom, labels, slots)
    m = mc.m
    before = bytes(m.memory[0x8000:0x10000])
    init_cost = mc.call('snd_init')
    di_after_init = m.iff1 == 0
    costs, regs_bad, sfx_bc_bad, sfx_cost = [], [], 0, (0, 0)
    for t in range(n_ticks):
        mc.tick = t
        if t in sfx_at:
            m.bc = 0x1234
            sfx_cost = mc.call('sfx_play', a=sfx_at[t])
            sfx_bc_bad += m.bc != 0x1234
        m.ix, m.iy = 0x1357, 0x2468
        m.alt_af, m.alt_bc, m.alt_de, m.alt_hl = 0x1111, 0x2222, 0x3333, 0x4444
        costs.append(mc.call('snd_tick'))
        if (m.ix, m.iy, m.alt_af, m.alt_bc, m.alt_de, m.alt_hl) != (0x1357, 0x2468, 0x1111, 0x2222, 0x3333, 0x4444):
            regs_bad.append(t)
    after = bytes(m.memory[0x8000:0x10000])
    stray = [0x8000 + i for i, (x, y) in enumerate(zip(before, after))
             if x != y and not (MUS_RAM <= 0x8000 + i < MUS_RAM + 128) and not (STACK - 0x100 <= 0x8000 + i < STACK)]
    pac_old = None if pac_exp is None else contents[Slots(exp, {}).key(pac_exp)][0x7FF6]
    return dict(mc=mc, slots=slots, costs=costs, pac_old=pac_old, init_cost=init_cost, sfx_cost=sfx_cost, regs_bad=regs_bad, stray=stray, di=di_after_init,
                fm=m.memory[MUS_RAM], fm_exp=fm_exp, pac_exp=pac_exp, sfx_bc_bad=sfx_bc_bad)


# ------------------------------------------------------------------ checks
class Fail(list):
    def check(self, cond, msg):
        if not cond:
            self.append(msg)


def replay(outs, n_ticks):
    """PSG/OPLL register files after snd_init (index -1) and after every tick,
    plus per tick the writes as (chip, reg, value)."""
    psg, opll = [0] * 16, [0] * 64
    pa = oa = None
    per_tick = {t: [] for t in range(-1, n_ticks)}
    snaps = {}
    cur = -1
    for p, v, t, c, tick in outs:
        while cur < tick:
            snaps[cur] = (list(psg), list(opll))
            cur += 1
        if p == 0xA0:
            pa = v
        elif p == 0xA1:
            psg[pa & 15] = v
            per_tick[tick].append(('P', pa, v))
        elif p == 0x7C:
            oa = v
        elif p == 0x7D:
            opll[oa & 63] = v
            per_tick[tick].append(('O', oa, v))
    while cur < n_ticks:
        snaps[cur] = (list(psg), list(opll))
        cur += 1
    return snaps, per_tick


def check_run(res, n_ticks, sfx_at):
    f = Fail()
    mc, fm = res['mc'], res['fm']
    f.check(fm == res['fm_exp'], f'FM flag {fm}, expected {res["fm_exp"]}')
    f.check(res['di'], 'interrupts enabled after snd_init')
    f.check(not mc.bios_not_di, f'no DI after BIOS calls returning to {mc.bios_not_di[:4]}')
    f.check(not res['slots'].bad_ids, f'malformed slot IDs {res["slots"].bad_ids[:4]}')
    f.check(not res['regs_bad'], f'IX/IY/alternate registers changed at ticks {res["regs_bad"][:4]}')
    f.check(not res['stray'], f'RAM written outside MUS_RAM..+127: {[hex(a) for a in res["stray"][:6]]}')
    f.check(res['sfx_bc_bad'] == 0, 'sfx_play changed BC')
    pac = [w for w in res['slots'].writes if w[1] == 0x7FF6]
    if res['pac_exp'] is None:
        f.check(not res['slots'].writes, f'unexpected slot writes {res["slots"].writes}')
    else:
        old = res['pac_old']
        f.check(len(pac) == 1 and pac[0][0] == res['pac_exp'] and pac[0][2] == (old | 1),
                f'FM-PAC enable: writes {pac}, expected 7FF6h = {old | 1:02x} in slot {res["pac_exp"]:02x}')

    outs = mc.outs
    events, states = music.timeline(n_ticks, sfx_at)
    snaps, per_tick = replay(outs, n_ticks)

    # PSG rules
    psg_regs = [w for t in per_tick for w in per_tick[t] if w[0] == 'P']
    f.check(all(r not in (14, 15) for _, r, _ in psg_regs), 'PSG R14/R15 written')
    f.check(all(v & 0xC0 == 0x80 for _, r, v in psg_regs if r == 7), 'PSG R7 bits 7/6 not 1/0')
    f.check(all(r < 14 for _, r, _ in psg_regs), 'PSG register >= 14 written')
    ps0, op0 = snaps[-1]
    f.check(ps0[7] == 0xB8 and ps0[8] == ps0[9] == ps0[10] == 0, f'PSG after init R7={ps0[7]:02x} vols {ps0[8:11]}')
    if not fm:
        f.check(not any(p in (0x7C, 0x7D) for p, *_ in outs), 'OPLL written without MSX-MUSIC')

    note_ticks = {ch: set() for ch in range(3)}
    end_ticks = set()
    for e in events:
        if e[2] == 'note':
            note_ticks[e[1]].add(e[0])
        elif e[2] == 'end':
            end_ticks.add(e[0])
    bgm_ch = (0, 1) if not fm else ()
    # state after every tick
    bad = 0
    for t in range(n_ticks):
        psg, opll = snaps[t]
        st = states[t]
        for ch in range(3):
            s = st[ch]
            if ch in bgm_ch or ch == 2:
                per = psg[2 * ch] | (psg[2 * ch + 1] & 15) << 8
                if s is None:
                    ok = psg[8 + ch] == 0
                else:
                    ok = per == music.psg_period(s[0]) and psg[8 + ch] == s[1]
            else:
                hi, lo, iv = opll[0x20 + ch], opll[0x10 + ch], opll[0x30 + ch]
                if psg[8 + ch]:
                    ok = False
                elif s is None:
                    ok = not hi & 0x10
                else:
                    bl, fn = music.opll_fnum(s[0])
                    ok = (hi & 0x10 and (hi >> 1) & 7 == bl and (lo | (hi & 1) << 8) == fn
                          and hi & 0x20 == 0 and iv == (music.FM_INST[ch] << 4 | music.fm_att(s[1])))
            if not ok:
                bad += 1
                if bad <= 5:
                    f.append(f'tick {t} ch {ch}: state {s}, PSG {psg[:11]}, OPLL 10h+ {opll[0x10 + ch]:02x} '
                             f'20h+ {opll[0x20 + ch]:02x} 30h+ {opll[0x30 + ch]:02x}')
    # writes exactly on the note ticks
    for ch in range(3):
        if ch in bgm_ch or ch == 2:
            wt = {t for t in range(n_ticks) for w in per_tick[t] if w[:2] == ('P', 2 * ch)}
        else:
            wt = {t for t in range(n_ticks) for w in per_tick[t] if w[:2] == ('O', 0x10 + ch)}
            # re-articulation: in each note tick, key off then key on
            for t in sorted(note_ticks[ch]):
                ks = [w[2] & 0x10 for w in per_tick[t] if w[:2] == ('O', 0x20 + ch)]
                if ks[:1] != [0] or ks[-1:] != [0x10]:
                    f.append(f'tick {t} ch {ch}: key writes {ks}, expected off then on')
                    break
        f.check(wt == note_ticks[ch], f'ch {ch}: period writes at ticks {sorted(wt ^ note_ticks[ch])[:6]} '
                                     f'differ from the note starts')
    st_ticks = {t for t in range(n_ticks) for w in per_tick[t] if w == ('P', 10, 0)}
    f.check(st_ticks == end_ticks, f'SFX silence ticks {sorted(st_ticks)} != ends {sorted(end_ticks)}')
    # both loops really wrapped
    for ch, loop_ticks in ((0, 25 * 600), (1, 16 * 600)):
        f.check(any(t * 16 >= 2 * loop_ticks for t in note_ticks[ch]), f'ch {ch}: loop not covered twice')

    # OPLL write timing
    oo = [(p, t, c) for p, v, t, c, tick in outs if p in (0x7C, 0x7D)]
    a2d = [b[1] - a[1] for a, b in zip(oo, oo[1:]) if a[0] == 0x7C and b[0] == 0x7D]
    d2a = [b[1] - a[1] for a, b in zip(oo, oo[1:]) if a[0] == 0x7D and b[0] == 0x7C]
    pairs_ok = all((a[0] == 0x7C) != (b[0] == 0x7C) for a, b in zip(oo, oo[1:])) and (not oo or oo[0][0] == 0x7C)
    f.check(pairs_ok, 'OPLL writes not address/data pairs')
    if oo:
        f.check(min(a2d) >= 12, f'OPLL address->data only {min(a2d)} T-states')
        f.check(min(d2a) >= 84, f'OPLL data->address only {min(d2a)} T-states')
    timing = dict(a2d=min(a2d) if a2d else None, d2a=min(d2a) if d2a else None,
                  a2d_msx=min(b[2] - a[2] for a, b in zip(oo, oo[1:]) if a[0] == 0x7C) if oo else None,
                  d2a_msx=min(b[2] - a[2] for a, b in zip(oo, oo[1:]) if a[0] == 0x7D) if oo else None)
    return f, timing, events


def sfx_schedule(n_ticks):
    s = {0: 1, 100: 0, 113: 3, 260: 2, 262: 2, 600: 3, 601: 0, 900: 1, 1500: 3}
    if n_ticks > 15100:
        s[15000] = 3        # both BGM loops restart here (400 beats): the busiest tick
        s[15040] = 1
    return {k: v for k, v in s.items() if k < n_ticks}


def check_reference(n, sfx_at):
    """The reference timeline itself against closed forms of Playload's rule
    (a note starts at the first tick whose elapsed time reaches the sum of the
    lengths before it): channel 0 note k at ceil(600k / 16), channel 1 at
    150k, SFX notes at call + ceil(sum / 16), silence at call + ceil(total / 16)
    unless another play(2) came first."""
    f = Fail()
    events, _ = music.timeline(n, sfx_at)
    starts = {ch: [e[0] for e in events if e[1] == ch and e[2] == 'note'] for ch in range(3)}
    f.check(starts[0] == [-(-600 * k // 16) for k in range(len(starts[0]))], 'ch 0 note starts')
    f.check(starts[1] == [150 * k for k in range(len(starts[1]))], 'ch 1 note starts')
    f.check(len(starts[0]) == -(-n * 16 // 600) and len(starts[1]) == -(-n * 16 // 2400), 'note counts')
    exp, ends = [], []
    calls = sorted(sfx_at.items())
    for i, (c, k) in enumerate(calls):
        nxt = calls[i + 1][0] if i + 1 < len(calls) else n
        cum = 0
        for op in music.compile_score(music.SFX[k]):
            if op[0] == 'note':
                if c + -(-cum // 16) < nxt:
                    exp.append(c + -(-cum // 16))
                cum += op[2]
        if c + -(-cum // 16) < nxt:
            ends.append(c + -(-cum // 16))
    f.check(starts[2] == exp, f'SFX note starts {starts[2][:8]} != {exp[:8]}')
    f.check([e[0] for e in events if e[2] == 'end'] == ends, 'SFX ends')
    # pitch formulas: A4 = 440 Hz -> PSG period 1789772.5 / (16 * 440) = 254.2; A3 = 220 Hz ->
    # OPLL block 3, F-number 220 * 2^18 / 49716 / 2^2 = 290.0; middle C (O5 c) = MIDI 60
    f.check(music.psg_period(69) == 254 and music.opll_fnum(57) == (3, 290), 'pitch formulas')
    f.check(music.compile_score('O5c')[0][1] == 60 and music.compile_score('O4C')[0][1] == 60, 'octaves')
    return f


def main():
    quick = '--quick' in sys.argv
    n = 2000 if quick else 15200
    rom, labels = assemble()
    size = labels['mus_prog_end'] - 0x4000
    print(f'music.asm + music_data.asm: {size} bytes (code {labels["mus_per"] - 0x4000}, '
          f'tables {labels["mus_prog_end"] - labels["mus_per"]}); RAM used '
          f'{labels["MUS_END"] - labels["MUS_RAM"]} of 128 bytes')
    sfx_at = sfx_schedule(n)
    fr = check_reference(n, sfx_at)
    print('reference timeline vs closed forms:', 'PASS' if not fr else 'FAIL ' + '; '.join(fr))
    ok = not fr
    for name in SCENARIOS:
        res = run_driver(name, n, sfx_at, rom, labels)
        f, timing, events = check_run(res, n, sfx_at)
        cost = [c[0] for c in res['costs']]
        cmsx = [c[1] for c in res['costs']]
        srt = sorted(cost)
        print(f'[{name:14s}] FM={res["fm"]} ticks={n} notes={sum(1 for e in events if e[2] == "note")} '
              f'snd_tick T-states: median {srt[len(srt) // 2]}, mean {sum(cost) / len(cost):.0f}, '
              f'max {max(cost)} (tick {cost.index(max(cost))}); MSX cycles max {max(cmsx)}; '
              f'snd_init {res["init_cost"][0]} T, sfx_play {res["sfx_cost"][0]} T'
              + (f'; OPLL gaps min addr->data {timing["a2d"]} T ({timing["a2d_msx"]} MSX), '
                 f'data->addr {timing["d2a"]} T ({timing["d2a_msx"]} MSX)' if timing['a2d'] else '')
              + ('  PASS' if not f else '  FAIL'))
        for msg in f[:12]:
            print('     ', msg)
        ok &= not f
    print('ALL PASS' if ok else 'FAILURES')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
