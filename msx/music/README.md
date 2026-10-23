# Cube Maze 3D, MSX2 port: sound module

The music and sound effects of harukaappscreate's "Cube Maze 3D" (ported with the
author's permission), rebuilt for the MSX2 cartridge: a Z80 driver that plays the
BGM on MSX-MUSIC (OPLL) when one is present and on the PSG otherwise, with the
SFX always on PSG channel C.

| file | what |
|---|---|
| `music.py` | MML compiler (the Playload subset), table generator (`music_data.asm`), reference player (Playload's timing on a 60 Hz grid) |
| `music_data.asm` | generated tables and streams (do not edit; run `python3 music.py`) |
| `music.asm` | the driver (GNU z80asm 1.8), includes `music_data.asm` |
| `test_music.py` | runs the driver in the pip `z80` emulator with a stub BIOS and checks every PSG/OPLL write against the reference |
| `preview.py` | renders `preview_psg.wav` and `preview_fm.wav` from the driver's recorded writes |

## Source and how it was transcribed

From `orig/cubemaze.src.js` (lines 108-111), played by the Playload engine (an
AY-3-8910 model taking ZX Spectrum 128 PLAY strings):

```
sfx(t) = play(2, ['V12O5N1eg', 'V13O4N2gCE', 'V13O3N2ec', 'V14O4N2ceg4C2E6G'][t])
play(0, 'T96M7V8O4dfaCEbDaCEGBdDcgbO3abO4cegbDb))')
play(1, 'V6O3N9daeg))')
```

`music.py` re-implements Playload's `compileScore` (read in `ext/pl/src/engine/sound.js`,
not executed): `N` and blanks ignored; a number 1..12 picks the length
(beats `[0, .25, .375, .5, .75, 1, 1.5, 2, 3, 4, 1/6, 1/3, 2/3]`, default 1 beat);
`a`..`g` notes, upper case one octave up, `O5` lower-case `c` = MIDI 60; `&` rest;
`#`/`$`, `_` ties, triplets, `( )` repeats and the "two unmatched `)` = loop forever"
rule are implemented as in the JS. `V` is a fixed AY level, `T` only counts on
channel 0 and is global (T96 everywhere, SFX included), `M7` (tones only) is ignored.
Lengths are kept in integer units, 1 beat = 600 (so 1/6 beat = 100, 0.375 = 225), and
one 60 Hz tick removes 96/60/60 beat = 16 units.

Timing follows Playload's player exactly: each voice has `remaining`; when it is <= 0
the next event runs (control ops, then one note adds its length to what is left), then
16 units are removed. Note k of channel 0 therefore starts at tick ceil(600k/16)
(0, 38, 75, 113, 150, ...) and the music never drifts. The two BGM channels loop
independently: channel 0 is **25** notes of 1 beat (25 beats = 15.625 s; the brief
said 29, the string has 25), channel 1 is 4 notes of 4 beats (16 beats = 10 s), so they
drift against each other and realign every 400 beats (250 s), as in the original.
`play(2, ...)` restarts the SFX voice (volume 15 until its `V`); when an SFX ends,
channel C is silent.

