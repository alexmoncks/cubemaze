# Cube Maze 3D for MSX2 + V9968 + geo3d v2.0

A port of **Cube Maze 3D** by **harukaappscreate** (JavaScript, Playload engine)
to the MSX2 with the V9968 and its geo3d v2.0 3D coprocessor, made **with the
original author's permission**. Roll a ball through a maze that covers the six
faces of a cube; crossing an edge rolls the whole cube. The game design, the
mazes' rules, the look and the music are harukaappscreate's; this directory
holds the MSX version of them.

| file | what |
|---|---|
| `release/CUBEMAZE_98.ROM` | V9968 at 98h, geo3d at 9Dh/9Fh: emulators (openMSX with the geo3d extension, blueMSX+ V9968-geo3d) |
| `release/CUBEMAZE_88.ROM` | the V9968 cartridge with the geo3d v2.0 build, DIP switch at 88h |

Both are 128 KB ASCII16 MegaROMs (bank 0 the code, banks 1-4 tables; `msx/build.sh`
writes them to `msx/out/`). They need
an MSX2 or later, a V9968 and geo3d **v2.0** (ID 20h); without it the ROM says
so on the text screen. MSX-MUSIC (internal, or an FM-PAC) is used for the music
when present, the PSG otherwise.

## Playing

| key | joystick (port 1) | |
|---|---|---|
| arrows | stick | roll the ball (the cube turns when it crosses an edge); on the title, pick the size; on the code screen, edit |
| SPACE | trigger A | start / skip the preview / next stage / OK |
| ESC | trigger B | in play: retry the maze; on the title: the stage code screen; elsewhere: back |

Screens: title (sizes 3x3 to 6x6, best score of the size picked), preview (the
cube turns for 3 s, the countdown, SPACE skips it), play, stage clear (time,
rolls, score, best, the code of the size just unlocked), all clear after 6x6.

**Stage codes.** The browser version saves the progress; an MSX cartridge
cannot, so each unlocked size has a 4-letter code, shown on the clear screen
and typed on the title's code screen (ESC):

| unlocks up to | code |
|---|---|
| 4x4 | `NRPT` |
| 5x5 | `B4SX` |
| 6x6 | `MHXV` |

Score, as the original: `max(0, (60003 - time_in_ticks - 300 * rolls) // 6)`,
at 60 ticks a second.

### What differs from the browser version

* At most 30 pictures a second. The game runs 60 ticks a second as the
  original: each picture advances the game by as many ticks as blanks the
  previous one stayed on screen (2 to 4), so the game's speed and its clock do
  not depend on the picture rate down to 15 pictures a second (see
  Performance for the rates measured).
* Progress is not saved: stage codes instead (above). In the original, B on the
  title unlocked every size; here ESC opens the code screen.
* SCREEN 7 (512 x 212, 16 colours from the V9968's 15-bit palette); the
  original's 160 x 144 is scaled to it. The font is larger than the original's,
  so some texts are shorter ("SPACE:START", "ESC:CODE", ...).
* The floors' dither is a screen-aligned mesh like the original's (two palette
  entries per colour, the floors drawn with a logical OR over a checkerboard).
* The random generator is a xorshift32 (it also advances on the title, so each
  game gets another maze); the mazes are not the browser's. A maze with a face
  too large for geo3d's RAM slot is generated again.
* On the title the cube keeps the maze it has while another size is picked (the
  original redraws the old maze at the new size, with walls in the cells it
  does not have).

## Music

The two BGM voices and the four sound effects, transcribed from the original's
MML (`msx/music/`): on MSX-MUSIC the arpeggio is the Clarinet and the bass the
Acoustic Bass, the effects on PSG channel C; without MSX-MUSIC the original's
square waves on the PSG. Details, timing and tests in
[`msx/music/README.md`](msx/music/README.md).

## How it works

* geo3d draws the cube: the floor of each visible face as a textured quad
  (twelve 128 x 64 textures drawn by the VDP when a maze starts: each face,
  active or not), the walls as two layers of flat quads, the goal's box. Only
  the faces in view (at most 3) are in geo3d's RAMs, in three fixed slots.
* The ball and its shadow are copied by the VDP (LMMM, from images in VRAM);
  then the wall quads near the ball that are in front of it are drawn again,
  so the ball goes behind the walls in front of it.
* The background (checkerboard and stars) is restored from VRAM by one HMMM per
  frame, while the Z80 prepares the frame. The HUD's bars and text rows (title,
  code screen, play) are drawn into VRAM caches when their text changes and
  copied every frame; the clear screen draws its texts every frame.
* The camera: the title's spin repeats every 628 ticks and a roll takes 25
  steps; both come from tables, the cube's orientation is one of 24 signed
  permutations.

