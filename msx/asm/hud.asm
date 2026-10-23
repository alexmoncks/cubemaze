; SPDX-License-Identifier: MIT
; Copyright (c) 2026 Alex Moncks
; ============================================================================
; hud.asm - the texts and bars over the picture (zmodel.py Machine.hud)
;
; A text: its box filled with the colour (HMMV), then each 24 x 14 glyph
; cell ANDed over it from the masks of page 2 (LMMM, AND): ink keeps the
; colour, paper and the gaps become black. Positions are the original's
; (160 x 144), through T_HX / T_HY.
; ============================================================================

hud:    call dy_page
        ld a, (ph)
        or a
        jr z, hd_title
        cp 5
        jr z, hd_title
        jp hd_play

; ----------------------------------------------------------------------------
; The title and the code screen: the two bars, then four text rows (14 lines,
; the bar's width), each drawn into its cache (ROW_Y) when its key changes
; and copied every frame (HMMM). The rows share page 0's lines 212-253 with
; the play bars' caches: a change of mode (cmode) empties the other's.
hd_title:
        ld a, (cmode)
        cp 1
        jr z, ht_0
        ld a, 1
        ld (cmode), a
        ld a, 0xFF
        ld (rkeys), a
        ld (rkeys + 8), a
        ld (rkeys + 16), a
        ld (rkeys + 24), a
ht_0:   ld de, 2 * 256 + 20
        call bar
        ld de, 104 * 256 + 142
        call bar
        ; row 0: the title (the same key on both screens)
        call rk_clear
        ld (hl), 1
        ld bc, 0 * 256 + 7
        call row_chk
        jr z, ht_r0
        ld bc, 32 * 256 + 7
        ld a, 7
        ld hl, s_title
        call text
ht_r0:  ld bc, 0 * 256 + 7
        call row_put
        ld a, (ph)
        or a
        jp nz, hd_code
        ; row 1: the sizes: "3x3", "[4x4]" (selected), "5x?" (locked)
        call rk_clear
        inc hl                          ; (ph = 0)
        ld a, (lv)
        ld (hl), a
        inc hl
        ld a, (unl)
        ld (hl), a
        ld bc, 1 * 256 + 110
        call row_chk
        jr z, ht_r1
        ld b, 3
ht_1:   push bc
        ld hl, nbuf
        ld a, (unl)
        cp b
        jr nc, ht_2
        ; locked: "sx?", colour 1
        ld a, b
        add a, '0'
        ld (hl), a
        inc hl
        ld (hl), 'x'
        inc hl
        ld (hl), '?'
        inc hl
        ld (hl), 0
        ld c, 1
        ld d, 0
        jr ht_4
ht_2:   ld a, (lv)
        cp b
        jr nz, ht_3
        ld (hl), '['
        inc hl
        call put_lx
        ld (hl), ']'
        inc hl
        ld (hl), 0
        ld c, 6
        ld d, 8
        jr ht_4
ht_3:   call put_lx
        ld (hl), 0
        ld c, 7
        ld d, 0
ht_4:   ; x = 16 + 36 (s - 3) - D
        ld a, b
        sub 3
        ld e, a
        add a, a
        add a, a
        add a, a
        add a, e                        ; 9 i
        add a, a
        add a, a                        ; 36 i
        add a, 16
        sub d
        ld b, a
        ld a, c
        ld c, 110
        ld hl, nbuf
        call text
        pop bc
        inc b
        ld a, b
        cp 7
        jr c, ht_1
ht_r1:  ld bc, 1 * 256 + 110
        call row_put
        ; row 2: BEST:n, ESC:CODE
        call rk_clear
        inc hl
        call best_of_lv
        ld (hl), e
        inc hl
        ld (hl), d
        ld bc, 2 * 256 + 121
        call row_chk
        jr z, ht_r2
        ld hl, nbuf
        ld de, s_best
        call put_str
        call best_of_lv
        call put_dec
        ld (hl), 0
        ld bc, 8 * 256 + 121
        ld a, 5
        ld hl, nbuf
        call text
        ld bc, 94 * 256 + 121
        ld a, 5
        ld hl, s_esccode
        call text
ht_r2:  ld bc, 2 * 256 + 121
        call row_put
        ; row 3: ARW:SEL SPACE:START
        call rk_clear
        ld bc, 3 * 256 + 131
        call row_chk
        jr z, ht_r3
        ld bc, 4 * 256 + 131
        ld a, 6
        ld hl, s_arwsel
        call text
ht_r3:  ld bc, 3 * 256 + 131
        jp row_put

; "sxs" of B at HL (HL moves on)
put_lx: ld a, b
        add a, '0'
        ld (hl), a
        inc hl
        ld (hl), 'x'
        inc hl
        ld (hl), a
        inc hl
        ret

hd_code:
        ; row 1: CODE: and the four letters (the one edited in colour 6)
        call rk_clear
        ld (hl), 5
        inc hl
        ex de, hl
        ld hl, code
        ld bc, 4
        ldir
        ld a, (cpos)
        ld (de), a
        ld bc, 1 * 256 + 110
        call row_chk
        jr z, hc_r1
        ld bc, 16 * 256 + 110
        ld a, 7
        ld hl, s_code
        call text
        ld b, 0
hc_1:   push bc
        ld hl, code
        ld a, b
        call add_hl_a
        ld a, (hl)
        ld hl, T_CODEABC
        call add_hl_a
        ld a, (hl)
        ld hl, nbuf
        ld (hl), a
        inc hl
        ld (hl), 0
        ld a, (cpos)
        cp b
        ld c, 7
        jr nz, hc_2
        ld c, 6
hc_2:   ld a, b
        add a, a
        add a, a
        add a, a
        add a, 64
        ld b, a
        ld a, c
        ld c, 110
        ld hl, nbuf
        call text
        pop bc
        inc b
        ld a, b
        cp 4
        jr c, hc_1
hc_r1:  ld bc, 1 * 256 + 110
        call row_put
        ; row 2: ARW:EDIT SPACE:OK
        call rk_clear
        ld (hl), 5
        ld bc, 2 * 256 + 121
        call row_chk
        jr z, hc_r2
        ld bc, 8 * 256 + 121
        ld a, 5
        ld hl, s_arwedit
        call text
hc_r2:  ld bc, 2 * 256 + 121
        call row_put
        ; row 3: ESC:BACK
        call rk_clear
        ld (hl), 5
        ld bc, 3 * 256 + 131
        call row_chk
        jr z, hc_r3
        ld bc, 8 * 256 + 131
        ld a, 6
        ld hl, s_escback
        call text
hc_r3:  ld bc, 3 * 256 + 131
        jp row_put

; rkey_new = 0 (8 bytes); HL = rkey_new
rk_clear:
        ld hl, rkey_new
        ld b, 8
rkc_1:  ld (hl), 0
        inc hl
        djnz rkc_1
        ld hl, rkey_new
        ret

; B = row, C = its original y. rkey_new vs the row's key: Z, the same; else
; NZ: the key stored, the row's cache cleared (HMMV, colour 0) and hud_dy set
; so that text at y lands in it
row_chk:
        push bc
        ld a, b
        add a, a
        add a, a
        add a, a
        ld hl, rkeys
        call add_hl_a
        ex de, hl                       ; DE = the row's key
        push de
        ld hl, rkey_new
        ld b, 8
        call cmp_n
        pop de
        pop bc
        ret z
        push bc
        ld hl, rkey_new
        ld bc, 8
        ldir
        pop bc
        push bc
        call row_y                      ; HL = ROW_Y[B]
        push hl
        ex de, hl
        ld hl, HX0
        ld bc, HX160 - HX0
        ld ix, 14
        xor a
        call hmmv
        pop hl
        pop bc
        push bc
        ld a, c
        call hy_of                      ; DE = T_HY[y]
        or a
        sbc hl, de
        ld (hud_dy), hl
        pop bc
        or 1                            ; NZ
        ret

; B = row, C = its original y: the row's cache to the hidden page
row_put:
        push bc
        call row_y
        ld (cp_sy), hl
        ld hl, HX0
        ld (cp_sx), hl
        pop bc
        ld a, c
        call hy_of
        ld a, (pg)
        add a, d
        ld d, a                         ; DE = 256 pg + T_HY[y]
        ld hl, HX0
        ld bc, HX160 - HX0
        ld ix, 14
        ld a, 0xD0
        jp copy_cmd

; B = row -> HL = ROW_Y[B]
row_y:  ld a, b
        add a, a
        ld hl, row_ys
        call add_hl_a
        ld a, (hl)
        inc hl
        ld h, (hl)
        ld l, a
        ret

row_ys:     dw 468, 212, 226, 240

; A = original y -> DE = T_HY[A]
hy_of:  push hl
        ld hl, T_HY
        call add_hl_a
        ld e, (hl)
        ld d, 0
        pop hl
        ret

; ----------------------------------------------------------------------------
hd_play:
        ld a, (cmode)
        cp 2
        jr z, hp_m
        ld a, 2
        ld (cmode), a
        ld a, 0xFF
        ld (cbot), a
        ld (ctop), a
        ld (hkey), a
hp_m:   ; the top bar's key: size, face, rotations, seconds; unchanged: the
        ; cached bar is right
        ld hl, hkey_new
        ld a, (lv)
        ld (hl), a
        inc hl
        ld a, (act)
        ld (hl), a
        inc hl
        ld de, (rot)
        ld (hl), e
        inc hl
        ld (hl), d
        inc hl
        ld de, (el_sec)
        ld (hl), e
        inc hl
        ld (hl), d
        ld hl, hkey_new
        ld de, hkey
        ld b, 6
        call cmp_n
        jp z, hp_c
        ld hl, hkey_new
        ld de, hkey
        ld bc, 6
        ldir
        ; the top bar's texts: tbuf ("6x6 F1/6 R:0"), tmbuf (time)
        ld hl, tbuf
        ld a, (lv)
        ld b, a
        call put_lx
        ld (hl), ' '
        inc hl
        ld (hl), 'F'
        inc hl
        ld a, (act)
        add a, '1'
        ld (hl), a
        inc hl
        ld de, s_of6r
        call put_str
        ld de, (rot)
        call put_dec
        ld (hl), 0
        ld hl, tmbuf
        call put_time
        ld (hl), 0
        ; changed since the cache was drawn?
        ld hl, tbuf
        ld de, ctop
        ld b, 32
        call cmp_n
        jr z, hp_c
        ld hl, tbuf
        ld de, ctop
        ld bc, 32
        ldir
        ld hl, 212
        ld (hud_dy), hl
        ld de, 0 * 256 + 12
        call bar
        ld bc, 3 * 256 + 2
        ld a, 7
        ld hl, tbuf
        call text
        ld bc, 116 * 256 + 2
        ld a, 6
        ld hl, tmbuf
        call text
        call dy_page
hp_c:   ld a, 0
        ld de, 212
        call bar_copy
        ld a, (ph)
        cp 3
        jp nc, hd_clear
        cp 1
        jr nz, hp_2
        ; the countdown: prv // 60 + 1
        ld hl, (prv)
        ld c, 60
        call div16_8
        ld a, l
        inc a                           ; 1 .. 3
        cp 4
        jr nc, hp_2
        ld hl, T_BIG1
        cp 1
        jr z, hp_1
        ld hl, T_BIG2
        cp 2
        jr z, hp_1
        ld hl, T_BIG3
hp_1:   push hl
        ld bc, 66 * 256 + 58
        xor a
        call big_digit
        pop hl
        ld bc, 64 * 256 + 56
        ld a, C7
        call big_digit
hp_2:   ld a, (ph)
        ld hl, cbot
        cp (hl)
        jr z, hp_4
        ld (hl), a
        ld hl, BOT_DY
        ld (hud_dy), hl
        ld de, 132 * 256 + 144
        call bar
        ld a, (ph)
        cp 1
        ld hl, s_preview
        ld a, 6
        ld b, 4
        jr z, hp_3
        ld hl, s_arwroll
        ld a, 5
        ld b, 8
hp_3:   ld c, 134
        call text
        call dy_page
hp_4:   ld a, 132
        ld de, BOT_DY
        jp bar_copy

BOT_DY:     equ 230 - 194

; hud_dy = 256 * pg: draw on the hidden page
dy_page:
        ld a, (pg)
        ld h, a
        ld l, 0
        ld (hud_dy), hl
        ret

; Z: the B bytes at HL and DE are the same
cmp_n:  ld a, (de)
        cp (hl)
        ret nz
        inc hl
        inc de
        djnz cmp_n
        ret

; a cached bar to the hidden page: A = its first original line, DE = the
; cache's offset (line in VRAM = DE + HY[A]); 18 lines
bar_copy:
        ld hl, T_HY
        call add_hl_a
        ld l, (hl)
        ld h, 0
        push hl
        add hl, de
        ld (cp_sy), hl
        ld hl, HX0
        ld (cp_sx), hl
        pop de
        ld hl, (hud_dy)
        add hl, de
        ex de, hl                       ; DE = 256 pg + HY[A]
        ld hl, HX0
        ld bc, HX160 - HX0
        ld ix, 18
        ld a, 0xD0
        jp copy_cmd

hd_clear:
        ld de, 29 * 256 + 113
        call bar
        ld a, (ph)
        cp 4
        ld hl, s_allclr
        jr z, hc_t
        ld hl, nbuf
        ld de, s_stage
        call put_str
        ld a, (lv)
        ld b, a
        call put_lx
        ld de, s_clear
        call put_str
        ld (hl), 0
        ld hl, nbuf
hc_t:   ld bc, 16 * 256 + 35
        ld a, 6
        call text
        ; TIME:m:ss ROT:n
        ld hl, nbuf
        ld de, s_time
        call put_str
        call put_time
        ld de, s_rot
        call put_str
        ld de, (rot)
        call put_dec
        ld (hl), 0
        ld bc, 16 * 256 + 47
        ld a, 7
        ld hl, nbuf
        call text
        ld hl, nbuf
        ld de, s_score
        call put_str
        ld de, (sc)
        call put_dec
        ld (hl), 0
        ld bc, 16 * 256 + 58
        ld a, 5
        ld hl, nbuf
        call text
        ld hl, nbuf
        ld de, s_best
        call put_str
        call best_of_lv
        call put_dec
        ld (hl), 0
        ld bc, 16 * 256 + 69
        ld a, 5
        ld hl, nbuf
        call text
        ld a, (unl)
        cp 4
        jr c, hcl_1
        ld hl, nbuf
        ld de, s_code
        call put_str
        ld a, (unl)
        sub 4
        add a, a
        add a, a
        ld de, T_CODES
        ex de, hl
        call add_hl_a
        ex de, hl
        ld b, 4
hcl_0:  ld a, (de)
        ld (hl), a
        inc hl
        inc de
        djnz hcl_0
        ld (hl), 0
        ld bc, 16 * 256 + 80
        ld a, 4
        ld hl, nbuf
        call text
hcl_1:  ; SPACE:4x4 ESC:TITLE (3x3 after 6x6)
        ld hl, nbuf
        ld de, s_space
        call put_str
        ld a, (ph)
        cp 4
        ld b, 3
        jr z, hcl_2
        ld a, (lv)
        inc a
        ld b, a
hcl_2:  call put_lx
        ld de, s_esctitle
        call put_str
        ld (hl), 0
        ld bc, 4 * 256 + 97
        ld a, 7
        ld hl, nbuf
        jp text

; HL -> buffer: "m:ss" of el (ticks)
put_time:
        push hl
        ld hl, (el)
        ld c, 60
        call div16_8                    ; seconds
        ld c, 60
        call div16_8                    ; HL = minutes, A = seconds
        ld b, a
        ex de, hl
        pop hl
        push bc
        call put_dec                    ; minutes
        pop bc
        ld (hl), ':'
        inc hl
        ld a, b
        ld c, '0' - 1
pt_t1:  inc c
        sub 10
        jr nc, pt_t1
        add a, 10 + '0'
        ld (hl), c
        inc hl
        ld (hl), a
        inc hl
        ret

; DE = the best score of this size. Keeps HL.
best_of_lv:
        push hl
        ld a, (lv)
        sub 3
        add a, a
        ld hl, best
        call add_hl_a
        ld e, (hl)
        inc hl
        ld d, (hl)
        pop hl
        ret

; HL -> buffer, DE = value (unsigned): its digits; HL moves on
put_dec:
        ld (pd_buf), hl
        ex de, hl
        ld b, 0
pd_1:   push bc
        ld c, 10
        call div16_8
        pop bc
        push af
        inc b
        ld a, h
        or l
        jr nz, pd_1
        ld hl, (pd_buf)
pd_2:   pop af
        add a, '0'
        ld (hl), a
        inc hl
        djnz pd_2
        ret

; HL -> buffer, DE -> zero-terminated text: copied (HL moves on)
put_str:
        ld a, (de)
        or a
        ret z
        ld (hl), a
        inc hl
        inc de
        jr put_str

; ----------------------------------------------------------------------------
; bar: D = y0, E = y1 (original lines): black, a line of colour 1 at each edge
bar:    push de
        ld hl, T_HY
        ld a, d
        call add_hl_a
        ld a, (hl)
        ld (tmp + 4), a                 ; a
        pop de
        ld hl, T_HY
        ld a, e
        call add_hl_a
        ld a, (hl)
        ld (tmp + 5), a                 ; b
        ld hl, tmp + 4
        sub (hl)
        ld c, a
        ld b, 0
        push bc
        pop ix                          ; IX = b - a
        call bar_y                      ; DE = ypage + a
        ld hl, HX0
        ld bc, HX160 - HX0
        xor a
        call hmmv
        call bar_y
        ld hl, HX0
        ld bc, HX160 - HX0
        ld ix, 1
        ld a, C1 * 17
        call hmmv
        ld a, (tmp + 5)
        dec a
        ld hl, (hud_dy)
        call add_hl_a
        ex de, hl
        ld hl, HX0
        ld bc, HX160 - HX0
        ld ix, 1
        ld a, C1 * 17
        jp hmmv

bar_y:  ld a, (tmp + 4)
        ld hl, (hud_dy)
        call add_hl_a
        ex de, hl
        ret

; ----------------------------------------------------------------------------
; text: B = x, C = y (original), A = colour (original), HL -> zero-terminated
text:   push hl
        ld hl, cmap
        call add_hl_a
        ld a, (hl)
        ld (txt_col), a
        ld l, b
        ld h, 0
        add hl, hl
        ld de, T_HX
        add hl, de
        ld e, (hl)
        inc hl
        ld d, (hl)
        ld (txt_x), de
        ld hl, T_HY
        ld a, c
        call add_hl_a
        ld a, (hl)
        ld hl, (hud_dy)
        call add_hl_a
        ld (txt_y), hl
        pop hl
        push hl
        ld b, 0
tx_1:   ld a, (hl)
        or a
        jr z, tx_2
        inc hl
        inc b
        jr tx_1
tx_2:   ld l, b
        ld h, 0
        ld a, ADV
        call mul_hl_a
        ld b, h
        ld c, l                         ; BC = 24 n
        ld a, (txt_col)
        ld e, a
        rlca
        rlca
        rlca
        rlca
        or e
        ld hl, (txt_x)
        ld de, (txt_y)
        ld ix, 14
        call hmmv
        pop hl
tx_3:   ld a, (hl)
        or a
        ret z
        push hl
        call glyph
        ld hl, (txt_x)
        ld de, ADV
        add hl, de
        ld (txt_x), hl
        pop hl
        inc hl
        jr tx_3

; LMMM (AND) of the glyph cell of character A (32..127) to (txt_x, txt_y)
glyph:  sub 32
        ld l, a
        ld h, 0
        add hl, hl
        add hl, hl
        ld de, T_GCELL4
        add hl, de
        call wait_ce
        ld a, 32
        out (VDP_CTRL), a
        ld a, 0x80 + 17
        out (VDP_CTRL), a
        ld c, VDP_IND
        outi
        outi
        outi
        outi                            ; SX, SY
        ld hl, (txt_x)
        out (c), l
        out (c), h                      ; DX
        ld hl, (txt_y)
        out (c), l
        out (c), h                      ; DY
        ld a, ADV
        out (c), a
        xor a
        out (c), a                      ; NX
        ld a, 14
        out (c), a
        xor a
        out (c), a                      ; NY
        out (c), a                      ; CLR
        out (c), a                      ; ARG
        ld a, 0x91
        out (c), a                      ; LMMM, AND
        ret

; big_digit: HL -> runs (r, c0, c1; FFh), B = x, C = y (original), A = colour index
big_digit:
        ld (txt_col), a
        ld a, b
        ld (bd_x), a
        ld a, c
        ld (bd_y), a
bd_1:   ld a, (hl)
        cp 0xFF
        ret z
        ld (bd_r), a
        inc hl
        ld a, (hl)
        ld (bd_c0), a
        inc hl
        ld a, (hl)
        ld (bd_c1), a
        inc hl
        push hl
        ld a, (bd_c1)
        add a, a
        add a, a
        ld hl, bd_x
        add a, (hl)
        call hx_of
        push hl                         ; X1
        ld a, (bd_c0)
        add a, a
        add a, a
        ld hl, bd_x
        add a, (hl)
        call hx_of                      ; HL = X0
        pop de
        push hl
        ex de, hl
        or a
        sbc hl, de
        ld b, h
        ld c, l                         ; BC = X1 - X0
        ld a, (bd_r)
        add a, a
        add a, a
        ld hl, bd_y
        add a, (hl)
        ld (bd_t), a
        ld hl, T_HY
        call add_hl_a
        ld e, (hl)                      ; Y0
        ld a, (bd_t)
        add a, 4
        ld hl, T_HY
        call add_hl_a
        ld a, (hl)
        sub e
        ld l, a
        ld h, 0
        push hl
        pop ix                          ; NY
        ld a, e
        ld hl, (hud_dy)
        call add_hl_a
        ex de, hl                       ; DE = hud_dy + Y0
        pop hl                          ; X0
        ld a, (txt_col)
        rlca
        rlca
        rlca
        rlca
        push hl
        ld hl, txt_col
        or (hl)
        pop hl
        call hmmv
        pop hl
        jr bd_1

bd_x:       equ RAM + 0x470
bd_y:       equ RAM + 0x471
bd_r:       equ RAM + 0x472
bd_c0:      equ RAM + 0x473
bd_c1:      equ RAM + 0x474
bd_t:       equ RAM + 0x475
pd_buf:     equ RAM + 0x476
hud_dy:     equ RAM + 0x488             ; 2: line offset of the HUD's drawing
cbot:       equ RAM + 0x48A             ; the bottom bar cached (ph; FFh none)
tbuf:       equ RAM + 0x490             ; 24 + 8: the top bar's texts now
tmbuf:      equ tbuf + 24
ctop:       equ RAM + 0x4B0             ; 32: those of the cached bar
hkey:       equ RAM + 0x4DA             ; 6: the key of the cached top bar
hkey_new:   equ RAM + 0x4E0             ; 6
rkeys:      equ RAM + 0x2270            ; 4 x 8: the keys of the cached text rows
rkey_new:   equ RAM + 0x2290            ; 8
cmode:      equ RAM + 0x2298            ; the caches' mode: 1 title / code, 2 play

; A = original column -> HL = T_HX[A]
hx_of:  ld l, a
        ld h, 0
        add hl, hl
        push de
        ld de, T_HX
        add hl, de
        pop de
        ld a, (hl)
        inc hl
        ld h, (hl)
        ld l, a
        ret

cmap:   db C0, C1, C2, C3, C4, C5, C6, C7

s_title:    db "CUBE MAZE 3D", 0
s_best:     db "BEST:", 0
s_esccode:  db "ESC:CODE", 0
s_arwsel:   db "ARW:SEL SPACE:START", 0
s_code:     db "CODE:", 0
s_arwedit:  db "ARW:EDIT SPACE:OK", 0
s_escback:  db "ESC:BACK", 0
s_of6r:     db "/6 R:", 0
s_preview:  db "PREVIEW SPACE:START", 0
s_arwroll:  db "ARW:ROLL ESC:RETRY", 0
s_allclr:   db "ALL 6x6 CLEARED!", 0
s_stage:    db "STAGE ", 0
s_clear:    db " CLEAR!", 0
s_time:     db "TIME:", 0
s_rot:      db " ROT:", 0
s_score:    db "SCORE:", 0
s_space:    db "SPACE:", 0
s_esctitle: db " ESC:TITLE", 0
