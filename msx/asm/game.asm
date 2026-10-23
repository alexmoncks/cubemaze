; SPDX-License-Identifier: MIT
; Copyright (c) 2026 Alex Moncks
; ============================================================================
; game.asm - one tick of the game (60 a second), as zmodel.py Game.tick
;
; Buttons (bits of keyheld / keyp): 0 up, 1 down, 2 left, 3 right, 4 A
; (SPACE, trigger A), 5 B (ESC, trigger B).
; Phases: 0 title, 1 preview, 2 play, 3 stage clear, 4 all clear, 5 code.
; ============================================================================

tick:
        call read_keys                  ; A = held
        ld b, a
        ld a, (keyheld)
        ld (keyprev), a
        cpl
        and b
        ld (keyp), a
        ld a, b
        ld (keyheld), a
        ld hl, (tick_t)
        inc hl
        ld (tick_t), hl
        ld hl, (t628)
        inc hl
        ld de, SPIN_N
        or a
        sbc hl, de
        add hl, de
        jr nz, tk_1
        ld hl, 0
tk_1:   ld (t628), hl
        ld a, (t42)
        inc a
        cp GOAL_N
        jr c, tk_2
        xor a
tk_2:   ld (t42), a
        call cam_take
        ld a, (ph)
        or a
        jp z, ph_title
        dec a
        jp z, ph_preview
        dec a
        jp z, ph_play
        dec a
        jp z, ph_clear
        dec a
        jp z, ph_clear
        jp ph_code

; the camera of this tick (before its logic, as the original)
cam_take:
        ld a, (ph)
        ld hl, (t628)
        ld (cam_t), hl
        ld b, a
        ld a, (orient)
        ld (cam_o), a
        xor a
        ld (cam_a), a
        ld (cam_k), a
        ld a, (roll_on)
        or a
        jr z, ct_1
        ld a, (roll_a)
        ld (cam_a), a
        ld a, (roll_k)
        ld (cam_k), a
ct_1:   ld a, b
        ld c, 0
        cp 2
        jr c, ct_k                      ; 0, 1: spin
        cp 5
        jr z, ct_k                      ; 5: spin
        inc c
        cp 2
        jr z, ct_k                      ; 2: play
        inc c                           ; 3, 4: clear
ct_k:   ld a, c
        ld (cam_kind), a
        ret

; A = stp: +1 right / down, -1 left / up, 0 none (the original's
; btnp(3) - btnp(2) || btnp(1) - btnp(0))
get_stp:
        ld a, (keyp)
        ld c, a
        xor a
        bit 3, c
        jr z, gs_1
        inc a
gs_1:   bit 2, c
        jr z, gs_2
        dec a
gs_2:   or a
        ret nz
        bit 1, c
        jr z, gs_3
        inc a
gs_3:   bit 0, c
        ret z
        dec a
        ret

; ----------------------------------------------------------------------------
ph_title:
        call rng_next
        call get_stp
        or a
        jr z, pt_2
        ld hl, lv
        add a, (hl)
        cp 3
        jr nc, pt_0
        ld a, 3
pt_0:   ld hl, unl
        cp (hl)
        jr c, pt_1
        ld a, (hl)
pt_1:   ld (lv), a
        xor a
        call sfx_play
pt_2:   ld a, (keyp)
        bit 5, a
        jr z, pt_3
        ld a, 5
        ld (ph), a
        xor a
        ld (cpos), a
        jp sfx_play                     ; (A = 0)
pt_3:   bit 4, a
        ret z
        ld a, (lv)
        jp go

go:     ld (lv), a                      ; A = size
        call gen
        ld a, 1
        ld (ph), a
        jp sfx_play

; ----------------------------------------------------------------------------
ph_code:
        call rng_next
        ld a, (keyp)
        and 3
        jr z, pc_2
        ld hl, code
        ld a, (cpos)
        call add_hl_a
        ld a, (keyp)
        rrca
        ld a, (hl)
        jr nc, pc_dn
        inc a                           ; up: next letter
        cp NCODE_ABC
        jr c, pc_1
        xor a
        jr pc_1
pc_dn:  or a
        jr nz, pc_d1
        ld a, NCODE_ABC
pc_d1:  dec a
pc_1:   ld (hl), a
        xor a
        call sfx_play
        jr pc_4
