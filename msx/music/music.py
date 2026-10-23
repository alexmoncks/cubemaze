#!/usr/bin/env python3
"""Cube Maze 3D music for the MSX2 port: a compiler of the original game's
ZX Spectrum 128 PLAY strings (the subset the Playload engine accepts, as
read in its compileScore), the tables for the Z80 driver music.asm
(-> music_data.asm), and a reference player that follows Playload's timing
rules on a 60 Hz tick grid (used by test_music.py and the previews).

Time unit: 1 beat = 600 units, so every Playload length is an integer
(0.25 beat = 150, 1/6 = 100, ...). At T96 one 60 Hz tick removes
96 / 60 / 60 beats = 16 units.

    python3 music.py            writes music_data.asm, prints the note tables
"""
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))

# ------------------------------------------------------------------ the source
# cubemaze.src.js lines 108-111
BGM = ['T96M7V8O4dfaCEbDaCEGBdDcgbO3abO4cegbDb))',   # play(0, ...) -> channel 0
       'V6O3N9daeg))']                               # play(1, ...) -> channel 1
SFX = ['V12O5N1eg', 'V13O4N2gCE', 'V13O3N2ec', 'V14O4N2ceg4C2E6G']   # play(2, ...)

UNITS_PER_BEAT = 600
TICK_HZ = 60
TEMPO = 96                                  # BPM, from channel 0's T
UNITS_PER_TICK = TEMPO * UNITS_PER_BEAT // (60 * TICK_HZ)   # 16
assert TEMPO * UNITS_PER_BEAT % (60 * TICK_HZ) == 0

PSG_CLOCK = 1789772.5                       # MSX PSG (3.579545 MHz / 2)
OPLL_FS = 3579545 / 72                      # YM2413 sample rate, 49716 Hz

# OPLL choices (see README): channel 0 (arpeggio) -> FM channel 0,
# channel 1 (bass) -> FM channel 1.
FM_INST = [5, 14]                           # 5 Clarinet, 14 Acoustic Bass
FM_VOL_OFS = 11                             # OPLL attenuation = 11 - V (V8 -> 3, V6 -> 5)

# beats per length number 1..12 (Playload compileScore)
BEATS = [0, 0.25, 0.375, 0.5, 0.75, 1, 1.5, 2, 3, 4, 1 / 6, 1 / 3, 2 / 3]
UNITS = [0, 150, 225, 300, 450, 600, 900, 1200, 1800, 2400, 100, 200, 400]
assert all(abs(b * UNITS_PER_BEAT - u) < 1e-9 for b, u in zip(BEATS, UNITS))


# ------------------------------------------------------------------ compiler
def compile_score(src):
    """Playload's compileScore with lengths in integer units. Returns the
    op list: ('note', midi or None, units), ('V', n), ('T', n), ('M', n),
    ('repeat', start, count) (count 0 = forever)."""
    code, openings = [], []
    i, duration, tie, triplet, previous, octave, accidental = 0, 5, 0, 0, 5, 5, 0
    last_note, unmatched, unmatched_closing = -1, -1, 0

    def number(lo, hi):
        nonlocal i
        s = i
        while i < len(src) and src[i].isdigit():
            i += 1
        if i == s or not lo <= int(src[s:i]) <= hi:
            raise SyntaxError(f'invalid number at {s + 1}')
        return int(src[s:i])

    def repeat(start, count):
        if last_note < start:
            if count == 0:
                raise SyntaxError('a loop needs a note or rest')
            return -1
        code.append(['repeat', start, count])
        return len(code) - 1

    while i < len(src):
        c = src[i]
        i += 1
        if c.isspace() or c == 'N':
            continue
        if c == '!':
            e = src.index('!', i)
            i = e + 1
            continue
        if c.isdigit():
            i -= 1
            n = number(1, 12)
            if n >= 10:
                if not triplet:
                    previous = duration
                triplet = 3
            else:
                triplet = 0
            duration = n
            continue
        if c == '_':
            tie += UNITS[duration]
            continue
        if c == '#':
            accidental += 1
            continue
        if c == '$':
            accidental -= 1
            continue
        if c == '(':
            openings.append(len(code))
            continue
        if c == ')':
            if openings:
                repeat(openings.pop(), 2)
            else:
                unmatched_closing += 1
                if unmatched_closing >= 2:
                    if unmatched < 0:
                        raise SyntaxError('a loop needs a note or rest')
                    code[unmatched][2] = 0
                else:
                    unmatched = repeat(0, 2)
            continue
        if c == 'O':
            octave = number(0, 8)
            continue
        if c in 'VTM':
            rng = {'V': (0, 15), 'T': (60, 240), 'M': (1, 63)}[c]
            code.append([c, number(*rng)])
            continue
        if c == '&' or c.lower() in 'abcdefg':
            if c == '&':
                midi = None
            else:
                semi = {'c': 0, 'd': 2, 'e': 4, 'f': 5, 'g': 7, 'a': 9, 'b': 11}[c.lower()]
                midi = octave * 12 + semi + (12 if c.isupper() else 0) + accidental
            code.append(['note', midi, UNITS[duration] + tie])
            last_note = len(code) - 1
            accidental = tie = 0
            if triplet:
                triplet -= 1
                if triplet == 0:
                    duration = previous
            continue
        raise SyntaxError(f'unsupported command {c!r} at {i} (W, X, U, H: not used by this game)')
    while openings:
        repeat(openings.pop(), 2)
    if tie or accidental:
        raise SyntaxError('incomplete note')
    return [tuple(x) for x in code]