Pitches: equal temperament, A4 = 440 Hz. PSG period = round(1789772.5 / (16 f))
(the MSX PSG clock, not Playload's Spectrum 1773400 Hz, so the pitch is the same as
the original's). OPLL: fnum = round(f * 2^18 / 49716 / 2^(block-1)) with the smallest
block that keeps fnum < 512 (here always 258..460, i.e. the best precision). Worst
pitch error: 2.6 cents on the OPLL, 3.8 cents on the PSG.

Note names below: MIDI 60 = C4 (= Spectrum `O5c`).

**BGM channel 0 (arpeggio)**, V8, 25 notes of 1 beat (600 units), looping:

| # | note | MIDI | Hz | PSG period | OPLL block / fnum |
|---|---|---|---|---|---|
| 1 | D3 | 50 | 146.83 | 762 | 2 / 387 |
| 2 | F3 | 53 | 174.61 | 641 | 2 / 460 |
| 3 | A3 | 57 | 220.00 | 508 | 3 / 290 |
| 4 | C4 | 60 | 261.63 | 428 | 3 / 345 |
| 5 | E4 | 64 | 329.63 | 339 | 3 / 435 |
| 6 | B3 | 59 | 246.94 | 453 | 3 / 326 |
| 7 | D4 | 62 | 293.66 | 381 | 3 / 387 |
| 8 | A3 | 57 | 220.00 | 508 | 3 / 290 |
| 9 | C4 | 60 | 261.63 | 428 | 3 / 345 |
| 10 | E4 | 64 | 329.63 | 339 | 3 / 435 |
| 11 | G4 | 67 | 392.00 | 285 | 4 / 258 |
| 12 | B4 | 71 | 493.88 | 226 | 4 / 326 |
| 13 | D3 | 50 | 146.83 | 762 | 2 / 387 |
| 14 | D4 | 62 | 293.66 | 381 | 3 / 387 |
| 15 | C3 | 48 | 130.81 | 855 | 2 / 345 |
| 16 | G3 | 55 | 196.00 | 571 | 3 / 258 |
| 17 | B3 | 59 | 246.94 | 453 | 3 / 326 |
| 18 | A2 | 45 | 110.00 | 1017 | 2 / 290 |
| 19 | B2 | 47 | 123.47 | 906 | 2 / 326 |
| 20 | C3 | 48 | 130.81 | 855 | 2 / 345 |
| 21 | E3 | 52 | 164.81 | 679 | 2 / 435 |
| 22 | G3 | 55 | 196.00 | 571 | 3 / 258 |
| 23 | B3 | 59 | 246.94 | 453 | 3 / 326 |
| 24 | D4 | 62 | 293.66 | 381 | 3 / 387 |
| 25 | B3 | 59 | 246.94 | 453 | 3 / 326 |

**BGM channel 1 (bass)**, V6, 4 notes of 4 beats (2400 units), looping:

| # | note | MIDI | Hz | PSG period | OPLL block / fnum |
|---|---|---|---|---|---|
| 1 | D2 | 38 | 73.42 | 1524 | 1 / 387 |
| 2 | A2 | 45 | 110.00 | 1017 | 2 / 290 |
| 3 | E2 | 40 | 82.41 | 1357 | 1 / 435 |
| 4 | G2 | 43 | 98.00 | 1141 | 2 / 258 |

**SFX** (PSG C, both modes; then silence):

| SFX | string | volume | notes (length in beats) and PSG periods | total |
|---|---|---|---|---|
| 0 | `V12O5N1eg` | 12 | E4 (0.25) 339, G4 (0.25) 285 | 0.5 beat, 19 ticks |
| 1 | `V13O4N2gCE` | 13 | G3 (0.375) 571, C4 (0.375) 428, E4 (0.375) 339 | 1.125 beat, 43 ticks |
| 2 | `V13O3N2ec` | 13 | E2 (0.375) 1357, C2 (0.375) 1710 | 0.75 beat, 29 ticks |
| 3 | `V14O4N2ceg4C2E6G` | 14 | C3 (0.375) 855, E3 (0.375) 679, G3 (0.375) 571, C4 (0.75) 428, E4 (0.375) 339, G4 (1.5) 285 | 3.75 beat, 141 ticks |

## Instruments and volumes on MSX-MUSIC

The original is two constant-volume square waves held for their whole length.

* **Channel 0 (arpeggio): OPLL instrument 5, Clarinet**, on FM channel 0. Its
  modulator runs at twice the carrier frequency (MULT 2 : 1), and a 2:1 FM pair
  produces only odd harmonics, like a square wave: the closest built-in timbre to
  the AY's hollow square. Both operators use the sustained envelope type, so a note
  holds for its whole beat like the original.
* **Channel 1 (bass): OPLL instrument 14, Acoustic Bass**, on FM channel 1. MULT 1 : 1
  (sounds at the written pitch; Synth Bass 13 has its carrier at MULT 0.5 and would
  sound an octave low), carrier decay rate 0, so the attack level is held and only
  falls slowly (release rate 2 in the percussive sustain phase). Caveat: unlike the
  original's flat square, the bass fades a little over its 4-beat notes. If a flat
  drone is preferred, set `FM_INST[1] = 5` (Clarinet) in `music.py` and regenerate.
* **Volumes:** OPLL attenuation = 11 - V (3 dB per step on both chips), so V8 -> 3 and
  V6 -> 5: the bass stays 6 dB under the melody as in the original. The offset
  (`FM_VOL_OFS`) sets the BGM level against the PSG SFX, which depends on each
  machine's mix of FM and PSG; it is a guess to check on hardware.
* Each note is re-articulated: key off (at the old pitch), F-number low, then
  block / F-number bit 8 with key on (sustain bit 0), so repeated notes are struck again.

Without MSX-MUSIC the BGM is the original: PSG A = channel 0 at V8, PSG B = channel 1
at V6, periods for the MSX clock.

## Interface

`include "music.asm"` in the code bank (page 1, always visible) after defining
`MUS_RAM: equ <address>` (the driver uses MUS_RAM..MUS_RAM+39 of the 128 bytes
reserved, no other RAM). z80asm resolves `include` against the current directory and
the `-I` paths: assemble with `-I <this directory>` so `music_data.asm` is found.
Size: 1091 bytes (853 code, 238 tables). All labels start with `mus_`, `MUS_`,
`snd_` or `sfx_`.

| label | call | changes |
|---|---|---|
| `snd_init` | once at start-up, interrupts disabled. Scans every primary slot and, where EXPTBL (FCC1h) says it is expanded, every subslot with RDSLT (000Ch) for `APRLOPLL` at 401Ch (internal MSX-MUSIC, preferred) or `PAC2OPLL` (FM-PAC: then 7FF6h is read with RDSLT and written back with bit 0 set with WRSLT (0014h), enabling its I/O ports); `DI` after every BIOS call. Sets `MUS_FLAG`, initialises the PSG (R7 = B8h: tones on, noise off, bit 7 = 1 port B output, bit 6 = 0 port A input; R8-R10 = 0) and, with MSX-MUSIC, the OPLL (rhythm off, all keys off, volumes, the two instruments), then starts the BGM (first notes at the first `snd_tick`). R14/R15 are never written. | AF, BC, DE, HL |
| `snd_tick` | once per vertical blank (60 Hz) | AF, BC, DE, HL (IX, IY, alternate set preserved) |
| `sfx_play` | A = 0..3 (masked with 3): starts or restarts that SFX on PSG C; its first note sounds at the next `snd_tick` | AF, DE, HL |
| `MUS_FLAG` | RAM byte: 0 = PSG only, 1 = OPLL found | |

OPLL writes go to ports 7Ch/7Dh with 15 T-states from the address write to the data
write (>= 12) and at least 87 T-states from a data write to the next address write
(>= 84), counted in plain Z80 T-states (an MSX adds an M1 wait, so real gaps are
longer: 17 and 94 cycles). For a turbo CPU (R800) the delays would need to be longer.

Stream format (`music_data.asm`): a header byte (the volume at the first note), then
`2 * pitch index` + length word (units) per note, `F0h` + length for a rest,
`E0h+n` volume, `FEh` + address loop, `FFh` end. Pitch tables `mus_per` (PSG period)
and `mus_fnum` (OPLL F-number low, block * 2 + bit 8) are indexed by the same byte.
A loop jumps past the header; if the volume at the loop point differed from the
header's, the compiler inserts a `V` before the jump (Playload re-runs the leading `V`
at each pass).

