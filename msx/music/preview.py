#!/usr/bin/env python3
"""Audio previews of the Z80 driver's output: runs music.asm in the z80
emulator (test_music.py's harness) for 40 s with the four SFX at a few
moments, records every PSG / OPLL write and renders them:

  preview_psg.wav  no MSX-MUSIC: PSG A/B (BGM) + C (SFX); square waves with
                   the AY volume table Playload uses (Westcott's measurements)
  preview_fm.wav   MSX-MUSIC: OPLL channels 0/1 (BGM) through a simplified
                   YM2413 model + PSG C (SFX). An approximation of the chip:
                   2-operator FM with the built-in patch parameters, a linear-
                   in-dB envelope, no KSL, no AM/vibrato LFO, no DAC quirks.

    python3 preview.py
"""
import os
import sys
import wave

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import test_music as T  # noqa: E402

SR = 44100
SECONDS = 40
TICKS = SECONDS * 60
SPT = SR // 60                       # 735 samples per tick
SFX_AT = {240: 1, 600: 0, 615: 0, 1020: 2, 1500: 3, 1980: 1, 2160: 3}
PSG_CLOCK = 1789772.5
OPLL_FS = 3579545 / 72

# AY levels (Matthew Westcott's measurements, as in Playload's sound.js), 0..1
_V = [1.147, 1.162, 1.169, 1.178, 1.192, 1.213, 1.238, 1.299, 1.336, 1.457, 1.573, 1.707, 1.882,
      2.06, 2.32, 2.58]
AY_LEVEL = [(v - _V[0]) / (_V[15] - _V[0]) for v in _V]

# YM2413 built-in instruments 1..15 (8 bytes each, the layout of registers 00h-07h),
# as in the widely used dump (emu2413's 2413 tone table)
YM2413_PATCHES = {
    1: (0x71, 0x61, 0x1E, 0x17, 0xD0, 0x78, 0x00, 0x17),   # Violin
    2: (0x13, 0x41, 0x1A, 0x0D, 0xD8, 0xF7, 0x23, 0x13),   # Guitar
    3: (0x13, 0x01, 0x99, 0x00, 0xF2, 0xC4, 0x21, 0x23),   # Piano
    4: (0x11, 0x61, 0x0E, 0x07, 0x8D, 0x64, 0x70, 0x27),   # Flute
    5: (0x32, 0x21, 0x1E, 0x06, 0xE1, 0x76, 0x01, 0x28),   # Clarinet
    6: (0x31, 0x22, 0x16, 0x05, 0xE0, 0x71, 0x00, 0x18),   # Oboe
    7: (0x21, 0x61, 0x1D, 0x07, 0x82, 0x81, 0x11, 0x07),   # Trumpet
    8: (0x33, 0x21, 0x2D, 0x13, 0xB0, 0x70, 0x00, 0x07),   # Organ
    9: (0x61, 0x61, 0x1B, 0x06, 0x64, 0x65, 0x10, 0x17),   # Horn
    10: (0x41, 0x61, 0x0B, 0x18, 0x85, 0xF0, 0x81, 0x07),  # Synthesizer
    11: (0x33, 0x01, 0x83, 0x11, 0xEA, 0xEF, 0x10, 0x04),  # Harpsichord
    12: (0x17, 0xC1, 0x24, 0x07, 0xF8, 0xF8, 0x22, 0x12),  # Vibraphone
    13: (0x61, 0x50, 0x0C, 0x05, 0xD2, 0xF5, 0x40, 0x42),  # Synthesizer Bass
    14: (0x01, 0x01, 0x55, 0x03, 0xE9, 0x90, 0x03, 0x02),  # Acoustic Bass
    15: (0x41, 0x41, 0x89, 0x03, 0xF1, 0xE4, 0xC0, 0x13),  # Electric Guitar
}
MULT = [0.5, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 10, 12, 12, 15, 15]