def freq(midi):
    return 440.0 * 2 ** ((midi - 69) / 12)


def psg_period(midi):
    return max(1, min(4095, round(PSG_CLOCK / (16 * freq(midi)))))


def opll_fnum(midi):
    """(block, fnum): the smallest block whose F-number fits 9 bits, i.e. the
    largest F-number (best precision)."""
    f = freq(midi)
    for block in range(8):
        fnum = round(f * 2 ** 18 / OPLL_FS / 2 ** (block - 1))
        if fnum < 512:
            return block, fnum
    raise ValueError(midi)


def opll_freq(block, fnum):
    return fnum * OPLL_FS * 2 ** (block - 1) / 2 ** 18


def fm_att(v):
    return 15 if v == 0 else max(0, min(15, FM_VOL_OFS - v))


NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']


def note_name(midi):
    return 'rest' if midi is None else f'{NOTE_NAMES[midi % 12]}{midi // 12 - 1}'


# ------------------------------------------------------------------ reference player
class Voice:
    def __init__(self, code):
        self.code, self.pc, self.loops, self.rem, self.vol = code, 0, {}, 0, 15
        self.midi = None            # sounding note (None = silent)


class Reference:
    """Playload's AY.sample() on a 60 Hz grid, integer units. Per tick, for
    each channel 0..2: if the voice exists and remaining <= 0 -> next()
    (control ops, then one note adds its length); then remaining -= 16.
    play(2, sfx) replaces voice 2 before the tick it is called ahead of."""

    def __init__(self, bgm=BGM, sfx=SFX):
        self.sfx = [compile_score(s) for s in sfx]
        self.voices = [Voice(compile_score(s)) for s in bgm] + [None]
        self.tick_no = 0

    def play_sfx(self, n):
        self.voices[2] = Voice(self.sfx[n])

    def _next(self, ch, v, ev):
        budget = 32768
        while v.pc < len(v.code):
            budget -= 1
            assert budget, 'loop without notes'
            op = v.code[v.pc]
            v.pc += 1
            if op[0] == 'repeat':
                pos = v.pc - 1
                cnt = v.loops.get(pos, op[2] - 1)
                if op[2] == 0 or cnt > 0:
                    v.loops[pos] = cnt - 1
                    v.pc = op[1]
                else:
                    v.loops.pop(pos, None)
            elif op[0] == 'T':
                assert op[1] == TEMPO or ch != 0, 'the driver has a fixed tempo'
            elif op[0] == 'M':
                pass
            elif op[0] == 'V':
                v.vol = op[1]
                ev.append((self.tick_no, ch, 'vol', op[1]))
            elif op[0] == 'note':
                v.rem += op[2]
                v.midi = op[1]
                ev.append((self.tick_no, ch, 'note', op[1], v.vol, op[2]))
                return
        self.voices[ch] = None
        ev.append((self.tick_no, ch, 'end'))

    def tick(self):
        """One 60 Hz tick; returns the events of this tick."""
        ev = []
        for ch in range(3):
            v = self.voices[ch]
            if v is not None and v.rem <= 0:
                self._next(ch, v, ev)
            if self.voices[ch] is not None:
                self.voices[ch].rem -= UNITS_PER_TICK
        self.tick_no += 1
        return ev

    def state(self):
        """(midi, volume) per channel, None when silent."""
        out = []
        for v in self.voices:
            out.append(None if v is None or v.midi is None else (v.midi, v.vol))
        return out


