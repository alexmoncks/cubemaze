; SPDX-License-Identifier: MIT
; Copyright (c) 2026 Alex Moncks
; ============================================================================
; maze.asm - the random generator, the maze (the original's spanning tree
; over the six faces, depth first in a random order), the walls and their
; runs per face (zmodel.py face_walls, face_runs)
;
; A cell is ci = face * lv * lv + row * lv + column; grid[ci] has bit d set
; when the way out through direction d is open (0 up, 1 right, 2 down,
; 3 left, as the original).
; ============================================================================

game_init:
        ld hl, 0xF491
        ld (rng), hl
        ld hl, 0x2545
        ld (rng + 2), hl
        ld a, 3
        ld (lv), a
        ld (unl), a
        ld a, 9
        ld (rep), a
        xor a
        ld (oc_valid), a                ; (outside the cleared RAM)
        ; (everything else is 0 from the RAM clear)
        jp gen

; ----------------------------------------------------------------------------
; xorshift32: s ^= s << 13; s ^= s >> 17; s ^= s << 5. Keeps IX, IY.
rng_next:
        ld hl, (rng)
        ld de, (rng + 2)                ; s = DE:HL
        ; t = s << 13 = (s << 16) >> 3 ... build t in BC:A? use s << 8 then << 5
        ; t3 t2 t1 t0 = d? : (E, H, L, 0) << 5
        push hl
        push de
        ld b, e                         ; t3
        ld c, h                         ; t2
        ld d, l                         ; t1
        ld e, 0                         ; t0
        ld a, 5
rn_1:   sla e
        rl d
        rl c
        rl b
        dec a
        jr nz, rn_1
        ; s ^= t
        pop hl                          ; HL = s high (DE before)
        ld a, h
        xor b
        ld h, a
        ld a, l
        xor c
        ld l, a
        ex de, hl                       ; DE = new high, HL = t1:t0
        pop bc                          ; BC = s low
        ld a, b
        xor h
        ld b, a
        ld a, c
        xor l
        ld c, a                         ; s = DE:BC
        ; t = s >> 17 = (DE >> 1) as 16 bits; s low ^= t
        ld h, d
        ld l, e
        srl h
        rr l
        ld a, b
        xor h
        ld b, a
        ld a, c
        xor l
        ld c, a
        ; t = s << 5
        push de
        push bc
        ld h, b
        ld l, c                         ; HL = low, DE = high
        ld a, 5
rn_2:   add hl, hl
        rl e
        rl d
        dec a
        jr nz, rn_2
        pop bc
        ld a, c
        xor l
        ld c, a
        ld a, b
        xor h
        ld b, a
        pop hl
        ld a, l
        xor e
        ld l, a
        ld a, h
        xor d
        ld h, a
        ld (rng), bc
        ld (rng + 2), hl
        ret

; A = floor(rnd * n), n = B (2, 3 or 4): (s * n) >> 32
rng_below:
        push bc
        call rng_next
        pop bc
        ld a, (rng + 3)
        ld e, a
        ld a, b
        cp 3
        jr z, rb_3
        jr c, rb_2
        ld a, e                         ; n = 4: s >> 30
        rlca
        rlca
        and 3
        ret
rb_2:   ld a, e                         ; n = 2: s >> 31
        rlca
        and 1
        ret
rb_3:   ; n = 3: (s + 2s) >> 32
        ld hl, (rng)
        ld de, (rng + 2)
        push de
        push hl
        add hl, hl
        rl e
        rl d                            ; 2s (carry: bit 32)
        ld a, 0
        rla                             ; A = bit 32 of 2s
        pop bc
        add hl, bc
        pop bc
        ex de, hl
        adc hl, bc                      ; + s, carry: bit 32 of the sum
        adc a, 0
        ret

; A = a shuffled 0..3 as 2-bit fields (entry i at bits 2i): the original's
; Fisher-Yates (i = 3, 2, 1: j = floor(rnd * (i + 1)), swap a[i], a[j])
shuffle:
        ld hl, tmp
        ld (hl), 0
        inc hl
        ld (hl), 1
        inc hl
        ld (hl), 2
        inc hl
        ld (hl), 3
        ld b, 4