## Cost per tick (measured in the emulator)

Plain Z80 T-states per `snd_tick` (MSX cycles with the M1 wait in brackets), over
15200 ticks (both BGM loops wrap several times and realign at tick 15000) with 11 SFX
calls:

| | typical (no event) | one BGM note | both BGM notes | worst (tick 15000: both loops wrap + both notes + SFX start) |
|---|---|---|---|---|
| PSG only | 223 | 540 | 860 | 1474 (1649) |
| MSX-MUSIC | 223 | 634 | 1045 | 1659 (1850) |

Mean 235 / 238 T-states. `sfx_play`: 161 T-states. `snd_init`: 6 400 to 23 000
T-states plus the BIOS's own RDSLT time (the stubs answer at once), up to 16 slots x
8 bytes.

## Tests

```
python3 test_music.py            # 15200 ticks per scenario (~2 s)
python3 test_music.py --quick    # 2000 ticks
python3 preview.py               # writes preview_psg.wav, preview_fm.wav
```

`test_music.py` regenerates `music_data.asm`, assembles a test program (`build/`,
MUS_RAM = C800h, org 4000h) and runs it in the pip `z80` emulator. RDSLT/WRSLT are
trapped and answered from a simulated slot map; they clobber AF/BC/DE and return with
interrupts enabled so the driver's `DI` is checked. Scenarios: no MSX-MUSIC
(with a near-miss `PAC2OPL!` ID); internal MSX-MUSIC in slot 0 and in slot 3-3;
FM-PAC in slot 1 and in slot 2-1 (7FF6h read, bit 0 set, other bits kept, written in
the right slot); FM-PAC plus internal MSX-MUSIC (internal used, the FM-PAC left
alone). Checked for each:

* the reference timeline against closed forms of Playload's rule (channel 0 note k
  at ceil(600k/16), channel 1 at 150k, SFX notes and ends), the pitch formulas;
* after every tick, the PSG and OPLL register files rebuilt from the recorded OUTs
  equal the reference state: PSG periods and volumes per channel; OPLL F-number,
  block, key and instrument/volume register; PSG A/B silent in FM mode;
* period / F-number writes happen exactly on the note-start ticks, and every FM note
  tick keys off then on; channel C is silenced exactly when each SFX ends (also when an
  SFX restarts itself or another one);
* OPLL writes are address/data pairs with >= 12 / >= 84 T-state gaps; no OPLL write
  without MSX-MUSIC; R7 bits 7/6 = 1/0; R14/R15 never written;
* IX, IY and the alternate registers survive `snd_tick`, BC survives `sfx_play`, no
  RAM outside MUS_RAM..+127 (and the stack) is written, interrupts off after
  `snd_init`, well-formed slot IDs.

Result: all 6 scenarios pass. The checks were themselves tested by mutating the driver
(wrong period, wrong F-number, tempo step 15, a missing delay `nop`, no `DI` after RDSLT,
no key off, SFX end not muted, FM-PAC bit 1 instead of 0, R7 bit 6 set, IX clobbered,
wrong attenuation table, no carry of `remaining`): every mutation is detected.

## Previews

`preview_psg.wav` and `preview_fm.wav`: 40 s, 44.1 kHz mono, rendered from the
register writes the Z80 driver made in the emulator (no MSX-MUSIC / internal
MSX-MUSIC), with SFX 1, 0, 0, 2, 3, 1, 3 at 4.0, 10.0, 10.25, 17.0, 25.0, 33.0 and 36.0 s.

* PSG: square waves (8x oversampled, box filtered), the AY volume curve Playload uses
  (Westcott's measurements), state held per 1/60 s tick.
* FM: **an approximation of the YM2413**, written for this preview: 2-operator FM with
  the built-in patch bytes of the widely used dump (emu2413's table), modulator
  feedback, MULT, TL, AR/DR/SL/RR with the sustained/percussive envelope types and the
  key-on damp phase, as linear-in-dB envelopes with OPL-style rate tables; no KSL, no
  AM/vibrato LFO, no 9-bit DAC or rounding behaviour, and the modulation depth scale is
  an estimate. The SFX in this file are the PSG C writes, mixed at an assumed equal
  full scale. Real hardware will differ in timbre and FM/PSG balance.

## Open questions / uncertainties

* Channel 0 has 25 notes, not 29: confirm that the source string is the intended one.
* FM/PSG balance (`FM_VOL_OFS = 11`) and the bass instrument (14 fades slowly over
  4 beats; 5 would hold) should be judged on a real MSX-MUSIC machine or openMSX.
* Only `play` channels 0-2 with the commands this game uses are supported by the
  driver (`W`, `X`, `U`, `H`, envelopes and noise are rejected by the compiler); `T`
  must stay 96 (MUS_STEP is fixed at 16 units per tick); a PAL (50 Hz) machine would
  need MUS_STEP = 19.2 (not an integer: use a 50 Hz table or tick at 60 Hz).
* With both an internal MSX-MUSIC and an FM-PAC present, the FM-PAC's I/O is not
  enabled (to avoid two chips on the same ports).