def record(scenario):
    res = T.run_driver(scenario, TICKS, SFX_AT)
    snaps, per_tick = T.replay(res['mc'].outs, TICKS)
    return res, snaps, per_tick


def write_wav(path, x):
    x = x / max(1e-9, np.max(np.abs(x))) * 0.8
    pcm = (np.clip(x, -1, 1) * 32767).astype('<i2')
    with wave.open(path, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


# ------------------------------------------------------------------ PSG
def render_psg(snaps, channels=(0, 1, 2), over=8):
    """Square waves, 8x oversampled and box-filtered; the PSG state of each
    tick held for its 1/60 s (writes land at the start of the tick)."""
    out = np.zeros(TICKS * SPT)
    for ch in channels:
        phase = 0.0
        for t in range(TICKS):
            psg = snaps[t][0]
            per = (psg[2 * ch] | (psg[2 * ch + 1] & 15) << 8) or 1
            amp = AY_LEVEL[psg[8 + ch] & 15]
            if amp == 0:
                continue
            inc = PSG_CLOCK / (16 * per) / (SR * over)
            ph = phase + inc * np.arange(1, SPT * over + 1)
            sq = np.where((ph % 1.0) < 0.5, 1.0, -1.0) * amp
            out[t * SPT:(t + 1) * SPT] += sq.reshape(SPT, over).mean(axis=1)
            phase = ph[-1] % 1.0
    return out * 0.25


# ------------------------------------------------------------------ OPLL (approximation)
def t96(rate):
    """Seconds for 96 dB of decay at effective rate RK (OPL-style table)."""
    return 39.28 * 2 ** (-(rate - 4) / 4)


def ta(rate):
    """Seconds for a full attack at effective rate RK (OPL-style table)."""
    return 2.826 * 2 ** (-(rate - 4) / 4)


class Op:
    def __init__(self, b_mode, tl, ksl_fb, ad, sr):
        self.am, self.vib = b_mode >> 7 & 1, b_mode >> 6 & 1
        self.egt, self.ksr, self.mult = b_mode >> 5 & 1, b_mode >> 4 & 1, MULT[b_mode & 15]
        self.tl = tl
        self.ar, self.dr = ad >> 4, ad & 15
        self.sl, self.rr = sr >> 4, sr & 15
        self.att, self.state = 48.0, 'off'

    def rate(self, r, rks):
        return 0 if r == 0 else min(63, 4 * r + rks)


class FmChannel:
    """One OPLL channel: modulator with feedback, carrier, envelopes in dB
    (0 = loudest, 48 = silent), updated at a control rate of SR/32."""
    CR = 32

    def __init__(self, inst):
        p = YM2413_PATCHES[inst]
        self.mod = Op(p[0], (p[2] & 63) * 0.75, p[2] >> 6, p[4], p[6])
        self.car = Op(p[1], 0.0, p[3] >> 6, p[5], p[7])
        self.fb = p[3] & 7
        self.half_m, self.half_c = p[3] >> 3 & 1, p[3] >> 4 & 1
        self.pm = self.pc = 0.0
        self.y1 = self.y0 = 0.0
        self.table = self._fb_table()

    def _fb_table(self, levels=65, n=1024):
        """Steady-state wave of the self-modulating modulator per output level
        (0.75 dB steps): one cycle at n phase steps."""
        tab = np.zeros((levels, n))
        ph = np.arange(n) / n
        for k in range(levels):
            a = 10 ** (-0.75 * k / 20)
            y = np.zeros(n * 3)
            y1 = y0 = 0.0
            for i in range(n * 3):
                off = (y1 + y0) * 2 ** (self.fb - 7) if self.fb else 0.0
                s = np.sin(2 * np.pi * (ph[i % n] + off))
                if self.half_m and s < 0:
                    s = 0.0
                y1, y0 = y0, a * s
                y[i] = y0
            tab[k] = y[2 * n:]
        return tab

    def eg_step(self, op, key, dt, rks):
        if op.state == 'damp':
            op.att += 48 / (t96(op.rate(12, 0)) / 2) * dt
            if op.att >= 48:
                op.att, op.state = 48.0, 'attack'
        elif op.state == 'attack':
            r = op.rate(op.ar, rks)
            if op.ar == 15:
                op.att = 0.0
            elif r:
                op.att -= 48 / ta(r) * dt
            if op.att <= 0:
                op.att, op.state = 0.0, 'decay'
        elif op.state == 'decay':
            r = op.rate(op.dr, rks)
            if r:
                op.att += 96 / t96(r) * dt
            if op.att >= op.sl * 3:
                op.att, op.state = max(op.att, op.sl * 3.0), 'sustain'
        elif op.state == 'sustain':
            r = 0 if op.egt else op.rate(op.rr, rks)
            if r:
                op.att += 96 / t96(r) * dt
        elif op.state == 'release':
            r = op.rate(op.rr if op.egt else 7, rks)
            op.att += 96 / t96(r) * dt
        op.att = min(op.att, 48.0)

    def key_on(self):
        for op in (self.mod, self.car):
            op.state = 'damp'

    def key_off(self):
        self.car.state = 'release'          # the modulator keeps its state (YM2413)

    def render(self, n, fnum, block, key, vol):
        f = fnum * OPLL_FS * 2 ** (block - 1) / 2 ** 18
        bf = block * 2 + (fnum >> 8)
        m_env = np.zeros(n)
        c_env = np.zeros(n)
        dt = self.CR / SR
        for i in range(0, n, self.CR):
            for op in (self.mod, self.car):
                self.eg_step(op, key, dt, bf if op.ksr else bf >> 2)
            m_env[i:i + self.CR] = self.mod.att + self.mod.tl
            c_env[i:i + self.CR] = self.car.att + 3 * vol
        idx = np.arange(1, n + 1)
        pm = self.pm + f * self.mod.mult / SR * idx
        pc = self.pc + f * self.car.mult / SR * idx
        lvl = np.clip(np.round(m_env / 0.75), 0, 64).astype(int)
        lvl[m_env >= 47.9] = 64
        ym = self.table[lvl, ((pm % 1.0) * 1024).astype(int) % 1024]
        ym[m_env >= 47.9] = 0.0
        s = np.sin(2 * np.pi * (pc + 4.0 * ym))
        if self.half_c:
            s = np.maximum(s, 0)
        amp = 10 ** (-c_env / 20)
        amp[c_env >= 47.9] = 0.0
        self.pm, self.pc = pm[-1] % 1.0, pc[-1] % 1.0
        return s * amp


def render_fm(per_tick, snaps):
    out = np.zeros(TICKS * SPT)
    import music
    for ch, inst in enumerate(music.FM_INST):
        fc = FmChannel(inst)
        key = 0
        for t in range(TICKS):
            for chip, reg, v in per_tick[t]:
                if chip == 'O' and reg == 0x20 + ch:
                    k = v >> 4 & 1
                    if k and not key:
                        fc.key_on()
                    elif key and not k:
                        fc.key_off()
                    key = k
            opll = snaps[t][1]
            hi, lo, iv = opll[0x20 + ch], opll[0x10 + ch], opll[0x30 + ch]
            out[t * SPT:(t + 1) * SPT] += fc.render(SPT, lo | (hi & 1) << 8, hi >> 1 & 7, key, iv & 15)
    return out * 0.25


def main():
    res, snaps, per_tick = record('none')
    psg = render_psg(snaps)
    write_wav(os.path.join(HERE, 'preview_psg.wav'), psg)
    res, snaps, per_tick = record('internal-0')
    fm = render_fm(per_tick, snaps) + render_psg(snaps, channels=(2,))
    write_wav(os.path.join(HERE, 'preview_fm.wav'), fm)
    print(f'preview_psg.wav, preview_fm.wav: {SECONDS} s at {SR} Hz; SFX at ticks {SFX_AT}')


if __name__ == '__main__':
    main()