pc_2:   ld a, (keyp)
        and 12
        jr z, pc_4
        ld hl, cpos
        and 8
        jr z, pc_l
        ld a, (hl)
        cp 3
        jr nc, pc_3
        inc (hl)
        jr pc_3
pc_l:   ld a, (hl)
        or a
        jr z, pc_3
        dec (hl)
pc_3:   xor a
        call sfx_play
pc_4:   ld a, (keyp)
        bit 4, a
        jr z, pc_esc
        ; the code: 6, 5, 4 in T_CODES (4 letters each, the codes of 4, 5, 6)
        ld b, 6
pc_c1:  ld a, b
        sub 4
        add a, a
        add a, a
        ld hl, T_CODES
        call add_hl_a
        ld de, code
        ld c, 4
pc_c2:  push hl
        ld a, (de)
        ld hl, T_CODEABC
        call add_hl_a
        ld a, (hl)
        pop hl
        cp (hl)
        jr nz, pc_c3
        inc hl
        inc de
        dec c
        jr nz, pc_c2
        ; found: B
        ld a, (unl)
        cp b
        jr nc, pc_c4
        ld a, b
        ld (unl), a
pc_c4:  xor a
        ld (ph), a
        ld a, 1
        jp sfx_play
pc_c3:  dec b
        ld a, b
        cp 4
        jr nc, pc_c1
        ld a, 2
        jp sfx_play
pc_esc: bit 5, a
        ret z
        xor a
        ld (ph), a
        ret

; ----------------------------------------------------------------------------
ph_preview:
        ld hl, (prv)
        dec hl
        ld (prv), hl
        bit 7, h
        jr nz, pp_go
        ld a, h
        or l
        jr z, pp_go
        ld a, (keyp)
        bit 4, a
        jr z, pp_1
pp_go:  ld a, 2
        ld (ph), a
pp_1:   ld a, (keyp)
        bit 5, a
        ret z
        ld a, (lv)
        jp go

; ----------------------------------------------------------------------------
ph_clear:
        ld a, (keyp)
        bit 4, a
        jr z, pcl_1
        ld a, (ph)
        cp 3
        ld a, 3
        jp nz, go
        ld a, (lv)
        cp 6
        ld a, 3
        jp nc, go
        ld a, (lv)
        inc a
        jp go
pcl_1:  bit 5, a
        ret z
        xor a
        ld (ph), a
        ret

; ----------------------------------------------------------------------------
ph_play:
        ld hl, (el)
        inc hl
        ld a, h
        or l
        jr z, pl_0                      ; saturates at 65535
        ld (el), hl
        ld hl, el_sub                   ; el_sec = el // 60 (for the HUD)
        inc (hl)
        ld a, (hl)
        cp 60
        jr c, pl_0
        ld (hl), 0
        ld hl, (el_sec)
        inc hl
        ld (el_sec), hl
pl_0:   ld a, (keyp)
        bit 5, a
        jr z, pl_1
        ld a, (lv)
        jp go
pl_1:   ; the ball's move
        ld a, (mv_on)
        or a
        jr z, pl_roll
        ld hl, mv_j
        inc (hl)
        ld a, (hl)
        cp J_END
        jr c, pl_roll
        xor a
        ld (mv_on), a
        ld a, (cur)
        ld hl, gl
        cp (hl)
        jr nz, pl_roll
        call goal_reached
pl_roll:
        ld a, (roll_on)
        or a
        jr z, pl_in
        ld hl, roll_k
        inc (hl)
        ld a, (hl)
        cp K_END
        jr c, pl_in
        xor a
        ld (roll_on), a
        ld a, (orient)                  ; orient = ROLLNEXT[orient][roll_a]
        add a, a
        add a, a
        ld hl, roll_a
        add a, (hl)
        ld hl, T_ROLLNEXT
        call add_hl_a
        ld a, (hl)
        ld (orient), a
pl_in:  ld a, (mv_on)
        ld hl, roll_on
        or (hl)
        ret nz
        ; the key: the first of 0..3 pressed now, or held with the repeat run out
        ld a, (keyp)
        ld d, a
        ld a, (keyheld)
        ld e, a
        ld b, 0
pl_k1:  ld a, d
        and 1
        jr nz, pl_kf
        ld a, e
        and 1
        jr z, pl_k2
        ld hl, rep
        dec (hl)
        bit 7, (hl)
        jr nz, pl_kf