sh_1:   push bc
        call rng_below                  ; A = j
        pop bc
        ld hl, tmp
        call add_hl_a                   ; HL -> a[j]
        ld de, tmp - 1
        ld a, e
        add a, b
        ld e, a
        jr nc, sh_2
        inc d                           ; DE -> a[i], i = B - 1
sh_2:   ld a, (de)
        ld c, (hl)
        ld (hl), a
        ld a, c
        ld (de), a
        dec b
        ld a, b
        cp 2
        jr nc, sh_1
        ld a, (tmp + 3)
        rlca
        rlca
        ld hl, tmp + 2
        or (hl)
        rlca
        rlca
        dec hl
        or (hl)
        rlca
        rlca
        dec hl
        or (hl)
        ret

; ----------------------------------------------------------------------------
; gen: a new maze for size lv (and again while a face would not fit its slot)
; the maze, the geo3d blocks and the textures use mlv, the size of the maze:
; lv is the title's selection, which may differ from it
gen:    ld a, (lv)
        ld (mlv), a
gn_0:   call gen_once
        call build_faces
        jr c, gn_0
        ld hl, stage
        inc (hl)
        ret

gen_once:
        ; this size's constants
        ld a, (mlv)
        sub 3
        ld hl, T_LV
        or a
        jr z, go_2
        ld de, LV_SIZE
        ld b, a
go_1:   add hl, de
        djnz go_1
go_2:   ld de, lvc
        ld bc, LV_SIZE
        ldir
        ld a, (lvc + LV_NN)
        ld (nn), a
        ld a, (lvc + LV_NCELL)
        ld (ncell), a
        ; fnn[f] = f * nn, rlv[r] = r * lv
        ld hl, fnn
        ld b, 6
        xor a
gn_t1:  ld (hl), a
        inc hl
        ld de, nn
        ex de, hl
        add a, (hl)
        ex de, hl
        djnz gn_t1
        ld hl, rlv
        ld b, 6
        xor a
gn_t2:  ld (hl), a
        inc hl
        ld de, mlv
        ex de, hl
        add a, (hl)
        ex de, hl
        djnz gn_t2
        ; cf, cr, cc of every cell
        ld ix, 0                        ; IXL = cell
        ld d, 0                         ; face
gn_f:   ld e, 0                         ; row
gn_r:   ld c, 0                         ; column
gn_c:   push ix
        pop hl
        ld h, 0
        push hl
        ld a, l
        ld hl, cf
        call add_hl_a
        ld (hl), d
        pop hl
        push hl
        ld a, l
        ld hl, cr
        call add_hl_a
        ld (hl), e
        pop hl
        ld a, l
        ld hl, cc
        call add_hl_a
        ld (hl), c
        inc ix
        inc c
        ld a, (mlv)
        cp c
        jr nz, gn_c
        inc e
        cp e
        jr nz, gn_r
        inc d
        ld a, d
        cp 6
        jr nz, gn_f
        ; the neighbours (nbr: 4 per cell) from the bank table
        ld a, TBANK2
        call setbank
        ld hl, (lvc + LV_PMV)
        ld de, nbr
        ld a, (ncell)
        ld b, a
gn_n1:  push bc
        ld b, 4
gn_n2:  ld a, (hl)
        ld (de), a
        inc hl
        inc hl
        inc de
        djnz gn_n2
        pop bc
        djnz gn_n1
        ; clear the maze
        ld hl, grid
        ld de, grid + 1
        ld bc, 215
        ld (hl), 0
        ldir
        xor a
        ld (act), a
        ld (mv_on), a
        ld (roll_on), a
        ld (orient), a
        ld hl, 0
        ld (el), hl
        ld (rot), hl
        ld (el_sec), hl
        xor a
        ld (el_sub), a
        ld hl, 179
        ld (prv), hl
        ; start = (0, lv >> 1, lv >> 1)
        ld a, (mlv)
        srl a
        ld b, a
        ld hl, 0
        ld a, (mlv)
        ld c, a
        ld a, b
        or a
        jr z, gn_s1
gn_s0:  ld a, l
        add a, c
        ld l, a
        djnz gn_s0