| file | what |
|---|---|
| `msx/asm/*.asm` | the program (GNU z80asm 1.8): `cubemaze.asm` (start, RAM, VDP helpers), `game.asm`, `maze.asm`, `render.asm`, `hud.asm`, `hw.asm` |
| `msx/ztables.py`, `msx/gen_assets.py` | the integer tables and the ROM's banks 1-4 |
| `msx/zmodel.py` | the program in Python at the level of the Z80: the same state, arithmetic and traffic to geo3d and the VDP, in the same order (the specification of the assembly) |
| `msx/run_z80.py` | runs the ROM in a Z80 emulator and compares it with `zmodel.py` frame by frame |
| `msx/sys_rtl.py`, `msx/sim/tb_system_cm.v` | the ROM's traffic on the RTL: geo3d (`rtl/`) driving HRA!'s V9968 command engine |
| `msx/music/` | the sound driver and its tools |
| `ref/` | the reference port of the game logic (`cubemaze.py`) and its check against the original (`check_logic.py`, `js_trace.js`, node) |
| `msx/scene.py`, `traffic.py`, `hud.py`, `preview.py`, `ref_frames.py` | the floating-point design reference used to set the look |

Build: `msx/build.sh` (python3, numpy, z80asm 1.8).

The original's source (`orig/cubemaze.src.js`) is not part of this repository;
the checks in `ref/` need it in `orig/`.

## Verification

* **Game logic against the original:** `ref/check_logic.py` runs the original
  in node and the Python port side by side, state compared every frame: random
  joypad scripts (3 seeds x 3000 frames) and scripts that solve every size from
  3x3 to the all-clear (3 seeds x 6000 frames): identical.
* **ROM against the model:** `run_z80.py` runs the ROM (both port profiles)
  with joypad scripts that play every size to the all-clear, and one that also
  goes through the title's sizes, the code screen (a wrong code, then a right
  one), the preview's restart and a retry. Every frame's geo3d bytes and VDP
  commands are compared with `zmodel.py`, and the pictures painted from both
  (the geo3d model of `sim/` and a SCREEN 7 command model). The ROM decides
  how many ticks each frame has (from its own timing); the model takes the
  same counts. Result: the touring script to the all-clear and back (9 000
  ticks, 3 755 pictures; both builds, the 88h one with MSX-MUSIC present)
  has the same geo3d bytes, VDP commands, VRAM writes, palette and pages
  shown as the model in every frame; the pictures, painted and compared for
  the first 618 frames of the tour, are identical.
  The same run checks that geo3d and the command registers are only written
  after the Z80 saw geo3d idle.
* **On the RTL:** `sys_rtl.py` replays the ROM's traffic on geo3d's RTL driving
  HRA!'s `vdp_command.v` / `vdp_command_cache.v` (unmodified, SCREEN 7) and
  compares the pages shown with the model's: the title and code screen (40
  frames), the start of a 3x3 game (76 frames), the end of it, its clear
  screen and the 4x4 preview (62 frames): every page identical. (The play
  and clear runs used an earlier build with the same drawing code: the later
  changes are the per-picture tick count and a faster occluder search, which
  change what the Z80 computes, not what it draws.)
* **Music:** `msx/music/test_music.py`, six slot scenarios, every PSG / OPLL
  write against a reference player.

## Performance

Two measures, both from `sys_rtl.py`:

* **The Z80's own work** (the emulator, with geo3d and the VDP answering at
  once): about 145 000 to 160 000 MSX cycles per picture in play on average (a blank is
  59 736), most of it the occluder search, the geo3d slot uploads, the ball and
  the per-tick logic.
* **The drawing** (geo3d's RTL driving HRA!'s command engine, the VRAM always
  ready): about 70 000 to 83 000 MSX cycles per picture in play (background
  copy, three floors, two wall layers, the ball, its occluders, the HUD).

The ROM is then run again with geo3d and CE kept busy as long as the RTL
needed, so the waits cost what they would. Pictures per second (60 Hz MSX):

| screen | pictures / s |
|---|---|
| title, code screen | about 15 |
| preview | about 20 (the first picture of a new maze waits for the maze and its textures: about 0.5 s at 3x3, up to 1.5 s at 6x6) |
| play | about 17 to 18 (3 or 4 blanks per picture, 2 now and then) |
| stage clear | about 12 (its texts are drawn every picture) |

In play the Z80 mostly waits for the drawing now: the occluder search runs
while geo3d draws the floors. Real hardware shares the VRAM with the display,
so its commands are a little slower than in the RTL bench; the game's speed
does not change with it (more ticks per picture), only the smoothness.

## Credits

* **Cube Maze 3D**: game, graphics and music by harukaappscreate. Ported to
  the MSX with the author's permission.
* MSX version: Alex Moncks (code under the MIT licence, see the SPDX headers).
* V9968 and its command engine: HRA!.