def timeline(n_ticks, sfx_at=None):
    """Runs the reference for n_ticks ticks; sfx_at = {tick: sfx number}
    (play(2) issued before that tick). Returns (events, states): events is a
    list of (tick, ch, kind, ...), states[t] the per-channel state after tick t."""
    sfx_at = sfx_at or {}
    ref = Reference()
    events, states = [], []
    for t in range(n_ticks):
        if t in sfx_at:
            ref.play_sfx(sfx_at[t])
        events += ref.tick()
        states.append(ref.state())
    return events, states


# ------------------------------------------------------------------ driver data
def flatten(code, allow_loop):
    """Op list -> driver events: ('V', n) / ('N', midi or None, units) and a
    final ('LOOP',) (forever back to the stream start) or ('END',). Finite
    repeats are unrolled; T and M are dropped (T is fixed at 96)."""
    out, pc, loops, guard = [], 0, {}, 0
    while pc < len(code):
        guard += 1
        assert guard < 100000
        op = code[pc]
        pc += 1
        if op[0] == 'repeat':
            pos = pc - 1
            if op[2] == 0:
                assert allow_loop and op[1] == 0, 'only a whole-score loop is supported'
                out.append(('LOOP',))
                return out
            cnt = loops.get(pos, op[2] - 1)
            if cnt > 0:
                loops[pos] = cnt - 1
                pc = op[1]
            else:
                del loops[pos]
        elif op[0] == 'V':
            out.append(('V', op[1]))
        elif op[0] == 'T':
            assert op[1] == TEMPO
        elif op[0] == 'note':
            out.append(('N', op[1], op[2]))
    out.append(('END',))
    return out


def build():
    streams = [('mus_bgm0', flatten(compile_score(BGM[0]), True)),
               ('mus_bgm1', flatten(compile_score(BGM[1]), True))]
    streams += [(f'mus_sfx{k}', flatten(compile_score(s), False)) for k, s in enumerate(SFX)]
    pitches = sorted({e[1] for _, s in streams for e in s if e[0] == 'N' and e[1] is not None})
    assert len(pitches) <= 112
    for _, s in streams:
        assert any(e[0] == 'N' for e in s)
        assert all(0 < e[2] < 32768 for e in s if e[0] == 'N')
    return streams, pitches


def layout(name, stream):
    """Driver stream for flatten()'s events: a header byte (the volume at the
    first note: the leading V's, else 15), then the events. A loop jumps to
    the first event after the header; if the volume at the loop point differs
    from the header's, a V command restores it first (as Playload, which runs
    the leading V's again at each pass). Returns (header, items) with items
    ('V', n) / ('N', midi or None, units) / ('LOOP', label) / ('END',)."""
    i, hdr = 0, 15
    while stream[i][0] == 'V':
        hdr = stream[i][1]
        i += 1
    body = list(stream[i:])
    if body[-1][0] == 'LOOP':
        vol = hdr
        for e in body:
            if e[0] == 'V':
                vol = e[1]
        body[-1:] = ([('V', hdr)] if vol != hdr else []) + [('LOOP', name + '_l')]
    return hdr, body


def encode(name, stream, pitches):
    """Bytes of a stream (the loop target as an offset from its start):
    header volume; note = 2 * pitch index (00h..DEh) + length word (units);
    rest = 0F0h + length word; 0E0h+n = volume n; 0FEh + word = loop;
    0FFh = end (silence, idle)."""
    hdr, body = layout(name, stream)
    b = [hdr]
    for e in body:
        if e[0] == 'V':
            b.append(0xE0 | e[1])
        elif e[0] == 'N':
            b.append(0xF0 if e[1] is None else 2 * pitches.index(e[1]))
            b += [e[2] & 255, e[2] >> 8]
        elif e[0] == 'LOOP':
            b += [0xFE, 1, 0]
        else:
            b.append(0xFF)
    return b