gn_s1:  ld a, (mlv)
        srl a
        add a, l                        ; (lv >> 1) * lv + (lv >> 1)
        ld (cur), a
        ld (st), a
        ld (gl), a
        ld (tmp + 6), a                 ; tmp+6: the deepest cell, tmp+7: its depth
        xor a
        ld (tmp + 7), a
        ; depth first: IY -> the top entry (cell, depth, dirs, next)
        ld a, TBANK2
        call setbank
        ld iy, dfs
        ld a, (cur)
        ld c, 0
        call dfs_enter
gn_loop:
        ld a, (iy + 3)
        cp 4
        jr nz, gn_l1
        ; pop
        ld de, -4
        add iy, de
        push iy
        pop hl
        ld de, dfs
        or a
        sbc hl, de
        jr nc, gn_loop                  ; IY >= dfs: go on
        jr gn_done
gn_l1:  inc (iy + 3)
        ld b, a                         ; B = index
        ld a, (iy + 2)
        inc b
gn_l2:  dec b
        jr z, gn_l3
        rrca
        rrca
        jr gn_l2
gn_l3:  and 3
        ld c, a                         ; C = d
        ; n, din = MV[p][d]
        ld l, (iy + 0)
        ld h, 0
        add hl, hl
        add hl, hl
        add hl, hl
        ld a, c
        add a, a
        call add_hl_a
        ld de, (lvc + LV_PMV)
        add hl, de
        ld e, (hl)                      ; E = n
        inc hl
        ld d, (hl)                      ; D = din
        ld hl, grid
        ld a, e
        call add_hl_a
        ld a, (hl)
        or a
        jr nz, gn_loop
        ; carve: grid[n] |= 1 << ((din + 2) & 3); grid[p] |= 1 << d
        ld a, d
        add a, 2
        and 3
        call bit_of
        or (hl)
        ld (hl), a
        ld hl, grid
        ld a, (iy + 0)
        call add_hl_a
        ld a, c
        call bit_of
        or (hl)
        ld (hl), a
        ld a, (iy + 1)
        inc a
        ld c, a
        ld a, e
        ld de, 4
        add iy, de
        call dfs_enter
        jr gn_loop
gn_done:
        call build_n2
        ld a, (tmp + 6)
        ld (gl), a
        ld hl, cf
        call add_hl_a
        ld a, (hl)
        ld (gl_face), a
        ret

; A = 1 << A (A = 0..3)
bit_of: ld b, a
        inc b
        ld a, 0x80
bo_1:   rlca
        djnz bo_1
        ret

; push (A = cell, C = depth) at IY: the deepest cell, then a shuffle
dfs_enter:
        ld (iy + 0), a
        ld (iy + 1), c
        ld (iy + 3), 0
        ld b, a
        ld a, (tmp + 7)
        cp c
        jr nc, de_1
        ld a, c
        ld (tmp + 7), a
        ld a, b
        ld (tmp + 6), a
de_1:   push iy
        call shuffle
        pop iy
        ld (iy + 2), a
        ld a, TBANK2                    ; (shuffle keeps the bank, but be safe)
        jp setbank

; ----------------------------------------------------------------------------
; the walls and runs of the six faces; carry: a face has too many runs
build_faces:
        ld hl, wcnt
        ld de, wcnt + 1
        ld bc, 215
        ld (hl), 0
        ldir
        ld ix, walls
        ld iy, runs
        xor a
bf_f:   ld (cur_face), a
        ld e, a
        ld d, 0
        ld hl, walls_p
        add hl, de
        add hl, de
        push ix
        pop bc
        ld (hl), c
        inc hl
        ld (hl), b
        ld hl, runs_p
        add hl, de
        add hl, de
        push iy
        pop bc
        ld (hl), c
        inc hl
        ld (hl), b
        ld hl, walls_n
        add hl, de
        ld (hl), 0
        ld hl, runs_n
        add hl, de
        ld (hl), 0
        ; walls: (tu, tv, ci, d) in the original's edge order
        ld b, 0                         ; row
bf_r:   ld c, 0                         ; column
bf_c:   call ci_of                      ; A = ci
        ld (tmp), a
        ld hl, grid
        call add_hl_a
        ld a, (hl)
        ld (tmp + 1), a                 ; its passage bits
        xor a
