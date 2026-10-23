; SPDX-License-Identifier: MIT
; Copyright (c) 2026 Alex Moncks
; ============================================================================
; cubemaze.asm - Cube Maze 3D for MSX2 + V9968 + geo3d v2.0 (ASCII16 MegaROM)
;
; A port of "Cube Maze 3D" by harukaappscreate (JavaScript, Playload engine),
; made with the author's permission. Roll a ball through a maze that covers
; the six faces of a cube; crossing an edge rolls the cube.
;
; SCREEN 7 (512 x 212, 16 colours from the V9968's 15-bit palette), at most
; 30 pictures a second; the game at 60 ticks a second as the original (each
; picture advances it by as many ticks as blanks the last one was shown, 2
; to 4). geo3d v2.0
; draws the cube: the floor of each visible face as textured quads (the
; textures are drawn by the VDP at the start of each maze), the walls as two
; layers of flat quads, the goal's box; only the visible faces (at most 3) are
; in geo3d's RAMs. The ball and its shadow are copied by the VDP (LMMM), then
; the walls in front of it are painted again. The HUD's texts are drawn
; glyph by glyph from masks in VRAM (a fill, then AND), into caches (the
; bars, the title's text rows) that are copied every frame.
;
; The program follows zmodel.py (the same tables, the same integer
; arithmetic, the same traffic to geo3d and the VDP): run_z80.py compares
; the two frame by frame.
;
; VRAM (256 KB, 256 bytes per line):
;   page 0 (0-211), page 1 (256-467)   the two pictures
;   212-253: in play the top bar (212-229) and the bottom bar (230-247),
;   on the title / code screen three text rows (212, 226, 240); 468-481
;   the title's first text row
;   page 2: 512-723 background (checkerboard of indices 0 / 1, both black,
;           and the stars), 724-765 glyph masks (3 rows of 21 cells 24 x 14)
;   page 3: 768-959 twelve floor textures (slots of 128 x 64: face x active),
;           960-991 ball images, 992-1023 shadow images
;
; Rules kept (as sphere7.asm): no write to R#32-R#58 while geo3d's RUN is
; busy; R#15 = 0 except inside wait_ce; page flips and palette writes right
; after S#0 shows a vertical blank; no interrupts at all (DI from start).
;
; Banks (ASCII16): 0 this code (4000h), 1-4 tables (8000h, gen_assets.py).
; Assemble: build.sh (z80asm 1.8)
; ============================================================================

        include "out/ports.asm"             ; PORT_BASE
        include "out/inc/equ.asm"

VDP_DATA:   equ PORT_BASE
VDP_CTRL:   equ PORT_BASE + 1
VDP_PAL:    equ PORT_BASE + 2
VDP_IND:    equ PORT_BASE + 3
VDP_PORT4:  equ PORT_BASE + 4
GEO_IDX:    equ PORT_BASE + 5
GEO_DAT:    equ PORT_BASE + 7

PPI_B:      equ 0xA9
PPI_C:      equ 0xAA
PSG_A:      equ 0xA0
PSG_D:      equ 0xA1
PSG_R:      equ 0xA2

ENASLT:     equ 0x0024
MSXVER:     equ 0x002D
INITXT:     equ 0x006C
CHPUT:      equ 0x00A2
RSLREG:     equ 0x0138
EXPTBL:     equ 0xFCC1

BANK2_SEL:  equ 0x7000              ; ASCII16: bank of 8000h-BFFFh
WAIT_TURNS: equ 6                   ; x 65536 polls, then hw_fail

; ----------------------------------------------------------------------------
; RAM (page 3, C000h-F37Fh; the stack below F380h)
RAM:        equ 0xC000
my_slot:    equ RAM + 0x000
vbl:        equ RAM + 0x001         ; 2: vertical blanks seen
flip_vbl:   equ RAM + 0x003         ; 2: the blank of the last flip
first:      equ RAM + 0x005         ; 1 until a frame was drawn
pg:         equ RAM + 0x006         ; page being drawn (0 / 1)
fail:       equ RAM + 0x007
pal_act:    equ RAM + 0x008         ; colour in palette entry DITH_ACT
flip_actc:  equ RAM + 0x009         ; active face colour of the frame drawn last
baked:      equ RAM + 0x00A         ; stage whose textures are in VRAM (FFh none)
nflip:      equ RAM + 0x00B         ; 2
late:       equ RAM + 0x00D         ; 2
in_snd:     equ RAM + 0x00F         ; 1 while snd_tick runs (vpoll re-entry)
; game
ph:         equ RAM + 0x010
lv:         equ RAM + 0x011
unl:        equ RAM + 0x012
best:       equ RAM + 0x013         ; 4 words
tick_t:     equ RAM + 0x01B         ; 2: T
t628:       equ RAM + 0x01D         ; 2
t42:        equ RAM + 0x01F
sc:         equ RAM + 0x020         ; 2
rep:        equ RAM + 0x022
code:       equ RAM + 0x023         ; 4
cpos:       equ RAM + 0x027
keyprev:    equ RAM + 0x028
keyheld:    equ RAM + 0x029
keyp:       equ RAM + 0x02A         ; new presses this tick
rng:        equ RAM + 0x02B         ; 4 (little-endian)
stage:      equ RAM + 0x02F
act:        equ RAM + 0x030
el:         equ RAM + 0x031         ; 2
rot:        equ RAM + 0x033         ; 2
mv_on:      equ RAM + 0x035
mv_from:    equ RAM + 0x036
mv_to:      equ RAM + 0x037
mv_j:       equ RAM + 0x038
roll_on:    equ RAM + 0x039
roll_a:     equ RAM + 0x03A
roll_k:     equ RAM + 0x03B
orient:     equ RAM + 0x03C
prv:        equ RAM + 0x03D         ; 2 (signed)
cur:        equ RAM + 0x03F
st:         equ RAM + 0x040
gl:         equ RAM + 0x041
cam_kind:   equ RAM + 0x042         ; 0 spin, 1 play, 2 clear
cam_t:      equ RAM + 0x043         ; 2
cam_o:      equ RAM + 0x045
cam_a:      equ RAM + 0x046
cam_k:      equ RAM + 0x047
nn:         equ RAM + 0x048         ; lv * lv
ncell:      equ RAM + 0x049         ; 6 * lv * lv
gl_face:    equ RAM + 0x04A
tmp:        equ RAM + 0x04B         ; 8 scratch bytes
fnn:        equ RAM + 0x053         ; 6: f * lv * lv
rlv:        equ RAM + 0x059         ; 6: r * lv
lvc:        equ RAM + 0x060         ; LV_SIZE: this size's constants (words)
; render
mat:        equ RAM + 0x0A0         ; 18: the frame's matrix (Q2.14)
mtmp:       equ RAM + 0x0B2         ; 18
mtmp2:      equ RAM + 0x0C4         ; 18
vis_n:      equ RAM + 0x0D6
vis:        equ RAM + 0x0D7         ; 3 faces, farthest first
vkey:       equ RAM + 0x0DA         ; 3 words (sort keys)
slots:      equ RAM + 0x0E0         ; 3 x (face, act); face FFh: empty
vslot:      equ RAM + 0x0E6         ; slot of each vis entry
kept:       equ RAM + 0x0E9         ; 3 flags: slot kept this frame
cmdbuf:     equ RAM + 0x0F0         ; 16: a command's registers
; the face being emitted
fax:        equ RAM + 0x100         ; 6: its axes (2 * component, negate) x 3
fp_n:       equ RAM + 0x106         ; 2
fp_u:       equ RAM + 0x108         ; 2
fp_v:       equ RAM + 0x10A         ; 2
pt:         equ RAM + 0x10C         ; 6: x, y, z
cur_face:   equ RAM + 0x112
cur_vb:     equ RAM + 0x113         ; 2: vertex base
cur_fb:     equ RAM + 0x115         ; 2: face base
cur_act:    equ RAM + 0x117
cur_goal:   equ RAM + 0x118
cur_nr:     equ RAM + 0x119         ; runs of this face
cur_runs:   equ RAM + 0x11A         ; 2: pointer
cur_walls:  equ RAM + 0x11C         ; 2
cur_nw:     equ RAM + 0x11E
vg_ofs:     equ RAM + 0x11F         ; 2: local index of the goal's vertices
fidx:       equ RAM + 0x121         ; 4 words: a face's indices
fbase_col:  equ RAM + 0x129
ng_ofs:     equ RAM + 0x12A         ; 2: local face index of goal2
; ball
bm:         equ RAM + 0x130         ; 6
bsh:        equ RAM + 0x136         ; 6
b_px:       equ RAM + 0x13C         ; 2
b_py:       equ RAM + 0x13E         ; 2
b_pz:       equ RAM + 0x140         ; 2
b_qx:       equ RAM + 0x142
b_qy:       equ RAM + 0x144
b_zb:       equ RAM + 0x146         ; 2: the ball's key
bx0:        equ RAM + 0x148
p0:         equ RAM + 0x150         ; 6
p1:         equ RAM + 0x156         ; 6
near:       equ RAM + 0x160         ; 32 bytes: bitmap of cells
nfr:        equ RAM + 0x180         ; frontier lists (2 x 64)
nfr2:       equ RAM + 0x1C0
nfr_n:      equ RAM + 0x200
nfr2_n:     equ RAM + 0x201
occ_n:      equ RAM + 0x202
f_mn:       equ RAM + 0x204         ; 2
f_mu:       equ RAM + 0x206         ; 4
f_mv:       equ RAM + 0x20A         ; 4
f_amid:     equ RAM + 0x20E         ; 4
f_atop:     equ RAM + 0x212         ; 4
f_bmid:     equ RAM + 0x216         ; 2: biases
f_btop:     equ RAM + 0x218
f_cmid:     equ RAM + 0x21A         ; colours
f_ctop:     equ RAM + 0x21B
acc:        equ RAM + 0x21C         ; 4
acc2:       equ RAM + 0x220         ; 4
occ:        equ RAM + 0x230         ; N_SCRATCH x 8: face, layer, col, tu, tv, d, -, -
mu_tab:     equ RAM + 0x300         ; 4 x 25: tu * mu for tu = -12..12
mv_tab:     equ RAM + 0x370         ; 4 x 25
uh_tab:     equ RAM + 0x3E0         ; 2 x 25: t * HG
; HUD
nbuf:       equ RAM + 0x420         ; 24: a string
txt_x:      equ RAM + 0x440         ; 2
txt_y:      equ RAM + 0x442         ; 2
txt_col:    equ RAM + 0x444
; maze
grid:       equ RAM + 0x500         ; 216: passage bits per cell
cf:         equ RAM + 0x600         ; 216: face of a cell
cr:         equ RAM + 0x700         ; 216: row
cc:         equ RAM + 0x800         ; 216: column
dfs:        equ RAM + 0x900         ; 216 x 4: cell, depth, dirs, next
walls:      equ RAM + 0xC80         ; 6 x 88 x 4: tu, tv, ci, d
walls_n:    equ RAM + 0x1500        ; 6
walls_p:    equ RAM + 0x1506        ; 6 x 2
runs:       equ RAM + 0x1520        ; 6 x 48 x 4: o, line, ta, tb
runs_n:     equ RAM + 0x1A00        ; 6
runs_p:     equ RAM + 0x1A06        ; 6 x 2
MUS_RAM:    equ RAM + 0x1B00        ; 128 bytes for the sound driver
wptr:       equ RAM + 0x1B80        ; 216 x 2: a cell's first wall in walls
wcnt:       equ RAM + 0x1D30        ; 216: its number of walls
nbr:        equ RAM + 0x1E10        ; 216 x 4: the neighbour of a cell in each direction
el_sub:     equ RAM + 0x2172
el_sec:     equ RAM + 0x2173        ; 2
ctx:        equ RAM + 0x2178        ; 3 x 14: face contexts of vis (cur_face .. cur_nw, slot)
flist:      equ RAM + 0x21B0        ; 6 x 32: per face, count + near cells
stamp:      equ RAM + 0x2170
mlv:        equ RAM + 0x22A0        ; the size of the maze in geo3d / the textures
nextra:     equ RAM + 0x22A1        ; ticks beyond 2 per frame (0 .. 2)
ram_end:    equ RAM + 0x22A2
nflag:      equ 0xE300              ; 256, page-aligned: near flags (stamp)
n2tab:      equ 0xE400              ; 216 x 14: per cell, count + the cells within 2 steps
STACK_TOP:  equ 0xF380

        org 0x4000
        db "AB"
        dw init
        dw 0, 0, 0
        ds 6, 0
        db "ROM_AS16"                   ; 4010h: ROM type signature (MSXgl): ASCII16
        include "../../tools/mapper_tag_ascii16.asm"

; ----------------------------------------------------------------------------
init:
        di
        ld sp, STACK_TOP
        ld hl, RAM
        ld de, RAM + 1
        ld bc, ram_end - RAM - 1
        ld (hl), 0
        ldir
        ; page 2 -> this cartridge's slot (the slot of page 1)
        call RSLREG
        rrca
        rrca
        and 3
        ld c, a
        ld b, 0
        ld hl, EXPTBL
        add hl, bc
        ld a, (hl)
        and 0x80
        or c
        ld c, a
        inc hl
        inc hl
        inc hl
        inc hl
        ld a, (hl)
        and 0x0C
        or c
        ld (my_slot), a
        ld h, 0x80
        call ENASLT
        di
        ld a, TBANK1
        call setbank
        call geo_probe
        jp nz, nogeo
        call snd_init                   ; (BIOS slot calls; before the VDP set-up)
        di
        call vdp_init
        call geo_init
        call game_init
        ld a, 1
        ld (pg), a                      ; the first frame goes to page 1
        ld (first), a
        ld a, 0xFF
        ld (baked), a
        ld (cbot), a
        ld (ctop), a
        ld (hkey), a
        ld a, 0x40
        ld b, 1
        call vdp_wreg                   ; display on, no interrupts
        ld hl, (vbl)
        ld (flip_vbl), hl

; ----------------------------------------------------------------------------
; The ticks (the last one's camera is the frame's), then the frame: the
; previous one is shown at its blank, the textures drawn if the maze is new.
; Two ticks, or as many as blanks the last picture was shown (at most 4): the
; game keeps its 60 ticks a second down to 15 pictures a second.
main_loop:
        call tick
        call tick
        ld a, (nextra)
        or a
        jr z, ml_t
        ld b, a
ml_x:   push bc
        call tick
        pop bc
        djnz ml_x
ml_t:   call wait_geo
        call wait_ce
        ld a, (first)
        or a
        call z, flip
        xor a
        ld (first), a
        ld a, (stage)
        ld hl, baked
        cp (hl)
        jr z, ml_1
        ld (hl), a
        call bake
        ld a, 0xFF
        ld (slots), a
        ld (slots + 2), a
        ld (slots + 4), a
ml_1:   call draw_frame
        ld a, (act)
        ld hl, T_FCOL
        call add_hl_a
        ld a, (hl)
        ld (flip_actc), a
        ld a, (pg)
        xor 1
        ld (pg), a
        jr main_loop

; ----------------------------------------------------------------------------
; Page flip: show page 1 - pg on the second blank after the last flip (or the
; next one when late), then palette entry DITH_ACT if its colour changed.
flip:
        ld hl, (flip_vbl)
        ld de, 2
        add hl, de
        ex de, hl                       ; DE = the blank to flip on
        ld hl, (vbl)
        or a
        sbc hl, de
        jr c, fl_1
        ld hl, (late)
        inc hl
        ld (late), hl
        ld de, (vbl)
        inc de
fl_1:   call vwait                      ; next blank
        ld hl, (vbl)
        or a
        sbc hl, de
        jr c, fl_1
        ld hl, (vbl)
        ld de, (flip_vbl)
        ld (flip_vbl), hl
        or a
        sbc hl, de                      ; blanks since the last flip
        ld a, h
        or a
        ld a, 4
        jr nz, fl_n
        ld a, l
        cp 4
        jr c, fl_n0
        ld a, 4
        jr fl_n
fl_n0:  cp 2
        jr nc, fl_n
        ld a, 2
fl_n:   sub 2
        ld (nextra), a                  ; the ticks beyond 2 of the next frame
        ld a, (pg)
        xor 1
        rrca
        rrca
        rrca
        or 0x1F                         ; R#2 = page * 32 + 1Fh
        ld b, 2
        call vdp_wreg
        ld a, (flip_actc)
        ld hl, pal_act
        cp (hl)
        jr z, fl_2
        ld (hl), a
        ld l, a                         ; T_PALACT + 3 * colour
        add a, a
        add a, l
        ld hl, T_PALACT
        call add_hl_a
        ld a, DITH_ACT
        ld b, 16
        call vdp_wreg
        ld bc, 3 * 256 + VDP_PAL
        otir
fl_2:   ld hl, (nflip)
        inc hl
        ld (nflip), hl
        ret

; wait for the next vertical blank (counts it)
vwait:  in a, (VDP_CTRL)                ; S#0 (R#15 = 0)
        rlca
        jr nc, vwait
        jp vblank

; ----------------------------------------------------------------------------
; VDP helpers
setbank:                                ; A = ASCII16 bank of page 2 (8000h-BFFFh)
        ld (BANK2_SEL), a
        ret

vdp_wreg:                               ; A = value, B = register
        out (VDP_CTRL), a
        ld a, b
        or 0x80
        out (VDP_CTRL), a
        ret

; CE (S#2 bit 0) = 0. R#15 = 2 only in here. Keeps BC, DE, HL.
wait_ce:
        ld a, 2
        out (VDP_CTRL), a
        ld a, 0x80 + 15
        out (VDP_CTRL), a
        in a, (VDP_CTRL)
        rrca
        jr c, wce_slow
wce_2:  xor a
        out (VDP_CTRL), a
        ld a, 0x80 + 15
        out (VDP_CTRL), a
        jp vpoll                        ; (S#0 again)
wce_slow:
        push de
        push bc
        ld de, 0
        ld c, WAIT_TURNS
wce_1:  in a, (VDP_CTRL)
        rrca
        jr nc, wce_3
        dec de
        ld a, d
        or e
        jr nz, wce_1
        dec c
        jr nz, wce_1
        ld a, 2
        ld (fail), a
        jp hw_fail
wce_3:  pop bc
        pop de
        jr wce_2

; one poll of S#0 (R#15 = 0): a vertical blank since the last read -> vblank
vpoll:  in a, (VDP_CTRL)
        rlca
        ret nc
vblank: push hl
        ld hl, (vbl)
        inc hl
        ld (vbl), hl
        ld a, (in_snd)
        or a
        jr nz, vb_1
        inc a
        ld (in_snd), a
        push bc
        push de
        call snd_tick
        pop de
        pop bc
        xor a
        ld (in_snd), a
vb_1:   pop hl
        ret

; geo3d's RUN over (status bit 0), counting the blanks meanwhile. Keeps BC, DE, HL.
wait_geo:
        push bc
        push de
        ld de, 0
        ld c, WAIT_TURNS
wg_1:   call vpoll
        in a, (GEO_IDX)
        rrca
        jr nc, wg_2
        dec de
        ld a, d
        or e
        jr nz, wg_1
        dec c
        jr nz, wg_1
        ld a, 1
        ld (fail), a
        jp hw_fail
wg_2:   pop de
        pop bc
        ret

; the command in cmdbuf: A = first register (32 or 36), B = count
issue_cmd:
        push hl
        push bc
        push af
        call wait_ce
        pop af
        out (VDP_CTRL), a
        ld a, 0x80 + 17
        out (VDP_CTRL), a               ; R#17 = first register, auto-increment
        pop bc
        ld hl, cmdbuf
        ld c, VDP_IND
        otir
        pop hl
        ret

; HMMV / LMMV: HL = x, DE = y, BC = nx; (cmdbuf+6) = ny (word) set by caller
; through c_ny; A = colour byte; c_op = command byte
c_ny:       equ cmdbuf + 6
c_op:       equ cmdbuf + 10
fill_cmd:
        ld (cmdbuf + 8), a              ; CLR
        ld (cmdbuf + 0), hl             ; DX
        ld (cmdbuf + 2), de             ; DY
        ld (cmdbuf + 4), bc             ; NX
        xor a
        ld (cmdbuf + 9), a              ; ARG
        ld a, 36
        ld b, 11
        jp issue_cmd

; HMMV: HL = x, DE = y, BC = nx, IX = ny, A = colour byte
hmmv:   ld (c_ny), ix
        push af
        ld a, 0xC0
        ld (c_op), a
        pop af
        jr fill_cmd

; LMMV (IMP): HL = x, DE = y, BC = nx, IX = ny, A = colour
lmmv:   ld (c_ny), ix
        push af
        ld a, 0x80
        ld (c_op), a
        pop af
        jr fill_cmd

; copies: (cp_sx), (cp_sy), HL = dx, DE = dy, BC = nx, IX = ny, A = command
cp_sx:      equ tmp
cp_sy:      equ tmp + 2
copy_cmd:
        ld (cmdbuf + 14), a
        ld (cmdbuf + 4), hl
        ld (cmdbuf + 6), de
        ld (cmdbuf + 8), bc
        ld (cmdbuf + 10), ix
        ld hl, (cp_sx)
        ld (cmdbuf + 0), hl
        ld hl, (cp_sy)
        ld (cmdbuf + 2), hl
        xor a
        ld (cmdbuf + 12), a
        ld (cmdbuf + 13), a
        ld a, 32
        ld b, 15
        jp issue_cmd

; ----------------------------------------------------------------------------
; geo3d port helpers
gidx:   out (GEO_IDX), a                ; A = index
        ret

; A = low index, B = high index, HL = 10-bit value
g10:    out (GEO_IDX), a
        ld a, l
        out (GEO_DAT), a
        ld a, b
        out (GEO_IDX), a
        ld a, h
        and 3
        out (GEO_DAT), a
        ret

; ----------------------------------------------------------------------------
; small helpers
add_hl_a:                               ; HL += A (unsigned)
        add a, l
        ld l, a
        ret nc
        inc h
        ret

; HL = HL * A (unsigned 8 x 16 -> 16). Changes DE, B.
mul_hl_a:
        ex de, hl
        ld hl, 0
        ld b, 8
mha_1:  add hl, hl
        rla
        jr nc, mha_2
        add hl, de
mha_2:  djnz mha_1
        ret

; HL = -HL
neg_hl: xor a
        sub l
        ld l, a
        sbc a, a
        sub h
        ld h, a
        ret

; signed 16 x 16 -> 32: HL x DE -> (acc) (little-endian 4 bytes). Changes all.
mul16s: ld c, 0                         ; C = sign
        bit 7, h
        jr z, ms_1
        call neg_hl
        inc c
ms_1:   bit 7, d
        jr z, ms_2
        ex de, hl
        call neg_hl
        ex de, hl
        inc c
ms_2:   push bc
        call mul16u                     ; HL x DE -> DE:HL (high:low)
        pop bc
        bit 0, c
        jr z, ms_3
        ; negate DE:HL
        ld a, l
        cpl
        ld l, a
        ld a, h
        cpl
        ld h, a
        ld a, e
        cpl
        ld e, a
        ld a, d
        cpl
        ld d, a
        inc l
        jr nz, ms_3
        inc h
        jr nz, ms_3
        inc de
ms_3:   ld (acc), hl
        ld (acc + 2), de
        ret

; unsigned 16 x 16 -> 32: HL x DE -> DE:HL (the leading zeros of DE skipped)
mul16u: ld b, h
        ld c, l                         ; BC = multiplicand
        ld hl, 0
        ld a, d
        or e
        ret z                           ; x 0
        ld a, 16
mu_0:   dec a
        sla e
        rl d
        jr nc, mu_0                     ; the first 1 bit
        ld h, b
        ld l, c                         ; the product so far
        or a
        ret z
mu_1:   add hl, hl
        rl e
        rl d
        jr nc, mu_2
        add hl, bc
        jr nc, mu_2
        inc de
mu_2:   dec a
        jr nz, mu_1
        ret

; (acc) += (HL-pointed 32-bit)
add32:  ld de, acc
        ld a, (de)
        add a, (hl)
        ld (de), a
        inc hl
        inc de
        ld a, (de)
        adc a, (hl)
        ld (de), a
        inc hl
        inc de
        ld a, (de)
        adc a, (hl)
        ld (de), a
        inc hl
        inc de
        ld a, (de)
        adc a, (hl)
        ld (de), a
        ret

; HL = (acc) >> 14 (floor; the result fits 16 bits)
acc_sr14:
        ld a, (acc + 1)
        ld l, a
        ld a, (acc + 2)
        ld h, a
        ld a, (acc + 3)
        add hl, hl                      ; (acc >> 8) << 2 into A:H
        rla
        add hl, hl
        rla
        ld l, h
        ld h, a
        ret

; (acc) += 8192
acc_round:
        ld hl, (acc)
        ld de, 8192
        add hl, de
        ld (acc), hl
        ret nc
        ld hl, (acc + 2)
        inc hl
        ld (acc + 2), hl
        ret

; HL = (HL * DE + 8192) >> 14, signed. Changes all.
mulq14: call mul16s
        call acc_round
        jp acc_sr14

        include "asm/game.asm"
        include "asm/maze.asm"
        include "asm/render.asm"
        include "asm/hud.asm"
        include "asm/hw.asm"
        include "music.asm"
        include "out/inc/tab0.asm"

bank0_end:
        ds 0x8000 - bank0_end, 0xFF