pl_k2:  srl d
        srl e
        inc b
        ld a, b
        cp 4
        jr c, pl_k1
pl_kf:  ld a, (keyheld)
        and 15
        jr nz, pl_k3
        ld a, 9
        ld (rep), a
pl_k3:  ld a, b
        cp 4
        ret nc
        ld a, 9
        ld (rep), a
        ; dir = DIRMAP[orient][sD]
        ld a, (orient)
        add a, a
        add a, a
        add a, b
        ld hl, T_DIRMAP
        call add_hl_a
        ld c, (hl)                      ; C = dir
        ld a, (cur)
        ld hl, grid
        call add_hl_a
        ld a, (hl)
        ld b, c
        inc b
pl_b:   rrca
        djnz pl_b                       ; carry = bit dir
        jr c, pl_mv
        ld a, 2
        jp sfx_play
pl_mv:  ; nx = MV[cur][dir]
        ld a, (cur)
        call mv_of                      ; A = cell, C = dir -> A = next cell
        ld b, a
        ld a, (cur)
        ld (mv_from), a
        ld a, b
        ld (mv_to), a
        xor a
        ld (mv_j), a
        inc a
        ld (mv_on), a
        ld a, b
        ld hl, cf
        call add_hl_a
        ld c, (hl)                      ; C = new face
        ld a, (cur)
        ld hl, cf
        call add_hl_a
        ld a, (hl)
        cp c
        ld a, b
        ld (cur), a
        ld a, c
        ld (act), a
        jr z, pl_same
        ld hl, (rot)
        inc hl
        ld (rot), hl
        ; roll axis = ROLLAX[orient][new face]
        ld a, (orient)
        ld b, a
        add a, a
        add a, b
        add a, a                        ; x 6
        add a, c
        ld hl, T_ROLLAX
        call add_hl_a
        ld a, (hl)
        ld (roll_a), a
        xor a
        ld (roll_k), a
        inc a
        ld (roll_on), a
        ld a, 1
        jp sfx_play
pl_same:
        xor a
        jp sfx_play

; A = cell, C = direction -> A = the next cell (nbr, built by gen)
mv_of:  ld l, a
        ld h, 0
        add hl, hl
        add hl, hl
        ld a, c
        call add_hl_a
        ld de, nbr
        add hl, de
        ld a, (hl)
        ret

goal_reached:
        ld a, 3
        call sfx_play
        ; sc = max(0, (60003 - el - 300 rot) // 6)
        ld hl, 60003
        ld de, (el)
        or a
        sbc hl, de
        jr c, gr_0
        push hl
        ld hl, (rot)
        ld de, 201
        or a
        sbc hl, de
        pop hl
        jr nc, gr_0
        push hl
        ld hl, (rot)
        ld a, 300 & 0xFF
        ld de, 300
        call mul16u                     ; HL = 300 rot (fits)
        ex de, hl
        pop hl
        or a
        sbc hl, de
        jr c, gr_0
        ld c, 6
        call div16_8
        jr gr_1
gr_0:   ld hl, 0
gr_1:   ld (sc), hl
        ; best[lv - 3]
        ld a, (lv)
        sub 3
        add a, a
        ld de, best
        ex de, hl
        call add_hl_a
        ld e, (hl)
        inc hl
        ld d, (hl)                      ; DE = best
        push hl
        ld hl, (sc)
        or a
        sbc hl, de
        pop hl
        jr z, gr_2
        jr c, gr_2
        ld de, (sc)
        ld (hl), d
        dec hl
        ld (hl), e
gr_2:   ld a, (unl)
        ld b, a
        ld a, (lv)
        cp b
        jr c, gr_3
        ld a, b
        cp 6
        jr nc, gr_3
        ld a, (lv)
        inc a
        ld (unl), a
gr_3:   ld a, (lv)
        cp 6
        ld a, 3
        jr c, gr_4
        inc a
gr_4:   ld (ph), a
        ret

; HL = HL / C (unsigned), A = remainder
div16_8:
        xor a
        ld b, 16
dv_1:   add hl, hl
        rla
        jr c, dv_2
        cp c
        jr c, dv_3
dv_2:   sub c
        inc l
dv_3:   djnz dv_1
        ret