bf_d:   ld (tmp + 2), a                 ; d
        ; listed: d < 2, or d == 3 and c == 0, or d == 2 and r == lv - 1
        cp 2
        jr c, bf_d1
        cp 3
        jr z, bf_d3
        ld a, (mlv)
        dec a
        cp b
        jr nz, bf_dn
        jr bf_d1
bf_d3:  ld a, c
        or a
        jr nz, bf_dn
bf_d1:  ld a, (tmp + 2)
        ld e, a
        inc e
        ld a, (tmp + 1)
bf_d2:  rrca
        dec e
        jr nz, bf_d2                    ; carry = passage bit
        jr c, bf_dn
        call wall_t                     ; D = tu, E = tv
        ; the cell's first wall and count (wptr, wcnt)
        push de
        ld a, (tmp)
        ld hl, wcnt
        call add_hl_a
        ld a, (hl)
        inc (hl)
        or a
        jr nz, bf_w1
        ld a, (tmp)
        ld l, a
        ld h, 0
        add hl, hl
        ld de, wptr
        add hl, de
        push ix
        pop de
        ld (hl), e
        inc hl
        ld (hl), d
bf_w1:  pop de
        ld (ix + 0), d
        ld (ix + 1), e
        ld a, (tmp)
        ld (ix + 2), a
        ld a, (tmp + 2)
        ld (ix + 3), a
        ld de, 4
        add ix, de
        ld a, (cur_face)
        ld hl, walls_n
        call add_hl_a
        inc (hl)
bf_dn:  ld a, (tmp + 2)
        inc a
        cp 4
        jp c, bf_d
        inc c
        ld a, (mlv)
        cp c
        jp nz, bf_c
        inc b
        cp b
        jp nz, bf_r
        call face_runs
        ; the count against the slot
        ld a, (cur_face)
        ld hl, runs_n
        call add_hl_a
        ld b, (hl)
        ld a, (gl_face)
        ld hl, cur_face
        cp (hl)
        ld a, (lvc + LV_RMAXN)
        jr nz, bf_m
        ld a, (lvc + LV_RMAXG)
bf_m:   cp b
        ret c                           ; more runs than allowed: carry
        ld a, (cur_face)
        inc a
        cp 6
        jp c, bf_f
        or a
        ret

; B = row, C = column of cur_face -> A = ci. Keeps BC, DE, HL.
ci_of:  push hl
        ld hl, fnn
        ld a, (cur_face)
        call add_hl_a
        ld a, (hl)
        ld hl, rlv
        add a, c
        push af
        ld a, b
        call add_hl_a
        pop af
        add a, (hl)
        pop hl
        ret

; the wall (B row, C column, (tmp + 2) d) -> D = tu, E = tv (half cells)
wall_t: ld hl, mlv
        ld a, c
        add a, a
        inc a
        sub (hl)
        ld d, a                         ; 2c + 1 - lv
        ld a, b
        add a, a
        inc a
        sub (hl)
        ld e, a                         ; 2r + 1 - lv
        ld a, (tmp + 2)
        or a
        jr z, wt_0
        dec a
        jr z, wt_1
        dec a
        jr z, wt_2
        dec d                           ; 3: left
        ret
wt_0:   dec e                           ; 0: up
        ret
wt_1:   inc d                           ; 1: right
        ret
wt_2:   inc e                           ; 2: down
        ret

; the runs of cur_face at IY: (o, line, ta, tb), runs_n counted
face_runs:
        ; horizontal lines k = 0 .. lv (v = 2k - lv): d 0 of row k, or d 2
        ; of row lv - 1 for k = lv
        ld b, 0
frh_k:  ld a, 0xFF
        ld (tmp + 3), a                 ; no run open
        ld c, 0                         ; segment: column
frh_s:  push bc
        ld e, 1
        ld a, (mlv)
        cp b
        jr nz, frh_1
        dec b
        ld e, 4
frh_1:  call ci_of
        pop bc
        ld hl, grid
        call add_hl_a
        ld a, (hl)
        and e                           ; Z: a wall
        ld d, 0
        call run_step
        inc c
        ld a, (mlv)
        cp c
        jr nz, frh_s
        ld d, 0
        call run_close
        inc b
        ld a, (mlv)
        inc a
        cp b
        jr nz, frh_k
        ; vertical lines k = 0 .. lv (u = 2k - lv): d 3 of column 0 for k = 0,
        ; else d 1 of column k - 1
        ld b, 0