def write_asm(path=os.path.join(HERE, 'music_data.asm')):
    streams, pitches = build()
    L = ['; music_data.asm - generated by music.py from the Cube Maze 3D PLAY strings; do not edit.',
         '; Stream: header byte = volume (AY level) at the first note; then: note = 2 * pitch index,',
         ';         length word (units: 1 beat = 600); rest = 0F0h, length word; 0E0h+n = volume n;',
         ';         0FEh, address = loop; 0FFh = end (silence).',
         '',
         f'MUS_FM_INST0: equ {FM_INST[0] << 4}\t; OPLL instrument {FM_INST[0]} for channel 0 (arpeggio)',
         f'MUS_FM_INST1: equ {FM_INST[1] << 4}\t; OPLL instrument {FM_INST[1]} for channel 1 (bass)',
         f'MUS_STEP: equ {UNITS_PER_TICK}\t\t; units per 60 Hz tick (T{TEMPO}, 600 units per beat)',
         '',
         '; pitch index -> PSG tone period (MSX clock 1789772.5 Hz)',
         'mus_per:']
    for p in pitches:
        L.append(f'\tdw {psg_period(p)}\t\t; {note_name(p)} ({freq(p):.2f} Hz)')
    L.append('; pitch index -> OPLL F-number low byte, block * 2 + F-number bit 8')
    L.append('mus_fnum:')
    for p in pitches:
        bl, fn = opll_fnum(p)
        L.append(f'\tdb {fn & 255}, {bl * 2 + (fn >> 8)}\t\t; {note_name(p)}: block {bl}, F-number {fn} '
                 f'({opll_freq(bl, fn):.2f} Hz)')
    L.append('; AY volume (V) -> OPLL attenuation (3 dB steps, 0 = loudest)')
    L.append('mus_att:\tdb ' + ', '.join(str(fm_att(v)) for v in range(16)))
    L.append('; SFX number -> stream')
    L.append('mus_sfxtab:\tdw mus_sfx0, mus_sfx1, mus_sfx2, mus_sfx3')
    total = 0
    for name, s in streams:
        hdr, body = layout(name, s)
        L.append(f'{name}:\tdb {hdr}\t\t; volume at the start')
        L.append(f'{name}_l:')
        for e in body:
            if e[0] == 'V':
                L.append(f'\tdb 0{0xE0 | e[1]:02X}h\t\t; V{e[1]}')
            elif e[0] == 'N':
                b = 0xF0 if e[1] is None else 2 * pitches.index(e[1])
                L.append(f'\tdb 0{b:02X}h\n\tdw {e[2]}\t\t; {note_name(e[1])}, {e[2] / UNITS_PER_BEAT:g} beat')
            elif e[0] == 'LOOP':
                L.append(f'\tdb 0FEh\n\tdw {e[1]}\t; loop')
            else:
                L.append('\tdb 0FFh\t\t; end')
        total += len(encode(name, s, pitches))
    with open(path, 'w') as f:
        f.write('\n'.join(L) + '\n')
    return path


def describe():
    lines = []
    for ch, s in enumerate(BGM + SFX):
        name = f'BGM channel {ch}' if ch < 2 else f'SFX {ch - 2}'
        code = compile_score(s)
        notes = [op for op in code if op[0] == 'note']
        lines.append(f'{name}: {s!r}: {len(notes)} notes, '
                     f'{sum(n[2] for n in notes) / UNITS_PER_BEAT:g} beats')
        for op in notes:
            bl, fn = opll_fnum(op[1])
            lines.append(f'   {note_name(op[1]):4s} midi {op[1]:3d} {freq(op[1]):8.2f} Hz  '
                         f'{op[2] / UNITS_PER_BEAT:6.3f} beat  PSG {psg_period(op[1]):4d}  '
                         f'OPLL blk {bl} fnum {fn}')
    return '\n'.join(lines)


if __name__ == '__main__':
    print(describe())
    print('wrote', write_asm())