frv_k:  ld a, 0xFF
        ld (tmp + 3), a
        ld c, 0                         ; segment: row
frv_s:  push bc
        ld a, b
        ld e, 8
        or a
        jr z, frv_1
        dec a
        ld e, 2
frv_1:  ld b, c                         ; row
        ld c, a                         ; column
        call ci_of
        pop bc
        ld hl, grid
        call add_hl_a
        ld a, (hl)
        and e
        ld d, 1
        call run_step
        inc c
        ld a, (mlv)
        cp c
        jr nz, frv_s
        ld d, 1
        call run_close
        inc b
        ld a, (mlv)
        inc a
        cp b
        jr nz, frv_k
        ret

; Z: a wall at segment C of line B (orientation D): open or extend the run;
; NZ: close the open run
run_step:
        jr nz, run_close
        ld a, (tmp + 3)
        cp 0xFF
        jr nz, rs_1
        ld a, c
        ld (tmp + 3), a
rs_1:   ld a, c
        ld (tmp + 4), a
        ret

; close the open run (if any) of line B, orientation D. Keeps BC.
run_close:
        ld a, (tmp + 3)
        cp 0xFF
        ret z
        ld (iy + 0), d                  ; o
        ld hl, mlv
        ld a, b
        add a, a
        sub (hl)
        ld (iy + 1), a                  ; line = 2k - lv
        ld a, (tmp + 3)
        add a, a
        inc a
        sub (hl)
        ld (iy + 2), a                  ; ta = 2 s + 1 - lv
        ld a, (tmp + 4)
        add a, a
        inc a
        sub (hl)
        ld (iy + 3), a                  ; tb
        ld de, 4
        add iy, de
        ld a, (cur_face)
        ld hl, runs_n
        call add_hl_a
        inc (hl)
        ld a, 0xFF
        ld (tmp + 3), a
        ret

; ----------------------------------------------------------------------------
; n2tab[cell]: the count, then the cells at most 2 steps away (breadth
; first: the cell, its 4 neighbours in direction order, theirs), 14 bytes
build_n2:
        ld hl, n2tab
        ld (n2_p), hl
        xor a
bn_c:   ld (n2_c), a
        ld hl, (n2_p)
        ld (hl), 1                      ; count
        inc hl
        ld (hl), a                      ; the cell itself
        ld a, 1
        ld (n2_lo), a                   ; frontier: entries 1 .. 2 (exclusive)
        inc a
        ld (n2_hi), a
        ld b, 2
bn_s:   push bc
        ld a, (n2_lo)
bn_f:   ld hl, n2_hi
        cp (hl)
        jr z, bn_fe
        jr nc, bn_fe
        push af
        ; the cell at entry A (1-based) -> its 4 neighbours
        ld hl, (n2_p)
        call add_hl_a
        ld l, (hl)
        ld h, 0
        add hl, hl
        add hl, hl
        ld de, nbr
        add hl, de
        ld b, 4
bn_n:   push bc
        ld a, (hl)
        inc hl
        push hl
        call n2_put
        pop hl
        pop bc
        djnz bn_n
        pop af
        inc a
        jr bn_f
bn_fe:  ld hl, n2_hi                    ; next frontier: the entries added
        ld a, (hl)
        ld (n2_lo), a
        ld hl, (n2_p)
        ld a, (hl)
        inc a
        ld (n2_hi), a
        pop bc
        djnz bn_s
        ld hl, (n2_p)
        ld de, 14
        add hl, de
        ld (n2_p), hl
        ld a, (n2_c)
        inc a
        ld hl, ncell
        cp (hl)
        jr c, bn_c
        ret

; A = cell: appended to the current n2tab entry unless already there
n2_put: ld c, a
        ld hl, (n2_p)
        ld b, (hl)                      ; count
        inc hl
np_1:   ld a, (hl)
        cp c
        ret z
        inc hl
        djnz np_1
        ld (hl), c
        ld hl, (n2_p)
        inc (hl)
        ret

n2_p:       equ RAM + 0x48C
n2_c:       equ RAM + 0x48E
n2_lo:      equ RAM + 0x48F
n2_hi:      equ RAM + 0x4D0
